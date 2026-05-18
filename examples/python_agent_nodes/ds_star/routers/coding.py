"""Coding router: wraps DS_star's Coder agent as AgentField reasoners."""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional

from agentfield import AgentRouter

from llm_bridge import get_agents, get_workdir
from state_adapter import build_state_for_coding

coding_router = AgentRouter(prefix="coding", tags=["data-analysis", "code-generation"])


@coding_router.reasoner()
async def implement_initial(
    descriptions: List[Dict[str, str]],
    plan_step: str,
    strategies: Optional[List[str]] = None,
) -> dict:
    """Generate initial Python code implementing the first plan step.

    Takes file descriptions and the first plan step, produces executable
    Python code that reads from data/ and writes to final/.
    """
    workdir = get_workdir()
    agents = get_agents(workdir)
    state = build_state_for_coding(descriptions, [plan_step], "", strategies)

    state = await asyncio.to_thread(agents.implement_initial, state)

    result = {
        "code": state.current_code,
        "stdout": state.execution_result.stdout if state.execution_result else "",
        "stderr": state.execution_result.stderr if state.execution_result else "",
        "exit_code": state.execution_result.exit_code if state.execution_result else -1,
        "artifacts": state.execution_result.artifacts if state.execution_result else {},
    }
    return result


@coding_router.reasoner()
async def implement_next(
    descriptions: List[Dict[str, str]],
    base_code: str,
    previous_plans: List[str],
    current_step: str,
    guidelines: str = "",
    strategies: Optional[List[str]] = None,
) -> dict:
    """Generate code for the next plan step, building on previous code.

    Receives the base code from previous steps and the current plan step,
    produces updated code that implements the new step incrementally.
    """
    workdir = get_workdir()
    agents = get_agents(workdir)
    all_plans = previous_plans + [current_step]
    state = build_state_for_coding(descriptions, all_plans, base_code, strategies)
    state.guidelines = guidelines

    state = await asyncio.to_thread(agents.implement_next, state)

    result = {
        "code": state.current_code,
        "stdout": state.execution_result.stdout if state.execution_result else "",
        "stderr": state.execution_result.stderr if state.execution_result else "",
        "exit_code": state.execution_result.exit_code if state.execution_result else -1,
        "artifacts": state.execution_result.artifacts if state.execution_result else {},
    }
    return result
