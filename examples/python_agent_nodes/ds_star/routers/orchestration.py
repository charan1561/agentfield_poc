"""Orchestration router: wraps the full DS_star pipeline and Finalizer."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from agentfield import AgentRouter

from llm_bridge import get_agents, get_workdir, create_llm
from state_adapter import build_state_for_finalization, state_to_response
from event_bridge import AgentFieldEventBridge

logger = logging.getLogger(__name__)

orchestration_router = AgentRouter(prefix="orchestration", tags=["pipeline"])


@orchestration_router.reasoner()
async def run_pipeline(
    query: str,
    data_files: List[str],
    max_iterations: int = 20,
    guidelines: Optional[str] = None,
    data_dir: str = "data",
) -> dict:
    """Run the full DS_star analysis pipeline.

    This is the top-level entry point that orchestrates all DS_star agents
    via LangGraph. It:
    1. Prepares context (retrieves strategies and anti-patterns from memory)
    2. Analyzes data files
    3. Iteratively plans, codes, verifies, and refines until the query is answered
    4. Finalizes the results into a summary
    5. Performs meta-learning (stores strategies for future runs)

    The entire LangGraph pipeline runs synchronously in a thread pool worker.
    """
    from ds_star.graph import run_ds_star_agent
    from ds_star.memory import HyperMemory

    workdir = get_workdir()
    run_id = str(uuid.uuid4())[:8]
    event_bridge = AgentFieldEventBridge()

    hyper_memory_path = os.path.join(workdir, "hyper_memory.db")
    memory = HyperMemory(db_path=hyper_memory_path)

    logger.info(
        "Starting DS_star pipeline: query=%r, files=%s, max_iter=%d",
        query, data_files, max_iterations,
    )

    try:
        final_state = await asyncio.to_thread(
            run_ds_star_agent,
            query=query,
            data_files=data_files,
            max_iterations=max_iterations,
            guidelines=guidelines,
            workdir=workdir,
            event_bus=event_bridge,
            memory=memory,
        )
    except Exception as e:
        logger.error("DS_star pipeline failed: %s", e, exc_info=True)
        return {
            "final_answer": None,
            "final_code": None,
            "iterations": 0,
            "verified": False,
            "plans": [],
            "run_score": None,
            "failure_type": "pipeline_error",
            "error": str(e),
        }

    captured_events = event_bridge.drain()
    logger.info(
        "Pipeline completed: iterations=%d, verified=%s, events=%d",
        final_state.iteration, final_state.verified, len(captured_events),
    )

    response = state_to_response(final_state)
    response["events_captured"] = len(captured_events)
    return response


@orchestration_router.reasoner()
async def finalize(
    query: str,
    descriptions: List[Dict[str, str]],
    code: str,
    execution_result: Dict[str, Any],
    guidelines: str = "",
) -> dict:
    """Create the final summary from analysis results.

    Generates a summary.md file with the analysis findings. Has a robust
    3-level fallback chain to guarantee output is always produced.
    """
    workdir = get_workdir()
    agents = get_agents(workdir)
    state = build_state_for_finalization(
        query, descriptions, code, execution_result, guidelines
    )

    state = await asyncio.to_thread(agents.finalize, state)

    return {
        "final_answer": state.final_answer,
        "final_code": state.final_code,
    }


