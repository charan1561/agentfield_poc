"""Bridge between AgentField AIConfig and DS_star's AzureLLM."""

from __future__ import annotations

import os
import logging
from typing import Optional

from ds_star.azure_client import AzureLLM
from ds_star.agents import DSStarAgents
from ds_star.events import EventBus

logger = logging.getLogger(__name__)


def create_llm() -> AzureLLM:
    """Create DS_star AzureLLM from environment variables.

    Both AgentField and DS_star share the same Azure env vars:
    - AZURE_OPENAI_ENDPOINT
    - AZURE_OPENAI_API_KEY
    - AZURE_OPENAI_API_VERSION
    - AZURE_OPENAI_DEPLOYMENT
    - AZURE_OPENAI_EMBEDDING_DEPLOYMENT
    """
    required_vars = ["AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT"]
    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        raise RuntimeError(
            f"Missing required Azure OpenAI environment variables: {', '.join(missing)}. "
            f"Set them in .env or as environment variables."
        )
    return AzureLLM()


def get_workdir() -> str:
    """Get the DS_star working directory from env."""
    workdir = os.getenv("DS_STAR_WORKDIR", "/tmp/ds_star")
    os.makedirs(os.path.join(workdir, "data"), exist_ok=True)
    os.makedirs(os.path.join(workdir, "final"), exist_ok=True)
    return workdir


def get_agents(
    workdir: Optional[str] = None,
    event_bus: Optional[EventBus] = None,
    run_id: Optional[str] = None,
) -> DSStarAgents:
    """Factory for DSStarAgents with properly configured LLM."""
    if workdir is None:
        workdir = get_workdir()
    return DSStarAgents(
        llm=create_llm(),
        workdir=workdir,
        event_bus=event_bus,
        run_id=run_id,
    )
