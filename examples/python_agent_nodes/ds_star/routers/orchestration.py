"""Orchestration router: parallel multi-strategy AgentField orchestration (v3).

Architecture: ~15 DAG nodes, ~400+ internal AI calls per run.
Each reasoner is 1 DAG node with massive internal parallelism via asyncio.gather.
Modeled after af-deep-research's pattern.
"""

from __future__ import annotations

import asyncio
import base64
import json as _json
import logging
import os
import shutil
import time
from typing import Any, Dict, List, Optional

from agentfield import AgentRouter

from ds_star.concurrency import run_in_batches, AI_CALL_CONCURRENCY_LIMIT
from llm_bridge import get_agents, get_workdir, create_llm
from state_adapter import state_to_response

logger = logging.getLogger(__name__)

orchestration_router = AgentRouter(prefix="orchestration", tags=["pipeline"])

VERIFIER_PERSPECTIVES = ["statistical", "logical", "query_alignment"]
ANALYSIS_PERSPECTIVES = ["statistical_profile", "relationships_correlations", "data_quality"]
REPORT_SECTIONS = [
    "executive_summary", "key_findings", "statistical_analysis",
    "data_quality", "methodology", "visualizations",
    "recommendations", "appendix",
]


def app_note(message: str):
    agent = orchestration_router._agent
    if agent and hasattr(agent, "note"):
        agent.note(message)
    logger.info("[DS-STAR] %s", message)


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


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


def _select_best_variant(variants: List[Dict]) -> Dict:
    successful = [v for v in variants if v.get("exit_code") == 0]
    if successful:
        return max(successful, key=lambda v: len(v.get("stdout", "")))
    return max(variants, key=lambda v: len(v.get("stdout", ""))) if variants else {}


def _merge_file_perspectives(results: List[Dict], data_files: List[str]) -> List[Dict[str, str]]:
    merged: Dict[str, List[str]] = {}
    for r in results:
        fn = r.get("filename", "")
        if fn not in merged:
            merged[fn] = []
        merged[fn].append(f"[{r.get('perspective', 'unknown')}]\n{r.get('summary', '')}")
    return [
        {"filename": fn, "summary": "\n\n".join(parts)}
        for fn, parts in merged.items()
    ]


# ---------------------------------------------------------------------------
# Sub-reasoners (kept from v2 — used internally by v3 reasoners)
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
        query=query, data_files=data_files, plans=plans,
        current_code=current_code, execution_result=er,
        iteration=iteration, verified=verified, failure_type=failure_type,
        retrieved_strategies=strategies or [],
        final_answer=final_answer, final_code=final_code,
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
            run_id=run_id, query=query, files_used=data_files,
            score=final_score, iterations=iteration, failure_type=ft,
            strategies_used=strategies or [], did_strategy_help=did_help,
            query_embedding=q_emb_run,
        )
    except Exception as e:
        logger.warning("meta_learn storage failed (non-fatal): %s", e)

    return {
        "run_score": score_dict,
        "failure_type": state.failure_type or "none",
    }


# ---------------------------------------------------------------------------
# v3 parallel reasoners — each is 1 DAG node with internal parallelism
# ---------------------------------------------------------------------------


@orchestration_router.reasoner()
async def analyze_parallel(
    query: str,
    data_files: List[str],
    data_dir: str = "data",
) -> dict:
    """Analyze all files from 3 perspectives in parallel (~45 internal AI calls)."""
    app_note(f"Analyzing {len(data_files)} files x {len(ANALYSIS_PERSPECTIVES)} perspectives")

    workdir = get_workdir()

    async def _analyze_one(filename: str, perspective: str) -> Dict:
        agents = get_agents(workdir)
        return await asyncio.to_thread(
            agents.analyze_single_file, filename, perspective, query, data_dir,
        )

    tasks = [
        _analyze_one(fn, p)
        for fn in data_files
        for p in ANALYSIS_PERSPECTIVES
    ]
    results = await run_in_batches(tasks)

    descriptions = _merge_file_perspectives(results, data_files)
    app_note(f"Completed {len(tasks)} analysis calls across {len(data_files)} files")
    return {"descriptions": descriptions}


