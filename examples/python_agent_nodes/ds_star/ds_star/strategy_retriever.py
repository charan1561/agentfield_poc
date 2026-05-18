"""
HyperAgent Strategy Retriever — Pre-run context loading from memory.

Retrieves similar strategies and anti-patterns, formats them for
prompt injection. Returns empty strings when memory is empty (first run).
"""

import logging
from typing import Any, Dict, List, Optional

from .azure_client import AzureLLM
from .memory import HyperMemory

logger = logging.getLogger("ds_star.strategy_retriever")


def retrieve_strategies(
    query: str,
    llm: AzureLLM,
    memory: HyperMemory,
    top_k: int = 5,
    min_score: float = 0.3,
) -> List[Dict[str, Any]]:
    """
    Embed query, find similar strategies in memory, bump usage counts.
    Returns raw strategy dicts (caller decides how to use them).
    """
    try:
        q_emb = llm.embed([query])[0]
        hits = memory.retrieve_similar_strategies(
            q_emb, top_k=top_k, min_score=min_score,
        )
        for h in hits:
            memory.increment_usage(h["id"])
        return hits
    except Exception as exc:
        logger.warning("retrieve_strategies failed (non-fatal): %s", exc)
        return []


def retrieve_anti_patterns(
    memory: HyperMemory,
    failure_type: Optional[str] = None,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """Retrieve top anti-patterns by frequency."""
    try:
        return memory.get_anti_patterns(
            failure_type=failure_type, top_k=top_k,
        )
    except Exception as exc:
        logger.warning("retrieve_anti_patterns failed (non-fatal): %s", exc)
        return []


def retrieve_similar_runs(
    query: str,
    llm: AzureLLM,
    memory: HyperMemory,
    top_k: int = 3,
) -> List[Dict[str, Any]]:
    """Find past runs with similar queries."""
    try:
        q_emb = llm.embed([query])[0]
        return memory.get_similar_runs(q_emb, top_k=top_k)
    except Exception as exc:
        logger.warning("retrieve_similar_runs failed (non-fatal): %s", exc)
        return []


# ------------------------------------------------------------------ #
#  Formatting for prompt injection                                    #
# ------------------------------------------------------------------ #

def format_strategies_for_prompt(strategies: List[str]) -> str:
    """
    Format strategy texts into a prompt-injectable block.
    Returns empty string if list is empty (no-op for first run).
    """
    if not strategies:
        return ""
    lines = [f"{i+1}. {s}" for i, s in enumerate(strategies)]
    return "Learned strategies from similar past tasks:\n" + "\n".join(lines)


def format_anti_patterns_for_prompt(
    anti_patterns: List[Dict[str, Any]],
) -> str:
    """
    Format anti-pattern dicts into a prompt-injectable block.
    Returns empty string if list is empty.
    """
    if not anti_patterns:
        return ""
    lines = [
        f"{i+1}. [{ap['failure_type']}] {ap['pattern_text']}"
        for i, ap in enumerate(anti_patterns)
    ]
    return "Avoid these known mistakes:\n" + "\n".join(lines)


def format_context_block(
    strategies: List[str],
    anti_patterns: List[Dict[str, Any]],
) -> str:
    """
    Combine strategies + anti-patterns into a single context block.
    Returns empty string if both are empty.
    """
    parts: List[str] = []
    s = format_strategies_for_prompt(strategies)
    if s:
        parts.append(s)
    a = format_anti_patterns_for_prompt(anti_patterns)
    if a:
        parts.append(a)
    return "\n\n".join(parts)
