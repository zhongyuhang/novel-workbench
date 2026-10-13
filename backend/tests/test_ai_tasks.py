"""AI task lifecycle scaffold."""

import pytest

from app.ai.tasks import TERMINAL_TASK_STATUSES, IllegalTaskTransition, TaskStatus, transition


def test_happy_path_reaches_completed_candidate() -> None:
    running = transition(TaskStatus.QUEUED, TaskStatus.RUNNING)
    completed = transition(running, TaskStatus.COMPLETED)

    assert completed is TaskStatus.COMPLETED
    assert completed in TERMINAL_TASK_STATUSES


def test_cancel_from_queued_or_running() -> None:
    assert transition(TaskStatus.QUEUED, TaskStatus.CANCELLED) is TaskStatus.CANCELLED
    assert transition(TaskStatus.RUNNING, TaskStatus.CANCELLED) is TaskStatus.CANCELLED


def test_running_can_fail() -> None:
    assert transition(TaskStatus.RUNNING, TaskStatus.FAILED) is TaskStatus.FAILED


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (TaskStatus.COMPLETED, TaskStatus.RUNNING),
        (TaskStatus.FAILED, TaskStatus.COMPLETED),
        (TaskStatus.CANCELLED, TaskStatus.COMPLETED),
        (TaskStatus.QUEUED, TaskStatus.COMPLETED),
        (TaskStatus.RUNNING, TaskStatus.QUEUED),
    ],
)
def test_illegal_or_late_transition_is_rejected(current: TaskStatus, target: TaskStatus) -> None:
    with pytest.raises(IllegalTaskTransition):
        transition(current, target)
