"""Forwards DS_star EventBus events to AgentField for observability."""

from __future__ import annotations

import queue
import logging
from typing import Any, Dict, List, Optional

from ds_star.events import EventBus

logger = logging.getLogger(__name__)


class AgentFieldEventBridge(EventBus):
    """Extended EventBus that captures DS_star events for async forwarding.

    DS_star's LangGraph runs synchronously in a thread. Events are emitted
    synchronously. This bridge queues them in a thread-safe queue so they
    can be drained from the async AgentField context after the pipeline
    completes (or periodically during execution).
    """

    def __init__(self):
        super().__init__()
        self._queue: queue.Queue[Dict[str, Any]] = queue.Queue()

    def emit_dict(
        self,
        type: str,
        run_id: str,
        node: Optional[str] = None,
        iteration: int = 0,
        status: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        ts: Optional[float] = None,
    ) -> None:
        super().emit_dict(
            type=type, run_id=run_id, node=node,
            iteration=iteration, status=status, payload=payload, ts=ts,
        )
        try:
            self._queue.put_nowait({
                "type": type, "run_id": run_id, "node": node,
                "iteration": iteration, "status": status, "payload": payload,
            })
        except queue.Full:
            logger.warning("Event bridge queue full, dropping event")

    def drain(self) -> List[Dict[str, Any]]:
        """Drain all queued events. Call from async context after pipeline completes."""
        events: List[Dict[str, Any]] = []
        while True:
            try:
                events.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return events

    def pending_count(self) -> int:
        return self._queue.qsize()
