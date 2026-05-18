"""Bridges DSStarState with AgentField's workflow-scoped memory."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ds_star.state import DSStarState, Description


def state_to_response(state: DSStarState) -> dict:
    """Extract the response payload from a completed pipeline state."""
    return {
        "final_answer": state.final_answer,
        "final_code": state.final_code,
        "iterations": state.iteration,
        "verified": state.verified,
        "plans": state.plans,
        "run_score": state.run_score,
        "failure_type": state.failure_type,
    }


def build_state_for_analysis(
    query: str,
    data_files: List[str],
    data_dir: str = "data",
) -> DSStarState:
    """Build a minimal DSStarState for the analyze_files step."""
    return DSStarState(query=query, data_files=data_files, data_dir=data_dir)


def build_state_for_planning(
    query: str,
    descriptions: List[Dict[str, str]],
    guidelines: str = "",
    strategies: Optional[List[str]] = None,
    anti_patterns: Optional[List[Dict]] = None,
) -> DSStarState:
    """Build DSStarState pre-loaded with file descriptions for planning."""
    desc_objects = [Description(**d) for d in descriptions]
    return DSStarState(
        query=query,
        data_files=[d["filename"] for d in descriptions],
        data_descriptions=desc_objects,
        guidelines=guidelines,
        retrieved_strategies=strategies or [],
        anti_patterns=anti_patterns or [],
    )


def build_state_for_coding(
    descriptions: List[Dict[str, str]],
    plans: List[str],
    base_code: str = "",
    strategies: Optional[List[str]] = None,
) -> DSStarState:
    """Build DSStarState for code implementation steps."""
    desc_objects = [Description(**d) for d in descriptions]
    return DSStarState(
        query="",
        data_files=[d["filename"] for d in descriptions],
        data_descriptions=desc_objects,
        plans=plans,
        base_code=base_code,
        retrieved_strategies=strategies or [],
    )


def build_state_for_verification(
    query: str,
    plans: List[str],
    current_code: str,
    execution_result: Dict[str, Any],
) -> DSStarState:
    """Build DSStarState for the verify step."""
    from ds_star.state import ExecutionResult

    exec_result = ExecutionResult(**execution_result)
    return DSStarState(
        query=query,
        data_files=[],
        plans=plans,
        current_code=current_code,
        execution_result=exec_result,
    )


def build_state_for_routing(
    query: str,
    descriptions: List[Dict[str, str]],
    plans: List[str],
    execution_result: Dict[str, Any],
    strategies: Optional[List[str]] = None,
    anti_patterns: Optional[List[Dict]] = None,
) -> DSStarState:
    """Build DSStarState for the router decision step."""
    from ds_star.state import ExecutionResult

    desc_objects = [Description(**d) for d in descriptions]
    exec_result = ExecutionResult(**execution_result)
    return DSStarState(
        query=query,
        data_files=[d["filename"] for d in descriptions],
        data_descriptions=desc_objects,
        plans=plans,
        execution_result=exec_result,
        retrieved_strategies=strategies or [],
        anti_patterns=anti_patterns or [],
    )


def build_state_for_finalization(
    query: str,
    descriptions: List[Dict[str, str]],
    current_code: str,
    execution_result: Dict[str, Any],
    guidelines: str = "",
) -> DSStarState:
    """Build DSStarState for the finalize step."""
    from ds_star.state import ExecutionResult

    desc_objects = [Description(**d) for d in descriptions]
    exec_result = ExecutionResult(**execution_result)
    return DSStarState(
        query=query,
        data_files=[d["filename"] for d in descriptions],
        data_descriptions=desc_objects,
        current_code=current_code,
        execution_result=exec_result,
        guidelines=guidelines,
    )
