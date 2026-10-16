"""In-process SSE fanout. Task rows remain the source of truth after disconnect."""

import json
import threading
from collections.abc import Iterator

TERMINAL_EVENTS = frozenset({"task.completed", "task.failed", "task.cancelled"})


class TaskBroker:
    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._events: dict[str, list[tuple[str, dict[str, object]]]] = {}
        self._conditions: dict[str, threading.Condition] = {}
        self._terminal: dict[str, str] = {}

    def _condition(self, task_id: str) -> threading.Condition:
        with self._guard:
            condition = self._conditions.get(task_id)
            if condition is None:
                condition = threading.Condition()
                self._conditions[task_id] = condition
                self._events.setdefault(task_id, [])
            return condition

    def publish(self, task_id: str, event: str, data: dict[str, object]) -> None:
        condition = self._condition(task_id)
        with condition:
            if event in TERMINAL_EVENTS and task_id in self._terminal:
                return
            self._events[task_id].append((event, data))
            if event in TERMINAL_EVENTS:
                self._terminal[task_id] = event
            condition.notify_all()

    def iter_events(
        self,
        task_id: str,
        heartbeat_seconds: float,
    ) -> Iterator[tuple[str, dict[str, object]]]:
        condition = self._condition(task_id)
        cursor = 0
        while True:
            heartbeat = False
            with condition:
                while cursor >= len(self._events[task_id]) and task_id not in self._terminal:
                    if not condition.wait(timeout=heartbeat_seconds):
                        if cursor >= len(self._events[task_id]) and task_id not in self._terminal:
                            heartbeat = True
                        break
                if heartbeat:
                    batch: list[tuple[str, dict[str, object]]] = []
                    done = False
                else:
                    batch = list(self._events[task_id][cursor:])
                    cursor = len(self._events[task_id])
                    done = task_id in self._terminal and cursor >= len(self._events[task_id])
            if heartbeat:
                yield ("heartbeat", {"task_id": task_id})
                continue
            yield from batch
            if done:
                return


def encode_sse(event: str, data: dict[str, object]) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"
