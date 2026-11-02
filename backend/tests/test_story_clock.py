"""Story clock parser and dimensional as-of fold."""

from __future__ import annotations

from datetime import UTC, datetime

from app.services.story_clock import (
    AsOfInput,
    fold_as_of,
    parse_story_clock,
    resolve_validity,
)


def test_parse_ordinal_day() -> None:
    parsed = parse_story_clock("第3天黄昏前")
    assert parsed.precision == "day"
    assert parsed.valid_from_day == 3
    assert parsed.valid_to_day == 3


def test_parse_relative_needs_anchor() -> None:
    assert parse_story_clock("次日").precision == "unknown"
    parsed = parse_story_clock("次日", anchor_day=10)
    assert parsed.valid_from_day == 11
    assert parsed.precision == "day"


def test_unparsed_never_raises() -> None:
    parsed = parse_story_clock("某个说不清的时候")
    assert parsed.precision == "unknown"
    assert parsed.valid_from_day is None
    assert resolve_validity("看不懂", "也看不懂").precision == "unknown"


def test_fold_as_of_three_chapters() -> None:
    """Hand-reasoned: at chapter order 1, city/alive/injury win; river/bell stay future."""

    now = datetime(2026, 1, 1, tzinfo=UTC)

    def row(
        *,
        id: str,
        dimension: str,
        chapter_order: int,
        day: int | None,
    ) -> AsOfInput:
        return AsOfInput(
            id=id,
            entity_id="e1",
            dimension=dimension,
            chapter_order=chapter_order,
            valid_from_day=day,
            created_at=now,
        )

    rows = [
        row(id="loc_village", dimension="location", chapter_order=0, day=1),
        row(id="alive", dimension="alive", chapter_order=0, day=1),
        row(id="loc_city", dimension="location", chapter_order=1, day=5),
        row(id="injury", dimension="injury", chapter_order=1, day=5),
        row(id="loc_river", dimension="location", chapter_order=2, day=2),
        row(id="bell", dimension="possession", chapter_order=2, day=6),
    ]
    as_of = {item.id for item in fold_as_of(rows, current_order=1)}
    assert as_of == {"loc_city", "alive", "injury"}
    assert "loc_river" not in as_of
    assert "bell" not in as_of
