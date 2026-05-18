"""
DS-STAR: Data Science Agent via Iterative Planning and Verification

This package provides a LangGraph-based implementation of the DS-STAR system.
Key exports:
- run_ds_star_agent: High-level function to execute the full pipeline
- build_graph: Constructs the LangGraph state machine for the workflow
"""

from .graph import run_ds_star_agent, build_graph
from .memory import HyperMemory
from .evaluator import evaluate_run
from .meta_controller import analyze_run, classify_failure, generate_strategy
from .strategy_retriever import retrieve_strategies, format_context_block

__all__ = [
    "run_ds_star_agent",
    "build_graph",
    "HyperMemory",
    "evaluate_run",
    "analyze_run",
    "classify_failure",
    "generate_strategy",
    "retrieve_strategies",
    "format_context_block",
]
