"""Orchestration router: native AgentField orchestration replacing LangGraph."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional

from agentfield import AgentRouter

from llm_bridge import get_agents, get_workdir, create_llm
from state_adapter import state_to_response

logger = logging.getLogger(__name__)

orchestration_router = AgentRouter(prefix="orchestration", tags=["pipeline"])


def _exec_result_to_dict(er) -> dict:
    return {
        "stdout": er.stdout,
        "stderr": er.stderr,
        "exit_code": er.exit_code,
        "artifacts": er.artifacts,
    }


def _descriptions_to_dicts(descs) -> List[Dict[str, str]]:
    return [{"filename": d.filename, "summary": d.summary} for d in descs]


def _build_full_state(params: dict):
    """Build a DSStarState from accumulated orchestrator params."""
    from ds_star.state import DSStarState, Description, ExecutionResult

    descs = [Description(**d) for d in params.get("descriptions", [])]
    er_dict = params.get("execution_result")
    er = ExecutionResult(**er_dict) if er_dict else ExecutionResult()

    return DSStarState(
        query=params.get("query", ""),
        data_dir=params.get("data_dir", "data"),
        data_files=params.get("data_files", []),
        max_iterations=params.get("max_iterations", 20),
        guidelines=params.get("guidelines"),
        data_descriptions=descs,
        plans=params.get("plans", []),
        base_code=params.get("base_code", ""),
        current_code=params.get("current_code", ""),
        codes_per_step=params.get("codes_per_step", []),
        execution_result=er,
        verified=params.get("verified", False),
        router_decision=params.get("router_decision"),
        iteration=params.get("iteration", 0),
        retrieved_strategies=params.get("strategies", []),
        anti_patterns=params.get("anti_patterns", []),
        similar_runs=params.get("similar_runs", []),
        consecutive_verify_fails=params.get("consecutive_verify_fails", 0),
        failure_type=params.get("failure_type"),
    )


# ---------------------------------------------------------------------------
# Sub-reasoners: each becomes a separate node in the AgentField DAG
# ---------------------------------------------------------------------------


@orchestration_router.reasoner()
async def prepare_context(query: str) -> dict:
    """Retrieve strategies, anti-patterns, and similar runs from HyperMemory."""
    from ds_star.memory import HyperMemory
    from ds_star.strategy_retriever import (
        retrieve_strategies,
        retrieve_anti_patterns,
        retrieve_similar_runs,
    )

    workdir = get_workdir()
    memory_path = os.path.join(workdir, "hyper_memory.db")
    strategies: List[str] = []
    anti_patterns: List[Dict] = []
    similar_runs: List[Dict] = []

    try:
        memory = HyperMemory(db_path=memory_path)
        llm = create_llm()
        hits = await asyncio.to_thread(retrieve_strategies, query, llm, memory, 5)
        strategies = [h["strategy_text"] for h in hits]
        anti_patterns = await asyncio.to_thread(retrieve_anti_patterns, memory, 5)
        similar_runs = await asyncio.to_thread(retrieve_similar_runs, query, llm, memory, 3)
    except Exception as e:
        logger.warning("prepare_context failed (non-fatal): %s", e)

    return {
        "strategies": strategies,
        "anti_patterns": anti_patterns,
        "similar_runs": similar_runs,
    }


@orchestration_router.reasoner()
async def analyze(
    query: str,
    data_files: List[str],
    data_dir: str = "data",
) -> dict:
    """Analyze data files and produce descriptions."""
    from ds_star.state import DSStarState

    workdir = get_workdir()
    agents = get_agents(workdir)
    state = DSStarState(query=query, data_files=data_files, data_dir=data_dir)

    state = await asyncio.to_thread(agents.analyze_files, state)

    return {"descriptions": _descriptions_to_dicts(state.data_descriptions)}


@orchestration_router.reasoner()
async def plan_and_code(
    query: str,
    descriptions: List[Dict[str, str]],
    guidelines: str = "",
    strategies: Optional[List[str]] = None,
    anti_patterns: Optional[List[Dict]] = None,
) -> dict:
    """Create initial plan and implement the first step."""
    from ds_star.state import DSStarState, Description

    workdir = get_workdir()
    agents = get_agents(workdir)
    desc_objs = [Description(**d) for d in descriptions]

    state = DSStarState(
        query=query,
        data_files=[d["filename"] for d in descriptions],
        data_descriptions=desc_objs,
        guidelines=guidelines,
        retrieved_strategies=strategies or [],
        anti_patterns=anti_patterns or [],
    )

    state = await asyncio.to_thread(agents.initial_plan, state)
    state = await asyncio.to_thread(agents.implement_initial, state)

    return {
        "plans": state.plans,
        "base_code": state.base_code,
        "current_code": state.current_code,
        "codes_per_step": state.codes_per_step,
        "execution_result": _exec_result_to_dict(state.execution_result),
    }


@orchestration_router.reasoner()
async def verify_result(
    query: str,
    plans: List[str],
    current_code: str,
    execution_result: Dict[str, Any],
    iteration: int = 0,
    max_iterations: int = 20,
    consecutive_verify_fails: int = 0,
) -> dict:
    """Verify whether the analysis answers the query."""
    from ds_star.state import DSStarState, ExecutionResult

    workdir = get_workdir()
    agents = get_agents(workdir)
    er = ExecutionResult(**execution_result)

    state = DSStarState(
        query=query,
        data_files=[],
        plans=plans,
        current_code=current_code,
        execution_result=er,
        iteration=iteration,
        max_iterations=max_iterations,
        consecutive_verify_fails=consecutive_verify_fails,
    )

    state = await asyncio.to_thread(agents.verify, state)

    return {
        "verified": state.verified,
        "failure_type": state.failure_type,
        "consecutive_verify_fails": state.consecutive_verify_fails,
    }


@orchestration_router.reasoner()
async def route_decision(
    query: str,
    descriptions: List[Dict[str, str]],
    plans: List[str],
    execution_result: Dict[str, Any],
    strategies: Optional[List[str]] = None,
    anti_patterns: Optional[List[Dict]] = None,
) -> dict:
    """Decide the next refinement action."""
    from ds_star.state import DSStarState, Description, ExecutionResult

    workdir = get_workdir()
    agents = get_agents(workdir)
    desc_objs = [Description(**d) for d in descriptions]
    er = ExecutionResult(**execution_result)

    state = DSStarState(
        query=query,
        data_files=[d["filename"] for d in descriptions],
        data_descriptions=desc_objs,
        plans=plans,
        execution_result=er,
        retrieved_strategies=strategies or [],
        anti_patterns=anti_patterns or [],
    )

    state = await asyncio.to_thread(agents.route, state)

    return {"decision": state.router_decision}


@orchestration_router.reasoner()
async def refine(
    query: str,
    descriptions: List[Dict[str, str]],
    plans: List[str],
    codes_per_step: List[str],
    base_code: str,
    current_code: str,
    execution_result: Dict[str, Any],
    router_decision: str,
    iteration: int = 0,
    guidelines: str = "",
    strategies: Optional[List[str]] = None,
    data_files: Optional[List[str]] = None,
    data_dir: str = "data",
) -> dict:
    """Execute the refinement action chosen by the router."""
    from ds_star.state import DSStarState, Description, ExecutionResult

    workdir = get_workdir()
    agents = get_agents(workdir)
    desc_objs = [Description(**d) for d in descriptions]
    er = ExecutionResult(**execution_result)

    state = DSStarState(
        query=query,
        data_dir=data_dir,
        data_files=data_files or [d["filename"] for d in descriptions],
        data_descriptions=desc_objs,
        plans=list(plans),
        base_code=base_code,
        current_code=current_code,
        codes_per_step=list(codes_per_step),
        execution_result=er,
        iteration=iteration,
        guidelines=guidelines,
        retrieved_strategies=strategies or [],
        router_decision=router_decision,
    )

    decision = router_decision
    if isinstance(decision, str) and decision.startswith("step:"):
        try:
            step_idx = int(decision.split(":")[1])
        except Exception:
            step_idx = len(state.plans)
        state = await asyncio.to_thread(agents.refine_fix_step, state, step_idx)
    elif decision == "change_strategy":
        state.plans = state.plans[:1]
        state.codes_per_step = state.codes_per_step[:1]
        state.base_code = state.codes_per_step[0] if state.codes_per_step else ""
        state.current_code = state.base_code
        state = await asyncio.to_thread(agents.refine_add_step, state)
    elif decision == "rerun_analysis":
        state = await asyncio.to_thread(agents.analyze_files, state)
        state = await asyncio.to_thread(agents.refine_add_step, state)
    elif decision == "retrieve_files":
        state.retrieved_indices = None
        state = await asyncio.to_thread(agents.refine_add_step, state)
    else:
        state = await asyncio.to_thread(agents.refine_add_step, state)

    return {
        "plans": state.plans,
        "base_code": state.base_code,
        "current_code": state.current_code,
        "codes_per_step": state.codes_per_step,
        "execution_result": _exec_result_to_dict(state.execution_result),
        "descriptions": _descriptions_to_dicts(state.data_descriptions),
    }


@orchestration_router.reasoner()
async def meta_reflect(
    query: str,
    iteration: int,
    max_iterations: int,
    consecutive_verify_fails: int,
    strategies: Optional[List[str]] = None,
) -> dict:
    """Mid-loop reflection when the agent is stuck."""
    from ds_star.meta_controller import generate_alternative_strategies

    threshold = max(3, max_iterations // 4)
    needs_reflection = consecutive_verify_fails >= 2 or iteration >= threshold

    if not needs_reflection:
        return {"strategies": strategies or [], "reflected": False}

    workdir = get_workdir()
    llm = create_llm()
    state = _build_full_state({
        "query": query,
        "iteration": iteration,
        "max_iterations": max_iterations,
        "strategies": strategies or [],
    })

    try:
        alternatives = await asyncio.to_thread(generate_alternative_strategies, state, llm)
        if alternatives:
            merged = list(set((strategies or []) + alternatives))
            return {"strategies": merged, "reflected": True}
    except Exception as e:
        logger.warning("meta_reflect failed (non-fatal): %s", e)

    return {"strategies": strategies or [], "reflected": False}


@orchestration_router.reasoner()
async def finalize_result(
    query: str,
    descriptions: List[Dict[str, str]],
    current_code: str,
    execution_result: Dict[str, Any],
    guidelines: str = "",
) -> dict:
    """Create the final summary from analysis results."""
    from ds_star.state import DSStarState, Description, ExecutionResult

    workdir = get_workdir()
    agents = get_agents(workdir)
    desc_objs = [Description(**d) for d in descriptions]
    er = ExecutionResult(**execution_result)

    state = DSStarState(
        query=query,
        data_files=[d["filename"] for d in descriptions],
        data_descriptions=desc_objs,
        current_code=current_code,
        execution_result=er,
        guidelines=guidelines,
    )

    state = await asyncio.to_thread(agents.finalize, state)

    answer = state.final_answer or ""

    # The finalize prompt creates final/result.json with structured data.
    # If the answer is just a status message, build markdown from result.json.
    if not answer or len(answer) < 100:
        import json as _json
        for candidate in ["final/result.json", "final/summary.md"]:
            fpath = os.path.join(workdir, candidate)
            if not os.path.isfile(fpath):
                continue
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    raw = f.read().strip()
                if candidate.endswith(".json"):
                    obj = _json.loads(raw)
                    answer = _format_result_json_as_markdown(obj, query)
                elif raw:
                    answer = raw
                break
            except Exception:
                continue

    return {
        "final_answer": answer,
        "final_code": state.final_code,
    }


def _format_result_json_as_markdown(obj: dict, query: str) -> str:
    """Convert the structured result.json into readable markdown."""
    parts: List[str] = []

    summary = obj.get("analysis_summary", "")
    if summary:
        parts.append(f"## Summary\n\n{summary}")

    data = obj.get("data")
    if isinstance(data, dict):
        for key, value in data.items():
            heading = key.replace("_", " ").title()
            if isinstance(value, list) and value and isinstance(value[0], dict):
                cols = list(value[0].keys())
                header = "| " + " | ".join(c.replace("_", " ").title() for c in cols) + " |"
                sep = "| " + " | ".join("---" for _ in cols) + " |"
                rows = []
                for row in value:
                    cells = " | ".join(str(row.get(c, "")) for c in cols)
                    rows.append(f"| {cells} |")
                parts.append(f"### {heading}\n\n{header}\n{sep}\n" + "\n".join(rows))
            elif isinstance(value, (int, float, str)):
                parts.append(f"**{heading}:** {value}")
            elif isinstance(value, dict):
                items = "\n".join(f"- **{k.replace('_', ' ').title()}:** {v}" for k, v in value.items())
                parts.append(f"### {heading}\n\n{items}")
            else:
                parts.append(f"**{heading}:** {value}")

    files = obj.get("files_created", [])
    if files:
        flist = ", ".join(f"`{f}`" for f in files)
        parts.append(f"\n*Generated files: {flist}*")

    return "\n\n".join(parts) if parts else str(obj)


@orchestration_router.reasoner()
async def meta_learn(
    query: str,
    data_files: List[str],
    plans: List[str],
    current_code: str,
    execution_result: Dict[str, Any],
    iteration: int,
    verified: bool,
    failure_type: Optional[str] = None,
    strategies: Optional[List[str]] = None,
    final_answer: Optional[str] = None,
    final_code: Optional[str] = None,
) -> dict:
    """Post-run evaluation, failure classification, and memory storage."""
    from ds_star.memory import HyperMemory
    from ds_star.evaluator import evaluate_run
    from ds_star.meta_controller import analyze_run as meta_analyze_run
    from ds_star.state import DSStarState, ExecutionResult

    workdir = get_workdir()
    llm = create_llm()
    er = ExecutionResult(**execution_result)

    state = DSStarState(
        query=query,
        data_files=data_files,
        plans=plans,
        current_code=current_code,
        execution_result=er,
        iteration=iteration,
        verified=verified,
        failure_type=failure_type,
        retrieved_strategies=strategies or [],
        final_answer=final_answer,
        final_code=final_code,
    )

    score_dict = {"score": 0.5, "quality": "medium", "failure_type": "none"}
    try:
        score_dict = await asyncio.to_thread(evaluate_run, state, llm)
        state.run_score = score_dict
    except Exception as e:
        logger.warning("evaluate_run failed (non-fatal): %s", e)

    memory_path = os.path.join(workdir, "hyper_memory.db")
    try:
        memory = HyperMemory(db_path=memory_path)
        meta = await asyncio.to_thread(meta_analyze_run, state, llm)
        ft = meta.get("failure_type", failure_type or "none")
        strategy_text = meta.get("strategy")
        final_score = score_dict.get("score", 0.5)

        if strategy_text:
            q_emb = await asyncio.to_thread(llm.embed, [query])
            memory.store_strategy(strategy_text, final_score, q_emb[0], ft)

        if final_score < 0.4 and ft != "none":
            reason = meta.get("reason", "")
            if reason:
                memory.store_anti_pattern(ft, reason)

        did_help = bool(strategies) and final_score >= 0.6
        try:
            q_emb_run = await asyncio.to_thread(llm.embed, [query])
            q_emb_run = q_emb_run[0]
        except Exception:
            q_emb_run = None

        run_id = f"run-{int(time.time() * 1000)}"
        memory.store_run(
            run_id=run_id,
            query=query,
            files_used=data_files,
            score=final_score,
            iterations=iteration,
            failure_type=ft,
            strategies_used=strategies or [],
            did_strategy_help=did_help,
            query_embedding=q_emb_run,
        )
    except Exception as e:
        logger.warning("meta_learn storage failed (non-fatal): %s", e)

    return {
        "run_score": score_dict,
        "failure_type": state.failure_type or "none",
    }


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------


@orchestration_router.reasoner()
async def run_pipeline(
    query: str,
    data_files: List[str],
    max_iterations: int = 20,
    guidelines: Optional[str] = None,
    data_dir: str = "data",
) -> dict:
    """Run the full DS_star analysis pipeline.

    Each await call below creates a child node in the AgentField DAG,
    giving full visibility into every step of the pipeline.
    """
    logger.info("Starting DS_star pipeline: query=%r, files=%s, max_iter=%d",
                query, data_files, max_iterations)

    # Step 1: Prepare context (retrieve strategies from memory)
    ctx = await prepare_context(query=query)
    strategies = ctx["strategies"]
    anti_patterns = ctx["anti_patterns"]

    # Step 2: Analyze data files
    analysis = await analyze(query=query, data_files=data_files, data_dir=data_dir)
    descriptions = analysis["descriptions"]

    # Step 3: Initial plan + code implementation
    impl = await plan_and_code(
        query=query,
        descriptions=descriptions,
        guidelines=guidelines or "",
        strategies=strategies,
        anti_patterns=anti_patterns,
    )

    plans = impl["plans"]
    base_code = impl["base_code"]
    current_code = impl["current_code"]
    codes_per_step = impl["codes_per_step"]
    exec_result = impl["execution_result"]

    # Step 4: Verify/refine loop
    iteration = 0
    verified = False
    failure_type = None
    consecutive_fails = 0

    while iteration < max_iterations:
        # Verify
        v = await verify_result(
            query=query,
            plans=plans,
            current_code=current_code,
            execution_result=exec_result,
            iteration=iteration,
            max_iterations=max_iterations,
            consecutive_verify_fails=consecutive_fails,
        )
        verified = v["verified"]
        failure_type = v["failure_type"]
        consecutive_fails = v["consecutive_verify_fails"]

        if verified or iteration >= max_iterations:
            break

        # Route
        r = await route_decision(
            query=query,
            descriptions=descriptions,
            plans=plans,
            execution_result=exec_result,
            strategies=strategies,
            anti_patterns=anti_patterns,
        )

        # Meta-reflect if stuck
        if consecutive_fails >= 2 or iteration >= max(3, max_iterations // 4):
            mr = await meta_reflect(
                query=query,
                iteration=iteration,
                max_iterations=max_iterations,
                consecutive_verify_fails=consecutive_fails,
                strategies=strategies,
            )
            strategies = mr["strategies"]
            if mr["reflected"]:
                consecutive_fails = 0

        # Refine
        ref = await refine(
            query=query,
            descriptions=descriptions,
            plans=plans,
            codes_per_step=codes_per_step,
            base_code=base_code,
            current_code=current_code,
            execution_result=exec_result,
            router_decision=r["decision"],
            iteration=iteration,
            guidelines=guidelines or "",
            strategies=strategies,
            data_files=data_files,
            data_dir=data_dir,
        )

        plans = ref["plans"]
        base_code = ref["base_code"]
        current_code = ref["current_code"]
        codes_per_step = ref["codes_per_step"]
        exec_result = ref["execution_result"]
        descriptions = ref["descriptions"]
        iteration += 1

    # Step 5: Finalize
    final = await finalize_result(
        query=query,
        descriptions=descriptions,
        current_code=current_code,
        execution_result=exec_result,
        guidelines=guidelines or "",
    )

    # Step 6: Meta-learn
    ml = await meta_learn(
        query=query,
        data_files=data_files,
        plans=plans,
        current_code=current_code,
        execution_result=exec_result,
        iteration=iteration,
        verified=verified,
        failure_type=failure_type,
        strategies=strategies,
        final_answer=final["final_answer"],
        final_code=final["final_code"],
    )

    logger.info("Pipeline completed: iterations=%d, verified=%s", iteration, verified)

    score_obj = ml["run_score"]
    run_score = score_obj.get("score", 0.5) if isinstance(score_obj, dict) else score_obj

    return {
        "final_answer": final["final_answer"],
        "final_code": final["final_code"],
        "iterations": iteration,
        "verified": verified,
        "plans": plans,
        "run_score": run_score,
        "failure_type": ml["failure_type"],
    }
