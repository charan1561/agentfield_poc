"""Analysis router: wraps DS_star's Analyzer agent as an AgentField reasoner."""

from __future__ import annotations

import asyncio
import os
from typing import List

from agentfield import AgentRouter

from llm_bridge import get_agents, get_workdir
from state_adapter import build_state_for_analysis

analysis_router = AgentRouter(prefix="analysis", tags=["data-analysis"])


@analysis_router.reasoner()
async def analyze_files(
    query: str,
    data_files: List[str],
    data_dir: str = "data",
) -> dict:
    """Analyze data files and return descriptions of their contents.

    Generates Python scripts to inspect each file, executes them,
    and returns textual summaries of each file's structure and content.
    """
    workdir = get_workdir()
    agents = get_agents(workdir)
    state = build_state_for_analysis(query, data_files, data_dir)

    state = await asyncio.to_thread(agents.analyze_files, state)

    return {
        "descriptions": [
            {"filename": d.filename, "summary": d.summary}
            for d in state.data_descriptions
        ]
    }