@orchestration_router.reasoner()
async def generate_strategies(
    query: str,
    descriptions: List[Dict[str, str]],
    guidelines: str = "",
    strategies: Optional[List[str]] = None,
    anti_patterns: Optional[List[Dict]] = None,
    num_strategies: int = 5,
) -> dict:
    """Generate N distinct analysis strategies (1 AI call)."""
    from ds_star.prompts import render_strategy_generation_prompt
    from ds_star.strategy_retriever import format_context_block
    from ds_star.utils import extract_first_code_block

    llm = create_llm()
    filenames = [d["filename"] for d in descriptions]
    summaries = [d["summary"] for d in descriptions]
    past = format_context_block(strategies or [], anti_patterns or [])

    msgs = render_strategy_generation_prompt(
        query, summaries, filenames, guidelines or "Provide helpful analysis",
        past_strategies=past, num_strategies=num_strategies,
    )
    resp = await asyncio.to_thread(llm.chat_complete, messages=msgs, temperature=0.7)

    # Strip markdown code fences if present
    clean = extract_first_code_block(resp) if "```" in resp else resp.strip()

    try:
        parsed = _json.loads(clean)
        if isinstance(parsed, list):
            strats = [s for s in parsed if isinstance(s, str)][:num_strategies]
        else:
            strats = [resp.strip()]
    except Exception:
        strats = [resp.strip()]

    while len(strats) < num_strategies:
        strats.append(f"Variation {len(strats)+1}: " + (strats[0] if strats else "Standard analysis approach"))

    app_note(f"Generated {len(strats)} analysis strategies")
    return {"strategies": strats}


