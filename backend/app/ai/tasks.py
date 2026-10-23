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

# Hard stops that can leave a usable stream. A non-empty buffer becomes a
# completed candidate instead of a failed task with stranded text.
PARTIAL_STOP_CODES = frozenset({"MODEL_TIMEOUT", "MODEL_UNAVAILABLE", "MODEL_BAD_RESPONSE"})


def is_partial_candidate(status: str, error_code: str | None, output_text: str | None) -> bool:
    """True when a completed task kept a fragment from a timeout or similar stop."""

    return (
        status == TaskStatus.COMPLETED.value
        and (error_code or "") in PARTIAL_STOP_CODES
        and bool((output_text or "").strip())
    )


def partial_candidate_message(code: str) -> str:
    if code == "MODEL_TIMEOUT":
        return "模型超时，已保留已生成的片段。正文还没改，可以采纳这段候选。"
    if code == "MODEL_UNAVAILABLE":
        return "模型中断了，已保留已生成的片段。正文还没改，可以采纳这段候选。"
    return "模型返回中断，已保留已生成的片段。正文还没改，可以采纳这段候选。"


def transition(current: TaskStatus, target: TaskStatus) -> TaskStatus:
    if target not in _TRANSITIONS[current]:
        raise IllegalTaskTransition(current, target)
    return target
