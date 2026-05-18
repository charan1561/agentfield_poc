"""Meta router: wraps DS_star's Meta-Controller for cross-run learning."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from agentfield import AgentRouter

from llm_bridge import create_llm, get_workdir

logger = logging.getLogger(__name__)

meta_router = AgentRouter(prefix="meta", tags=["meta-learning"])


def _get_memory():
    """Get or create the HyperMemory instance."""
    from ds_star.memory import HyperMemory

    workdir = get_workdir()
    return HyperMemory(db_path=os.path.join(workdir, "hyper_memory.db"))


@meta_router.reasoner()
async def meta_learn(state_dict: Dict[str, Any]) -> dict:
    """Post-run analysis: classify failure, generate strategy, store learnings.

    Takes the full pipeline state as a dict, analyzes the run, and stores
    reusable strategies and anti-patterns in HyperMemory for future runs.
    """
    from ds_star.state import DSStarState
    from ds_star.meta_controller import analyze_run

    state = DSStarState(**state_dict)
    llm = create_llm()
    memory = _get_memory()

    result = await asyncio.to_thread(analyze_run, state, llm, memory)

    return {
        "strategy_stored": result.get("strategy_stored", False),
        "failure_classified": result.get("failure_classified", False),
        "failure_type": result.get("failure_type"),
        "score": result.get("score"),
    }


@meta_router.skill()
def get_strategies(query: str, top_k: int = 5) -> dict:
    """Retrieve learned strategies from HyperMemory by similarity.

    Deterministic lookup: embeds the query and finds the most similar
    strategies from past successful runs.
    """
    from ds_star.retriever import get_embedding

    memory = _get_memory()
    llm = create_llm()

    try:
        query_embedding = get_embedding(llm, query)
        strategies = memory.retrieve_similar_strategies(
            query_embedding=query_embedding, top_k=top_k
        )
        return {
            "strategies": [
                {
                    "id": s.get("id"),
                    "text": s.get("strategy_text", ""),
                    "score": s.get("success_score", 0),
                    "usage_count": s.get("usage_count", 0),
                }
                for s in strategies
            ]
        }
    except Exception as e:
        logger.warning("Failed to retrieve strategies: %s", e)
        return {"strategies": []}


@meta_router.skill()
def get_anti_patterns(failure_type: Optional[str] = None, top_k: int = 5) -> dict:
    """Retrieve anti-patterns from HyperMemory.

    Returns known failure patterns and their frequencies, optionally
    filtered by failure type.
    """
    memory = _get_memory()

    try:
        patterns = memory.get_anti_patterns(failure_type=failure_type, top_k=top_k)
        return {
            "anti_patterns": [
                {
                    "failure_type": p.get("failure_type", ""),
                    "pattern": p.get("pattern_text", ""),
                    "frequency": p.get("frequency", 0),
                }
                for p in patterns
            ]
        }
    except Exception as e:
        logger.warning("Failed to retrieve anti-patterns: %s", e)
        return {"anti_patterns": []}
