"""Context packing keeps hard constraints and drops distant material first."""

from app.services.context_builder import ContextPiece, assemble_context


def test_budget_keeps_chapter_constraints_and_drops_distant_summary() -> None:
    pieces = [
        ContextPiece("system", "系统规则保持", True, False, 0),
        ContextPiece("instruction", "本次指令保持", True, False, 0),
        ContextPiece("rules", "硬规则保持", True, True, 1),
        ContextPiece("chapter", "当前章节约束保持", True, False, 1),
        ContextPiece("previous", "前文衔接保持\n" + ("前" * 400), True, True, 2),
        ContextPiece("state", "人物当前状态保持", True, False, 2),
        ContextPiece("guess", "不确定推断标记", False, False, 70),
        ContextPiece("distant", "远距离摘要标记UNIQUE", False, False, 60),
    ]

    full = assemble_context(pieces, 10_000)
    tight = assemble_context(pieces, 180)

    assert "远距离摘要标记UNIQUE" in full
    assert "不确定推断标记" in full
    for marker in (
        "系统规则保持",
        "本次指令保持",
        "硬规则保持",
        "当前章节约束保持",
        "前文衔接保持",
        "人物当前状态保持",
    ):
        assert marker in tight
    assert "远距离摘要标记UNIQUE" not in tight
    assert "不确定推断标记" not in tight
    assert "前" * 200 not in tight
