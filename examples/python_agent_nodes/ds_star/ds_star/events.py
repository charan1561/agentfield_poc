from __future__ import annotations
import time
import threading
import collections
from typing import Optional, Dict, Any, List, DefaultDict
from pydantic import BaseModel, Field


class Event(BaseModel):
    """
    Generic event model for agent observability.
    - type: semantic event type (e.g., 'run_started', 'node_started', 'verify_verdict')
    - ts: UNIX timestamp (seconds)
    - run_id: unique identifier for a run
    - node: optional node name (e.g., 'analyze', 'verify')
    - iteration: refine iteration counter (if applicable)
    - status: optional status ('running', 'ok', 'error')
    - payload: arbitrary structured data for the event
    """
    type: str
    ts: float = Field(default_factory=lambda: time.time())
    run_id: str
    node: Optional[str] = None
    iteration: int = 0
    status: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class EventBus:
    """
    In-memory event bus suitable for single-process runs and simple dashboards.
    Stores events per run_id; supports appending and querying slices.
    Thread-safe for basic usage.
    """
    def __init__(self) -> None:
        self._events: DefaultDict[str, List[Event]] = collections.defaultdict(list)
        self._lock = threading.Lock()

    def create_run(self, run_id: str) -> None:
        with self._lock:
            # Touch run_id to ensure container exists
            _ = self._events[run_id]

    def emit(self, event: Event) -> None:
        with self._lock:
            self._events[event.run_id].append(event)

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
        evt = Event(
            type=type,
            ts=ts if ts is not None else time.time(),
            run_id=run_id,
            node=node,
            iteration=iteration,
            status=status,
            payload=payload or {},
        )
        self.emit(evt)

    def get_events(self, run_id: str, from_index: int = 0) -> List[Event]:
        """
        Returns events for a run starting at a given index (inclusive).
        Useful for polling or streaming slices.
        """
        with self._lock:
            if run_id not in self._events:
                return []
            # Return a shallow copy slice to avoid external mutation
            return list(self._events[run_id][from_index:])

    def latest_index(self, run_id: str) -> int:
        """
        Returns the next index after the last event for the run.
        """
        with self._lock:
            return len(self._events.get(run_id, []))

    def latest(self, run_id: str) -> Optional[Event]:
        with self._lock:
            events = self._events.get(run_id, [])
            return events[-1] if events else None