@orchestration_router.reasoner()
async def explore_strategy(
    strategy_id: str,
    strategy_desc: str,
    query: str,
    descriptions: List[Dict[str, str]],
    guidelines: str = "",
    strategies: Optional[List[str]] = None,
    anti_patterns: Optional[List[Dict]] = None,
    max_iterations: int = 5,
    num_code_variants: int = 3,
    num_verifiers: int = 3,
    data_files: Optional[List[str]] = None,
    data_dir: str = "data",
) -> dict:
    """Explore one analysis strategy branch (~50 internal AI calls).

    Runs plan -> parallel code variants -> ensemble verify -> route -> refine loop.
    """
    from ds_star.state import DSStarState, Description
    from ds_star.strategy_retriever import format_context_block

    app_note(f"Strategy {strategy_id}: {strategy_desc[:80]}...")

    workdir = get_workdir()
    branch_dir = os.path.join(workdir, "branches", strategy_id)
    os.makedirs(os.path.join(branch_dir, "data"), exist_ok=True)
    os.makedirs(os.path.join(branch_dir, "final"), exist_ok=True)

    # Symlink or copy data files into branch workdir
    src_data = os.path.join(workdir, "data")
    dst_data = os.path.join(branch_dir, "data")
    if os.path.isdir(src_data):
        for fname in os.listdir(src_data):
            src = os.path.join(src_data, fname)
            dst = os.path.join(dst_data, fname)
            if os.path.isfile(src) and not os.path.exists(dst):
                shutil.copy2(src, dst)

    filenames = [d["filename"] for d in descriptions]
    summaries = [d["summary"] for d in descriptions]
    ctx_block = format_context_block(strategies or [], anti_patterns or [])
    augmented_guidelines = f"{guidelines}\nStrategy: {strategy_desc}"

    ai_call_count = 0

    # Initial plan
    agents_inst = get_agents(branch_dir)
    desc_objs = [Description(**d) for d in descriptions]
    state = DSStarState(
        query=query, data_files=data_files or filenames,
        data_descriptions=desc_objs, guidelines=augmented_guidelines,
        retrieved_strategies=strategies or [], anti_patterns=anti_patterns or [],
    )
    state = await asyncio.to_thread(agents_inst.initial_plan, state)
    ai_call_count += 1

    # Parallel code variants for initial step
    async def _gen_variant(vid: str, plan: str, base: str = "") -> Dict:
        a = get_agents(branch_dir)
        return await asyncio.to_thread(
            a.generate_code_variant, vid, plan, summaries, filenames, base, ctx_block,
        )

    raw_variants = await asyncio.gather(*[
        _gen_variant(f"v{j}", state.plans[0]) for j in range(num_code_variants)
    ], return_exceptions=True)
    variants = [v for v in raw_variants if isinstance(v, dict)]
    ai_call_count += num_code_variants
    best = _select_best_variant(variants)

    plans = list(state.plans)
    base_code = best.get("code", "")
    current_code = base_code
    codes_per_step = [base_code]
    exec_result = {
        "stdout": best.get("stdout", ""),
        "stderr": best.get("stderr", ""),
        "exit_code": best.get("exit_code", -1),
        "artifacts": best.get("artifacts", {}),
    }

    iteration = 0
    verified = False

    while iteration < max_iterations:
        app_note(f"  {strategy_id} iter {iteration}: ensemble verify ({num_verifiers} perspectives)")

        # Ensemble verification
        async def _verify(perspective: str) -> Dict:
            a = get_agents(branch_dir)
            result_text = exec_result.get("stdout", "")
            return await asyncio.to_thread(
                a.verify_from_perspective, perspective, query, current_code, result_text, plans,
            )

        raw_verdicts = await asyncio.gather(*[_verify(p) for p in VERIFIER_PERSPECTIVES[:num_verifiers]], return_exceptions=True)
        verdicts = [v for v in raw_verdicts if isinstance(v, dict)]
        ai_call_count += num_verifiers
        verified = len(verdicts) > 0 and sum(1 for v in verdicts if v.get("verified")) >= 2
        if verified:
            app_note(f"  {strategy_id}: verified at iteration {iteration}")
            break

        # Route decision
        from ds_star.state import ExecutionResult
        agents_route = get_agents(branch_dir)
        route_state = DSStarState(
            query=query, data_files=data_files or filenames,
            data_descriptions=desc_objs, plans=plans,
            execution_result=ExecutionResult(**exec_result),
            retrieved_strategies=strategies or [], anti_patterns=anti_patterns or [],
        )
        route_state = await asyncio.to_thread(agents_route.route, route_state)
        ai_call_count += 1
        decision = route_state.router_decision or "add"

        # Next plan
        last_result = exec_result.get("stdout", "")
        from ds_star.utils import truncate_text
        plan_agents = get_agents(branch_dir)
        plan_state = DSStarState(
            query=query, data_files=data_files or filenames,
            data_descriptions=desc_objs, plans=plans,
            guidelines=augmented_guidelines, retrieved_strategies=strategies or [],
        )
        plan_state = await asyncio.to_thread(plan_agents.next_plan, plan_state, truncate_text(last_result, 2000))
        ai_call_count += 1
        plans = list(plan_state.plans)

        # Parallel code variants for this step
        current_step = plans[-1] if plans else ""
        raw_variants = await asyncio.gather(*[
            _gen_variant(f"v{j}", current_step, current_code) for j in range(num_code_variants)
        ], return_exceptions=True)
        variants = [v for v in raw_variants if isinstance(v, dict)]
        ai_call_count += num_code_variants

        # If all fail, parallel debug
        successful = [v for v in variants if v.get("exit_code") == 0]
        if not successful and variants:
            async def _debug(attempt_id: str, failed: Dict) -> Dict:
                a = get_agents(branch_dir)
                from ds_star.prompts import render_debug_fix_solution_prompt, render_debug_summarize_prompt
                from ds_star.utils import extract_first_code_block
                tb = truncate_text(failed.get("stderr", ""), 4000)
                sum_msgs = render_debug_summarize_prompt(tb, "solution")
                summary = await asyncio.to_thread(a._chat, sum_msgs)
                fix_msgs = render_debug_fix_solution_prompt(summaries, filenames, failed.get("code", ""), truncate_text(summary, 3500))
                fixed_resp = await asyncio.to_thread(a._chat, fix_msgs)
                fixed_code = extract_first_code_block(fixed_resp)
                from ds_star.executor import run_python_code
                result = run_python_code(fixed_code, workdir=branch_dir)
                return {
                    "variant_id": attempt_id, "code": fixed_code,
                    "stdout": result.stdout, "stderr": result.stderr,
                    "exit_code": result.exit_code, "artifacts": result.artifacts,
                }

            raw_debugged = await asyncio.gather(*[
                _debug(f"d{j}", variants[0]) for j in range(3)
            ], return_exceptions=True)
            debugged = [d for d in raw_debugged if isinstance(d, dict)]
            ai_call_count += 3
            successful = [d for d in debugged if d.get("exit_code") == 0]

        best = _select_best_variant(successful or variants)
        current_code = best.get("code", current_code)
        base_code = current_code
        codes_per_step.append(current_code)
        exec_result = {
            "stdout": best.get("stdout", ""),
            "stderr": best.get("stderr", ""),
            "exit_code": best.get("exit_code", -1),
            "artifacts": best.get("artifacts", {}),
        }
        iteration += 1

    return {
        "strategy_id": strategy_id,
        "strategy_description": strategy_desc,
        "plans": plans,
        "base_code": base_code,
        "current_code": current_code,
        "codes_per_step": codes_per_step,
        "execution_result": exec_result,
        "verified": verified,
        "iteration": iteration,
        "ai_call_count": ai_call_count,
    }


