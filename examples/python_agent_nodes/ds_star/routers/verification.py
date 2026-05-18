"""Verification router: wraps DS_star's Verifier and Router agents."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from agentfield import AgentRouter

from llm_bridge import get_agents, get_workdir
from state_adapter import build_state_for_verification, build_state_for_routing

verification_router = AgentRouter(prefix="verification", tags=["data-analysis", "verification"])


@verification_router.reasoner()
async def verify(
    query: str,
    plans: List[str],
    code: str,
    execution_result: Dict[str, Any],
) -> dict:
    """Verify whether the current code and execution result answers the query.

    Uses LLM-as-judge to determine if the analysis is complete.
    Returns verified=True if the query is answered, along with failure
    type classification if not.
    """
    workdir = get_workdir()
    agents = get_agents(workdir)
    state = build_state_for_verification(query, plans, code, execution_result)

    state = await asyncio.to_thread(agents.verify, state)

    return {
        "verified": state.verified,
        "failure_type": state.failure_type,
        "consecutive_fails": state.consecutive_verify_fails,
    }


@verification_router.reasoner()
async def route_decision(
    query: str,
    descriptions: List[Dict[str, str]],
    plans: List[str],
    execution_result: Dict[str, Any],
    strategies: Optional[List[str]] = None,
    anti_patterns: Optional[List[Dict]] = None,
) -> dict:
    """Decide the refinement action when verification fails.

    Returns one of:
    - "add": add a new step
    - "step:<i>": backtrack to step i and regenerate
    - "change_strategy": reset and try a different approach
    - "rerun_analysis": re-analyze files
    - "retrieve_files": use all files (clear filter)
    """
    workdir = get_workdir()
    agents = get_agents(workdir)
    state = build_state_for_routing(
        query, descriptions, plans, execution_result, strategies, anti_patterns
    )

    state = await asyncio.to_thread(agents.route, state)

    return {"decision": state.router_decision}
