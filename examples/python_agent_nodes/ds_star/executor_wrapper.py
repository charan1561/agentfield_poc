"""Async wrapper for DS_star's synchronous code executor."""

from __future__ import annotations

import asyncio

from ds_star.executor import run_python_code


async def execute_code_async(
    code: str,
    workdir: str,
    timeout_sec: int = 120,
):
    """Run Python code in a subprocess without blocking the event loop.

    DS_star's run_python_code() uses subprocess.run (synchronous).
    This wrapper delegates to a thread pool via asyncio.to_thread().
    """
    return await asyncio.to_thread(
        run_python_code,
        code,
        workdir=workdir,
        timeout_sec=timeout_sec,
    )