@orchestration_router.reasoner()
async def select_best_strategy(
    query: str,
    branches: List[Dict[str, Any]],
    descriptions: List[Dict[str, str]],
) -> dict:
    """Evaluate all strategy branches and pick the winner (~6 internal AI calls)."""
    app_note(f"Selecting best from {len(branches)} strategies")

    if not branches:
        app_note("No strategy branches to evaluate")
        return {"strategy_id": "none", "plans": [], "current_code": "", "execution_result": {}, "verified": False}

    workdir = get_workdir()

    # Parallel verification of each branch's final result
    async def _verify_branch(branch: Dict) -> Dict:
        agents_inst = get_agents(workdir)
        result_text = branch.get("execution_result", {}).get("stdout", "")
        code = branch.get("current_code", "")
        plans = branch.get("plans", [])
        verdict = await asyncio.to_thread(
            agents_inst.verify_from_perspective, "query_alignment", query, code, result_text, plans,
        )
        return {
            "strategy_id": branch.get("strategy_id"),
            "verified": verdict.get("verified", False),
            "confidence": verdict.get("confidence", 0.0),
            "output_length": len(result_text),
        }

    raw_scores = await asyncio.gather(*[_verify_branch(b) for b in branches], return_exceptions=True)
    scores = []
    for i, s in enumerate(raw_scores):
        if isinstance(s, dict):
            scores.append((i, s))
        else:
            scores.append((i, {"verified": False, "confidence": 0.0, "output_length": 0}))

    # Pick best: prefer verified, then highest confidence, then longest output
    best_idx = 0
    best_score = (-1, -1.0, -1)
    for i, s in scores:
        score_tuple = (
            int(s.get("verified", False)),
            s.get("confidence", 0.0),
            s.get("output_length", 0),
        )
        if score_tuple > best_score:
            best_score = score_tuple
            best_idx = i

    winner = branches[best_idx]
    winner_score = dict(scores)[best_idx]
    app_note(f"Selected strategy: {winner.get('strategy_id', 'unknown')} (verified={winner_score.get('verified')})")
    return winner


