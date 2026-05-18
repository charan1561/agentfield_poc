"""Planning router: wraps DS_star's Planner agent as AgentField reasoners."""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional

from agentfield import AgentRouter

from llm_bridge import get_agents, get_workdir
from state_adapter import build_state_for_planning

planning_router = AgentRouter(prefix="planning", tags=["data-analysis", "planning"])


@planning_router.reasoner()
async def initial_plan(
    query: str,
    descriptions: List[Dict[str, str]],
    guidelines: str = "",
    strategies: Optional[List[str]] = None,
    anti_patterns: Optional[List[Dict]] = None,
) -> dict:
    """Generate the initial analysis plan from query and file descriptions.

    Takes file descriptions (from analyze_files) and produces a step-by-step
    plan for answering the query.
    """
    workdir = get_workdir()
    agents = get_agents(workdir)
    state = build_state_for_planning(
        query, descriptions, guidelines, strategies, anti_patterns
    )

    state = await asyncio.to_thread(agents.initial_plan, state)

    return {"plans": state.plans}


@planning_router.reasoner()
async def next_plan(
    query: str,
    descriptions: List[Dict[str, str]],
    plans: List[str],
    last_execution_stdout: str = "",
    guidelines: str = "",
    strategies: Optional[List[str]] = None,
) -> dict:
    """Generate the next analysis step based on current progress.

    Examines the execution result of previous steps and determines
    what the next step should be.
    """
    workdir = get_workdir()
    agents = get_agents(workdir)
    state = build_state_for_planning(query, descriptions, guidelines, strategies)
    state.plans = plans

    from ds_star.state import ExecutionResult

    state.execution_result = ExecutionResult(
        stdout=last_execution_stdout, stderr="", exit_code=0
    )

    state = await asyncio.to_thread(agents.next_plan, state)

    return {"plans": state.plans}
