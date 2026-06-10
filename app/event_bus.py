from __future__ import annotations

import json
import queue
import threading
from collections import defaultdict
from copy import deepcopy
from typing import Any, Iterator


class AgentEventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[queue.Queue]] = defaultdict(list)
        self._traces: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def publish(self, project_id: str, trace_id: str, event_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        event = {"project_id": project_id, "trace_id": trace_id, "type": event_type, "payload": payload or {}}
        with self._lock:
            trace = self._traces.setdefault(trace_id, {"trace_id": trace_id, "project_id": project_id, "events": []})
            trace["events"].append(deepcopy(event))
            targets = list(self._subscribers.get(project_id, [])) + list(self._subscribers.get("*", []))
        for target in targets:
            target.put(event)
        return event

    def trace(self, trace_id: str) -> dict[str, Any] | None:
        with self._lock:
            return deepcopy(self._traces.get(trace_id))

    def subscribe(self, project_id: str | None = None) -> Iterator[str]:
        key = project_id or "*"
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers[key].append(q)
        try:
            while True:
                event = q.get()
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
        finally:
            with self._lock:
                if q in self._subscribers.get(key, []):
                    self._subscribers[key].remove(q)


event_bus = AgentEventBus()
