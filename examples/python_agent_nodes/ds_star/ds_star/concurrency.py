"""Controlled concurrency utilities adapted from af-deep-research's run_in_batches pattern."""

from __future__ import annotations

import asyncio
import os
from typing import Any, List

AI_CALL_CONCURRENCY_LIMIT = int(os.getenv("DS_STAR_CONCURRENCY_LIMIT", "8"))


async def run_in_batches(
    tasks: List[Any],
    batch_size: int = AI_CALL_CONCURRENCY_LIMIT,
) -> List[Any]:
    results: List[Any] = []
    for i in range(0, len(tasks), batch_size):
        batch = tasks[i : i + batch_size]
        batch_results = await asyncio.gather(*batch, return_exceptions=True)
        results.extend(batch_results)
    return [r for r in results if not isinstance(r, Exception)]
