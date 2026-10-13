"""AI task state machine. Persistence and execution arrive with model integration.

States: queued -> running -> completed | failed | cancelled.
A successful generation is a candidate result, not an accepted chapter edit.
Terminal states cannot be overwritten by a late event.
"""

from enum import StrEnum


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class IllegalTaskTransition(Exception):
    def __init__(self, current: TaskStatus, target: TaskStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Cannot transition AI task from {current.value} to {target.value}.")


_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.QUEUED: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED}),
    TaskStatus.RUNNING: frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}

TERMINAL_TASK_STATUSES = frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED})


def transition(current: TaskStatus, target: TaskStatus) -> TaskStatus:
    if target not in _TRANSITIONS[current]:
        raise IllegalTaskTransition(current, target)
    return target