@orchestration_router.reasoner()
async def cross_strategy_synthesis(
    branches: List[Dict[str, Any]],
    query: str,
) -> dict:
    """Extract insights from ALL branches and merge (~6 internal AI calls)."""
    app_note(f"Extracting insights from {len(branches)} strategy branches")

    llm = create_llm()

    async def _extract_insights(branch: Dict) -> str:
        stdout = branch.get("execution_result", {}).get("stdout", "")
        plans = branch.get("plans", [])
        sid = branch.get("strategy_id", "")
        prompt = (
            f"Extract the 3-5 most important data insights from this analysis branch.\n\n"
            f"Strategy: {branch.get('strategy_description', '')}\n"
            f"Plans: {'; '.join(plans)}\n"
            f"Output:\n{stdout[:2000]}\n\n"
            f"Return a brief bullet list of unique insights."
        )
        return await asyncio.to_thread(
            llm.chat_complete, messages=[{"role": "user", "content": prompt}], temperature=0.3,
        )

    raw_insights = await asyncio.gather(*[_extract_insights(b) for b in branches], return_exceptions=True)
    insights = [ins if isinstance(ins, str) else "(extraction failed)" for ins in raw_insights]

    # Merge
    all_insights = "\n\n".join([
        f"### {b.get('strategy_id', f'Branch {i}')}\n{ins}"
        for i, (b, ins) in enumerate(zip(branches, insights))
    ])
    merge_prompt = (
        f"Merge these insights from {len(branches)} analysis strategies into a unified set of key findings.\n"
        f"Remove duplicates. Prioritize findings that appear across multiple strategies.\n\n"
        f"Question: {query}\n\n{all_insights}\n\n"
        f"Return a consolidated bullet list of unique insights."
    )
    merged = await asyncio.to_thread(
        llm.chat_complete, messages=[{"role": "user", "content": merge_prompt}], temperature=0.3,
    )

    return {"merged_insights": merged, "per_branch_insights": list(insights)}


@orchestration_router.reasoner()
async def generate_visualizations(
    query: str,
    descriptions: List[Dict[str, str]],
    execution_result: Dict[str, Any],
    data_files: Optional[List[str]] = None,
    data_dir: str = "data",
) -> dict:
    """Plan and generate charts in parallel (~24 internal AI calls)."""
    from ds_star.prompts import render_visualization_planner_prompt, render_chart_quality_prompt

    app_note("Planning visualizations")

    workdir = get_workdir()
    llm = create_llm()
    filenames = [d["filename"] for d in descriptions]
    summaries = [d["summary"] for d in descriptions]
    stdout = execution_result.get("stdout", "")

    # Plan charts (1 AI call)
    msgs = render_visualization_planner_prompt(query, summaries, filenames, stdout)
    resp = await asyncio.to_thread(llm.chat_complete, messages=msgs, temperature=0.5)

    try:
        specs = _json.loads(resp.strip())
        if not isinstance(specs, list):
            specs = []
    except Exception:
        specs = []

    if not specs:
        app_note("No visualization specs generated, skipping charts")
        return {"charts": [], "specs": []}

    os.makedirs(os.path.join(workdir, "final", "charts"), exist_ok=True)
    app_note(f"Generating {len(specs)} charts in parallel")

    # Generate charts in parallel — embed spec in result to avoid alignment issues
    async def _gen_chart(spec: Dict) -> Dict:
        agents_inst = get_agents(workdir)
        result = await asyncio.to_thread(agents_inst.generate_chart_code, spec, summaries, filenames)
        result["_spec"] = spec
        return result

    chart_tasks = [_gen_chart(s) for s in specs]
    charts = await run_in_batches(chart_tasks)

    # Quality check in parallel — use embedded spec, not positional zip
    async def _check_quality(chart: Dict) -> Dict:
        spec = chart.get("_spec", {})
        if not chart.get("success"):
            return {"good": False, "chart": chart, "spec": spec}
        msgs = render_chart_quality_prompt(spec, chart.get("code", ""), "", chart.get("error", ""))
        resp = await asyncio.to_thread(llm.chat_complete, messages=msgs, temperature=0.3)
        try:
            parsed = _json.loads(resp.strip())
        except Exception:
            parsed = {"good": True}
        return {"good": parsed.get("good", True), "chart": chart, "spec": spec}

    check_tasks = [_check_quality(c) for c in charts if c.get("success")]
    checked = await run_in_batches(check_tasks)

    # Redo poor quality charts
    poor = [c for c in checked if not c.get("good")]
    if poor:
        app_note(f"Regenerating {len(poor)} poor quality charts")
        redo_tasks = [_gen_chart(c["spec"]) for c in poor]
        redone = await run_in_batches(redo_tasks)
        for redo in redone:
            if redo.get("success"):
                # Replace in charts list
                for i, c in enumerate(charts):
                    if c.get("filename") == redo.get("filename"):
                        charts[i] = redo
                        break

    successful = [c for c in charts if c.get("success")]
    app_note(f"Generated {len(successful)}/{len(specs)} charts successfully")
    return {"charts": charts, "specs": specs}


