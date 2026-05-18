from typing import Any, Dict, Optional, List
import logging
import os
import time
from langgraph.graph import StateGraph, START, END
from .state import DSStarState
from .agents import DSStarAgents
from .azure_client import AzureLLM, get_default_llm
from .events import EventBus
from .memory import HyperMemory
from .evaluator import evaluate_run
from .meta_controller import analyze_run as meta_analyze_run, generate_alternative_strategies
from .strategy_retriever import (
    retrieve_strategies,
    retrieve_anti_patterns,
    retrieve_similar_runs,
    format_context_block,
)

_graph_logger = logging.getLogger("ds_star.graph")


def build_graph() -> StateGraph:
    """
    Build LangGraph state machine for DS-STAR workflow.

    State shape carried through the graph is a dict with:
      - obj: DSStarState (mutable)
      - agents: DSStarAgents (helper object holding LLM client + exec utilities)
    """
    graph = StateGraph(dict)

    # --- Nodes (each receives and returns a mapping) ---

    def prepare_context_node(state: Dict[str, Any]) -> Dict[str, Any]:
        obj: DSStarState = state["obj"]
        agents: DSStarAgents = state["agents"]
        memory: Optional[HyperMemory] = state.get("memory")

        agents.emit("node_started", node="prepare_context", iteration=0, status="running")

        if memory is not None:
            try:
                hits = retrieve_strategies(obj.query, agents.llm, memory, top_k=5)
                obj.retrieved_strategies = [h["strategy_text"] for h in hits]
                obj.anti_patterns = retrieve_anti_patterns(memory, top_k=5)
                obj.similar_runs = retrieve_similar_runs(obj.query, agents.llm, memory, top_k=3)
                if obj.retrieved_strategies:
                    agents.emit("strategy_retrieved", node="prepare_context",
                                payload={"count": len(obj.retrieved_strategies)})
            except Exception as exc:
                _graph_logger.warning("prepare_context failed (non-fatal): %s", exc)
                obj.retrieved_strategies = []
                obj.anti_patterns = []
                obj.similar_runs = []

        agents.emit("node_finished", node="prepare_context", iteration=0, status="ok",
                     payload={"strategies": len(obj.retrieved_strategies),
                              "anti_patterns": len(obj.anti_patterns),
                              "similar_runs": len(obj.similar_runs)})
        return {"obj": obj, "agents": agents, "memory": memory}

    def analyze_node(state: Dict[str, Any]) -> Dict[str, Any]:
        obj: DSStarState = state["obj"]
        agents: DSStarAgents = state["agents"]
        agents.logger.info("=" * 50)
        agents.logger.info("PHASE 1: ANALYZING DATA FILES")
        agents.logger.info("=" * 50)
        agents.emit("node_started", node="analyze", iteration=obj.iteration, status="running")
        obj = agents.analyze_files(obj)
        agents.emit("node_finished", node="analyze", iteration=obj.iteration, status="ok", payload={"descriptions": len(obj.data_descriptions)})
        return {"obj": obj, "agents": agents, "memory": state.get("memory")}

    def init_impl_node(state: Dict[str, Any]) -> Dict[str, Any]:
        obj: DSStarState = state["obj"]
        agents: DSStarAgents = state["agents"]
        agents.logger.info("=" * 50)
        agents.logger.info("PHASE 2: INITIAL PLANNING & IMPLEMENTATION")
        agents.logger.info("=" * 50)
        agents.emit("node_started", node="init_impl", iteration=obj.iteration, status="running")
        obj = agents.initial_plan(obj)
        obj = agents.implement_initial(obj)
        agents.emit("node_finished", node="init_impl", iteration=obj.iteration, status="ok", payload={"exit_code": obj.execution_result.exit_code, "artifacts": len(obj.execution_result.artifacts)})
        return {"obj": obj, "agents": agents, "memory": state.get("memory")}

    def verify_node(state: Dict[str, Any]) -> Dict[str, Any]:
        obj: DSStarState = state["obj"]
        agents: DSStarAgents = state["agents"]
        agents.emit("node_started", node="verify", iteration=obj.iteration, status="running")
        obj = agents.verify(obj)
        agents.emit("node_finished", node="verify", iteration=obj.iteration, status="ok", payload={"verified": obj.verified})
        return {"obj": obj, "agents": agents, "memory": state.get("memory")}

    def route_node(state: Dict[str, Any]) -> Dict[str, Any]:
        obj: DSStarState = state["obj"]
        agents: DSStarAgents = state["agents"]
        agents.emit("node_started", node="route", iteration=obj.iteration, status="running")
        obj = agents.route(obj)
        agents.emit("node_finished", node="route", iteration=obj.iteration, status="ok", payload={"decision": obj.router_decision})
        return {"obj": obj, "agents": agents, "memory": state.get("memory")}

    def refine_node(state: Dict[str, Any]) -> Dict[str, Any]:
        obj: DSStarState = state["obj"]
        agents: DSStarAgents = state["agents"]
        agents.emit("node_started", node="refine", iteration=obj.iteration, status="running")
        decision = obj.router_decision
        if isinstance(decision, str) and decision.startswith("step:"):
            try:
                step_idx = int(decision.split(":")[1])
            except Exception:
                step_idx = len(obj.plans)
            obj = agents.refine_fix_step(obj, step_index_1based=step_idx)
        elif decision == "change_strategy":
            obj.plans = obj.plans[:1]
            obj.codes_per_step = obj.codes_per_step[:1]
            obj.base_code = obj.codes_per_step[0] if obj.codes_per_step else ""
            obj.current_code = obj.base_code
            obj = agents.refine_add_step(obj)
        elif decision == "rerun_analysis":
            obj = agents.analyze_files(obj)
            obj = agents.refine_add_step(obj)
        elif decision == "retrieve_files":
            obj.retrieved_indices = None
            obj = agents.refine_add_step(obj)
        else:
            # default or 'add'
            obj = agents.refine_add_step(obj)
        # increment iteration after a refine cycle
        obj.iteration += 1
        agents.emit("node_finished", node="refine", iteration=obj.iteration, status="ok", payload={"decision": decision, "exit_code": obj.execution_result.exit_code})
        return {"obj": obj, "agents": agents, "memory": state.get("memory")}

    def meta_reflect_node(state: Dict[str, Any]) -> Dict[str, Any]:
        """Mid-loop reflection: triggered when stuck (2+ verify fails or high iteration)."""
        obj: DSStarState = state["obj"]
        agents: DSStarAgents = state["agents"]

        threshold = max(3, obj.max_iterations // 4)
        needs_reflection = (
            obj.consecutive_verify_fails >= 2 or obj.iteration >= threshold
        )

        if not needs_reflection:
            return {"obj": obj, "agents": agents, "memory": state.get("memory")}

        agents.emit("node_started", node="meta_reflect", iteration=obj.iteration, status="running")
        agents.logger.info("META-REFLECT: Agent is stuck, generating alternative strategies")

        try:
            alternatives = generate_alternative_strategies(obj, agents.llm)
            if alternatives:
                obj.retrieved_strategies = list(set(
                    obj.retrieved_strategies + alternatives
                ))
                agents.emit("strategy_injected", node="meta_reflect",
                            iteration=obj.iteration,
                            payload={"new_strategies": len(alternatives)})
        except Exception as exc:
            _graph_logger.warning("meta_reflect failed (non-fatal): %s", exc)

        obj.consecutive_verify_fails = 0

        agents.emit("node_finished", node="meta_reflect", iteration=obj.iteration, status="ok")
        return {"obj": obj, "agents": agents, "memory": state.get("memory")}

    def finalize_node(state: Dict[str, Any]) -> Dict[str, Any]:
        obj: DSStarState = state["obj"]
        agents: DSStarAgents = state["agents"]
        agents.logger.info("=" * 50)
        agents.logger.info("PHASE 3: FINALIZING")
        agents.logger.info("=" * 50)
        agents.emit("node_started", node="finalize", iteration=obj.iteration, status="running")
        obj = agents.finalize(obj)
        agents.emit("node_finished", node="finalize", iteration=obj.iteration, status="ok", payload={"answer": obj.final_answer})
        return {"obj": obj, "agents": agents, "memory": state.get("memory")}

    def meta_learn_node(state: Dict[str, Any]) -> Dict[str, Any]:
        """Post-run: evaluate, classify failure, store learnings."""
        obj: DSStarState = state["obj"]
        agents: DSStarAgents = state["agents"]
        memory: Optional[HyperMemory] = state.get("memory")

        agents.emit("node_started", node="meta_learn", iteration=obj.iteration, status="running")

        # Evaluate run
        try:
            score_dict = evaluate_run(obj, llm=agents.llm)
            obj.run_score = score_dict
        except Exception as exc:
            _graph_logger.warning("Run evaluation failed (non-fatal): %s", exc)
            score_dict = {"score": 0.5, "quality": "medium", "failure_type": "none"}
            obj.run_score = score_dict

        # Meta-analyze and store learnings
        if memory is not None:
            try:
                meta = meta_analyze_run(obj, agents.llm)
                obj.failure_type = meta.get("failure_type", obj.failure_type)
                strategy_text = meta.get("strategy")

                final_score = score_dict.get("score", 0.5)
                ft = obj.failure_type or "none"

                # Store strategy if one was generated
                if strategy_text:
                    q_emb = agents.llm.embed([obj.query])[0]
                    memory.store_strategy(
                        strategy_text=strategy_text,
                        success_score=final_score,
                        embedding=q_emb,
                        failure_type=ft,
                    )
                    agents.emit("learning_saved", node="meta_learn",
                                payload={"strategy": strategy_text[:200],
                                         "failure_type": ft})

                # Store anti-pattern if run failed
                if final_score < 0.4 and ft != "none":
                    reason = meta.get("reason", "")
                    if reason:
                        memory.store_anti_pattern(ft, reason)

                # Did strategies help? Compare score to similar past runs
                did_help = (
                    bool(obj.retrieved_strategies) and final_score >= 0.6
                )

                # Archive the run
                try:
                    q_emb_for_run = agents.llm.embed([obj.query])[0]
                except Exception:
                    q_emb_for_run = None
                memory.store_run(
                    run_id=agents.run_id,
                    query=obj.query,
                    files_used=obj.data_files,
                    score=final_score,
                    iterations=obj.iteration,
                    failure_type=ft,
                    strategies_used=obj.retrieved_strategies,
                    did_strategy_help=did_help,
                    query_embedding=q_emb_for_run,
                )
                agents.emit("run_archived", node="meta_learn",
                            payload={"score": final_score, "failure_type": ft,
                                     "did_strategy_help": did_help})

            except Exception as exc:
                _graph_logger.warning("Meta-learn storage failed (non-fatal): %s", exc)

        agents.emit("node_finished", node="meta_learn", iteration=obj.iteration, status="ok",
                     payload={"score": score_dict.get("score"),
                              "failure_type": obj.failure_type})
        return {"obj": obj, "agents": agents, "memory": memory}

    # --- Register nodes ---
    graph.add_node("prepare_context", prepare_context_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("init_impl", init_impl_node)
    graph.add_node("verify", verify_node)
    graph.add_node("route", route_node)
    graph.add_node("meta_reflect", meta_reflect_node)
    graph.add_node("refine", refine_node)
    graph.add_node("finalize", finalize_node)
    graph.add_node("meta_learn", meta_learn_node)

    # --- Edges ---
    graph.add_edge(START, "prepare_context")
    graph.add_edge("prepare_context", "analyze")
    graph.add_edge("analyze", "init_impl")
    graph.add_edge("init_impl", "verify")

    def verification_router(state: Dict[str, Any]) -> str:
        obj: DSStarState = state["obj"]
        agents: DSStarAgents = state["agents"]

        # HARD CIRCUIT BREAKER: Force exit if iteration exceeds max
        # This prevents ANY infinite loops at the graph level
        if obj.iteration >= obj.max_iterations:
            agents.emit("circuit_breaker_triggered", node="verify", iteration=obj.iteration,
                       status="warning", payload={"reason": f"Hard limit reached: {obj.iteration}/{obj.max_iterations}"})
            to = "done"
        elif obj.verified:
            to = "done"
        else:
            to = "refine"

        agents.emit("edge_chosen", node="verify", iteration=obj.iteration, status="ok",
                   payload={"from": "verify", "to": ("finalize" if to == "done" else "route"),
                           "verified": obj.verified, "iteration": obj.iteration,
                           "max_iterations": obj.max_iterations})
        return to

    graph.add_conditional_edges(
        "verify",
        verification_router,
        {
            "done": "finalize",
            "refine": "route",
        },
    )
    graph.add_edge("route", "meta_reflect")
    graph.add_edge("meta_reflect", "refine")
    graph.add_edge("refine", "verify")
    graph.add_edge("finalize", "meta_learn")
    graph.add_edge("meta_learn", END)

    return graph


def run_ds_star_agent(
    query: str,
    data_files: List[str],
    max_iterations: int = 20,
    guidelines: Optional[str] = None,
    data_dir: str = "data",
    llm: Optional[AzureLLM] = None,
    workdir: Optional[str] = None,
    event_bus: Optional[EventBus] = None,
    run_id: Optional[str] = None,
    memory: Optional[HyperMemory] = None,
):
    """
    High-level entry point to execute DS-STAR pipeline with LangGraph.
    - query: question string
    - data_files: list of filenames located under `data_dir/`
    - guidelines: optional finalization formatting rules
    - llm: optional injected AzureLLM client. If None, uses environment variables (get_default_llm)
    - workdir: working directory where 'data/' and 'final/' are resolved; defaults to os.getcwd()
    Returns the final DSStarState.
    """
    workdir = workdir or os.getcwd()
    os.makedirs(os.path.join(workdir, "final"), exist_ok=True)

    llm = llm or get_default_llm()

    # Prepare event bus and run id
    event_bus = event_bus or EventBus()
    run_id = run_id or f"run-{int(time.time() * 1000)}"
    event_bus.create_run(run_id)
    event_bus.emit_dict("run_started", run_id=run_id, payload={"query": query, "data_files": data_files, "max_iterations": max_iterations})

    # Auto-create HyperMemory if not provided
    if memory is None:
        try:
            memory = HyperMemory()
        except Exception:
            memory = None

    agents = DSStarAgents(llm=llm, workdir=workdir, event_bus=event_bus, run_id=run_id)

    # Log pipeline start
    agents.logger.info("=" * 50)
    agents.logger.info(f"STARTING PIPELINE: {run_id}")
    agents.logger.info("=" * 50)
    agents.logger.info(f"Query: {query[:100]}...")
    agents.logger.info(f"Data files: {data_files}")

    state = DSStarState(
        query=query,
        data_dir=data_dir,
        data_files=data_files,
        max_iterations=max_iterations,
        guidelines=guidelines,
    )

    graph = build_graph().compile()
    final_mapping = graph.invoke(
        {"obj": state, "agents": agents, "memory": memory},
        {"recursion_limit": 100},
    )
    final_state: DSStarState = final_mapping["obj"]

    # Log pipeline completion
    agents.logger.info("=" * 50)
    agents.logger.info("PIPELINE COMPLETED SUCCESSFULLY!")
    agents.logger.info("=" * 50)

    # Emit run finished
    event_bus.emit_dict(
        "run_finished",
        run_id=run_id,
        status="ok",
        payload={
            "verified": final_state.verified,
            "answer": final_state.final_answer,
            "exit_code": final_state.execution_result.exit_code,
        },
    )
    return final_state