@orchestration_router.reasoner()
async def generate_report(
    query: str,
    best: Dict[str, Any],
    charts: List[Dict[str, Any]],
    merged_insights: str,
    descriptions: List[Dict[str, str]],
    guidelines: str = "",
) -> dict:
    """Generate final report with parallel section writing (~17 internal AI calls)."""
    from ds_star.prompts import render_report_section_prompt

    app_note("Generating report with parallel section writing")

    llm = create_llm()
    workdir = get_workdir()
    stdout = best.get("execution_result", {}).get("stdout", "")
    chart_filenames = [c.get("filename", "") for c in charts if c.get("success")]

    # Write sections in parallel
    async def _write_section(section_name: str) -> Dict:
        msgs = render_report_section_prompt(
            query, section_name, merged_insights, chart_filenames, stdout,
        )
        content = await asyncio.to_thread(
            llm.chat_complete, messages=msgs, temperature=0.4,
        )
        return {"section": section_name, "content": content}

    raw_drafts = await asyncio.gather(*[_write_section(s) for s in REPORT_SECTIONS], return_exceptions=True)
    drafts = [d for d in raw_drafts if isinstance(d, dict)]
    if not drafts:
        return {"final_answer": f"# Analysis Report\n\n**Query:** {query}\n\nReport generation failed."}

    # Skip edit pass — drafts are already concise from the prompt constraints

    # Assemble final report
    report_parts = []
    report_parts.append(f"# Analysis Report\n\n**Query:** {query}\n")
    for section in drafts:
        name = section["section"].replace("_", " ").title()
        report_parts.append(f"## {name}\n\n{section['content']}")

    if chart_filenames:
        report_parts.append("\n---\n*Charts are available in the `charts/` directory.*")

    final_answer = "\n\n".join(report_parts)

    # Save report to file
    report_path = os.path.join(workdir, "final", "report.md")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8", errors="replace") as f:
        f.write(final_answer)

    app_note("Report generated successfully")
    return {"final_answer": final_answer}


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
    num_strategies: int = 5,
    strategy_max_iters: int = 5,
    num_code_variants: int = 3,
    num_verifiers: int = 3,
) -> dict:
    """Run the parallel DS-star v3 pipeline.

    ~15 DAG nodes, ~400+ internal AI calls.
    Each await below creates a child DAG node.
    Internal parallelism happens via asyncio.gather inside each reasoner.
    """
    t0 = time.time()
    app_note(f"Starting pipeline: {len(data_files)} files, {num_strategies} strategies, {num_code_variants} variants")

    # Step 1: 2 DAG nodes (parallel) — context + multi-perspective file analysis
    ctx_task = prepare_context(query=query)
    analysis_task = analyze_parallel(query=query, data_files=data_files, data_dir=data_dir)
    ctx, analysis = await asyncio.gather(ctx_task, analysis_task)

    strategies = ctx["strategies"]
    anti_patterns = ctx["anti_patterns"]
    descriptions = analysis["descriptions"]

    # Step 2: 1 DAG node — generate strategies
    strat_result = await generate_strategies(
        query=query, descriptions=descriptions,
        guidelines=guidelines or "", strategies=strategies,
        anti_patterns=anti_patterns, num_strategies=num_strategies,
    )
    strategy_list = strat_result["strategies"]

    # Step 3: N DAG nodes (parallel) — explore each strategy
    app_note(f"Exploring {len(strategy_list)} strategies in parallel")
    branch_tasks = [
        explore_strategy(
            strategy_id=f"s{i}", strategy_desc=s, query=query,
            descriptions=descriptions, guidelines=guidelines or "",
            strategies=strategies, anti_patterns=anti_patterns,
            max_iterations=strategy_max_iters,
            num_code_variants=num_code_variants,
            num_verifiers=num_verifiers,
            data_files=data_files, data_dir=data_dir,
        )
        for i, s in enumerate(strategy_list)
    ]
    branches = await run_in_batches(branch_tasks, batch_size=num_strategies)

    # Step 4: 1 DAG node — select best strategy
    best = await select_best_strategy(
        query=query, branches=branches, descriptions=descriptions,
    )

    # Step 5: 1 DAG node — cross-strategy synthesis
    synthesis = await cross_strategy_synthesis(branches=branches, query=query)
    merged_insights = synthesis["merged_insights"]

    # Step 6: 1 DAG node — generate visualizations
    viz = await generate_visualizations(
        query=query, descriptions=descriptions,
        execution_result=best.get("execution_result", {}),
        data_files=data_files, data_dir=data_dir,
    )
    charts = viz.get("charts", [])

    # Copy winning branch outputs to main final/
    workdir = get_workdir()
    winning_branch = os.path.join(workdir, "branches", best.get("strategy_id", "s0"), "final")
    main_final = os.path.join(workdir, "final")
    if os.path.isdir(winning_branch):
        for item in os.listdir(winning_branch):
            src = os.path.join(winning_branch, item)
            dst = os.path.join(main_final, item)
            if os.path.isfile(src) and not os.path.exists(dst):
                shutil.copy2(src, dst)

    # Step 7: 1 DAG node — generate report
    report = await generate_report(
        query=query, best=best, charts=charts,
        merged_insights=merged_insights, descriptions=descriptions,
        guidelines=guidelines or "",
    )

    # Step 8: 1 DAG node — meta-learn
    ml = await meta_learn(
        query=query, data_files=data_files,
        plans=best.get("plans", []),
        current_code=best.get("current_code", ""),
        execution_result=best.get("execution_result", {}),
        iteration=sum(b.get("iteration", 0) for b in branches),
        verified=best.get("verified", False),
        failure_type=None,
        strategies=strategies,
        final_answer=report["final_answer"],
        final_code=best.get("current_code"),
    )

    elapsed = time.time() - t0
    total_ai_calls = sum(b.get("ai_call_count", 0) for b in branches)
    app_note(f"Pipeline completed in {elapsed:.0f}s: {len(branches)} strategies, ~{total_ai_calls}+ AI calls")

    score_obj = ml["run_score"]
    run_score = score_obj.get("score", 0.5) if isinstance(score_obj, dict) else score_obj

    chart_data = []
    charts_dir = os.path.join(workdir, "final", "charts")
    for c in charts:
        if not c.get("success"):
            continue
        fname = c.get("filename", "")
        fpath = os.path.join(charts_dir, fname)
        if os.path.isfile(fpath):
            with open(fpath, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            ext = os.path.splitext(fname)[1].lstrip(".") or "png"
            chart_data.append({"name": fname, "data": f"data:image/{ext};base64,{b64}"})

    return {
        "final_answer": report["final_answer"],
        "final_code": best.get("current_code", ""),
        "charts": chart_data,
        "strategies_explored": len(branches),
        "total_ai_calls": total_ai_calls,
        "iterations": sum(b.get("iteration", 0) for b in branches),
        "verified": best.get("verified", False),
        "plans": best.get("plans", []),
        "run_score": run_score,
        "failure_type": ml["failure_type"],
        "elapsed_seconds": round(elapsed, 1),
    }
