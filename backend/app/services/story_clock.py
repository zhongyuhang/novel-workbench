"""Story-time assist and dimensional as-of states.

Discourse time stays the chapter reading order. These helpers only add an
optional day count relative to a 360-day story year (30-day months, day 1 is
1年1月1日 and 第1天). Text that does not match a rule stays unknown. Nothing
here raises, and an unknown result is not a conflict.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.models.memory import EntityState, StoryEntity, StoryEvent, StoryTimeAnchor
from app.repositories import catalog as catalog_repo
from app.schemas.story_clock import (
    StoryTimeAnchorCreate,
    StoryTimeAnchorResponse,
    StoryTimeAnchorUpdate,
)

Dimension = Literal["location", "alive", "injury", "possession", "identity", "custom"]
Precision = Literal["day", "month", "season", "unknown"]

DIMENSIONS: tuple[Dimension, ...] = (
    "location",
    "alive",
    "injury",
    "possession",
    "identity",
    "custom",
)
DIMENSION_LABELS: dict[Dimension, str] = {
    "location": "地点",
    "alive": "生死",
    "injury": "伤势",
    "possession": "持有",
    "identity": "身份",
    "custom": "其他",
}
_DIMENSIONS: dict[str, Dimension] = {item: item for item in DIMENSIONS}
_PRECISIONS: dict[str, Precision] = {
    "day": "day",
    "month": "month",
    "season": "season",
    "unknown": "unknown",
}
_PRECISION_RANK: dict[Precision, int] = {"unknown": 0, "day": 1, "month": 2, "season": 3}
_YEAR_DAYS = 360
_MONTH_DAYS = 30
_SEASON_MONTHS: dict[str, tuple[int, int]] = {
    "春": (1, 3),
    "夏": (4, 6),
    "秋": (7, 9),
    "冬": (10, 12),
}
_CN_DIGIT = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_NUM = r"(?:\d{1,6}|[零〇一两二三四五六七八九十百千]{1,12})"
_ORDINAL_DAY = re.compile(rf"第\s*({_NUM})\s*[天日]")
_YMD = re.compile(rf"({_NUM})\s*年\s*({_NUM})\s*月\s*({_NUM})\s*[日号]")
_YM = re.compile(rf"({_NUM})\s*年\s*({_NUM})\s*月")
_YEAR_SEASON = re.compile(rf"(?:第\s*)?({_NUM})\s*年\s*(春|夏|秋|冬)")
_AFTER = re.compile(rf"({_NUM})\s*[天日]\s*(?:之)?后")
_NEXT = re.compile(r"次日|翌日|明日")
_PREV = re.compile(r"昨日|前日|昨天")
_SAME = re.compile(r"当日|当天|这天|本日")
_BEFORE_TOD = re.compile(r"(?:黄昏|傍晚|黎明|天亮|午前|午后|子时|拂晓)前")
_SEASON = re.compile(r"春|夏|秋|冬")
_DAY_MIN = -1_000_000
_DAY_MAX = 1_000_000


class ParsedStoryTime:
    """A fuzzy story-time window. Unknown means the text was left alone."""

    __slots__ = ("precision", "valid_from_day", "valid_to_day")

    def __init__(
        self,
        valid_from_day: int | None,
        valid_to_day: int | None,
        precision: Precision,
    ) -> None:
        self.valid_from_day = valid_from_day
        self.valid_to_day = valid_to_day
        self.precision = precision


UNKNOWN = ParsedStoryTime(None, None, "unknown")


class AsOfInput:
    """One state already placed on the discourse timeline."""

    __slots__ = (
        "chapter_order",
        "created_at",
        "dimension",
        "entity_id",
        "id",
        "valid_from_day",
    )

    def __init__(
        self,
        *,
        id: str,
        entity_id: str,
        dimension: str,
        chapter_order: int,
        valid_from_day: int | None,
        created_at: datetime,
    ) -> None:
        self.id = id
        self.entity_id = entity_id
        self.dimension = dimension
        self.chapter_order = chapter_order
        self.valid_from_day = valid_from_day
        self.created_at = created_at


def normalize_dimension(value: str | None) -> Dimension:
    if value is None:
        return "custom"
    return _DIMENSIONS.get(value, "custom")


def normalize_precision(value: str | None) -> Precision:
    if value is None:
        return "unknown"
    return _PRECISIONS.get(value, "unknown")


def optional_day(value: object) -> int | None:
    """Return a story-day integer, or None. Never raises."""

    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < _DAY_MIN or value > _DAY_MAX:
        return None
    return value


def parse_story_clock(
    text: str | None,
    *,
    anchor_day: int | None = None,
) -> ParsedStoryTime:
    """Parse a common Chinese story-time phrase.

    Relative phrases (次日, 三日后, 黄昏前) need ``anchor_day``. Anything else,
    including empty text, stays unknown with null days.
    """

    try:
        return _parse_story_clock(text, anchor_day=anchor_day)
    except Exception:
        return UNKNOWN


def resolve_validity(
    valid_from_text: str | None,
    valid_until_text: str | None,
    *,
    anchor_day: int | None = None,
) -> ParsedStoryTime:
    """Combine the two free-text bounds. Unparsed bounds stay null."""

    try:
        start = parse_story_clock(valid_from_text, anchor_day=anchor_day)
        until = valid_until_text.strip() if isinstance(valid_until_text, str) else ""
        if until == "":
            return start
        end_anchor = start.valid_from_day if start.valid_from_day is not None else anchor_day
        end = parse_story_clock(until, anchor_day=end_anchor)
        from_day = start.valid_from_day
        to_day = end.valid_to_day
        precision = _coarser(start.precision, end.precision)
        if from_day is None and to_day is None:
            return UNKNOWN
        if from_day is not None and to_day is not None and from_day > to_day:
            from_day, to_day = to_day, from_day
        return ParsedStoryTime(from_day, to_day, precision)
    except Exception:
        return UNKNOWN


def resolve_stored_clock(
    *,
    valid_from_text: str | None,
    valid_until_text: str | None,
    valid_from_day: int | None,
    valid_to_day: int | None,
    time_precision: str | None,
    override_from: bool,
    override_to: bool,
    override_precision: bool,
) -> tuple[int | None, int | None, Precision]:
    """Explicit days win. Otherwise fill from the rule parser."""

    parsed = resolve_validity(valid_from_text, valid_until_text)
    from_day = valid_from_day if override_from else parsed.valid_from_day
    to_day = valid_to_day if override_to else parsed.valid_to_day
    if override_precision:
        precision = normalize_precision(time_precision)
    elif override_from or override_to:
        if from_day is None and to_day is None:
            precision = "unknown"
        else:
            precision = parsed.precision if parsed.precision != "unknown" else "day"
    else:
        precision = parsed.precision
    return from_day, to_day, precision


def apply_event_clock(event: StoryEvent) -> None:
    """Fill an event's story-day columns from ``event_time_text``."""

    parsed = parse_story_clock(event.event_time_text)
    event.valid_from_day = parsed.valid_from_day
    event.valid_to_day = parsed.valid_to_day
    event.time_precision = parsed.precision


def fold_as_of(rows: Sequence[AsOfInput], *, current_order: int | None) -> list[AsOfInput]:
    """One winner per entity and dimension, at or before ``current_order``.

    When both rows have ``valid_from_day``, the later story day wins. Otherwise
    the later chapter order wins. A missing day never raises and never outranks
    a later chapter on its own.
    """

    winners: dict[tuple[str, Dimension], AsOfInput] = {}
    for row in rows:
        if current_order is not None and row.chapter_order > current_order:
            continue
        dimension = normalize_dimension(row.dimension)
        key = (row.entity_id, dimension)
        current = winners.get(key)
        if current is None or _later(row, current):
            winners[key] = row
    return sorted(
        winners.values(),
        key=lambda item: (
            item.entity_id,
            DIMENSIONS.index(normalize_dimension(item.dimension)),
            item.id,
        ),
    )


def pick_states(
    states: Sequence[EntityState],
    positions: dict[str, int],
    current_order: int | None,
) -> dict[str, list[EntityState]]:
    """Fold ORM states. A chapter missing from ``positions`` is dropped."""

    paired: list[tuple[AsOfInput, EntityState]] = []
    for state in states:
        order = positions.get(state.chapter_id)
        if order is None:
            continue
        paired.append(
            (
                AsOfInput(
                    id=state.id,
                    entity_id=state.entity_id,
                    dimension=state.dimension,
                    chapter_order=order,
                    valid_from_day=state.valid_from_day,
                    created_at=state.created_at,
                ),
                state,
            )
        )
    winners = fold_as_of([item[0] for item in paired], current_order=current_order)
    by_id = {state.id: state for _stamp, state in paired}
    grouped: dict[str, list[EntityState]] = {}
    for winner in winners:
        found = by_id.get(winner.id)
        if found is None:
            continue
        grouped.setdefault(winner.entity_id, []).append(found)
    return grouped


def state_as_of(
    session: Session,
    novel_id: str,
    entity_id: str,
    chapter_id: str,
) -> list[EntityState]:
    """States of one entity as of a chapter: no future chapter, one per dimension."""

    from app.services.context_builder import chapter_reading_index

    entity = session.get(StoryEntity, entity_id)
    if entity is None or entity.deleted_at is not None or entity.novel_id != novel_id:
        return []
    positions = chapter_reading_index(session, novel_id)
    current = positions.get(chapter_id)
    if current is None:
        return []
    states = list(session.scalars(select(EntityState).where(EntityState.entity_id == entity_id)))
    return pick_states(states, positions, current).get(entity_id, [])


def state_summary(state_data: object) -> str:
    """Short display text for a state payload. Empty when nothing is readable."""

    if not isinstance(state_data, dict):
        return ""
    for key in ("summary", "note", "value"):
        raw = state_data.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    parts: list[str] = []
    for key, raw in state_data.items():
        if isinstance(key, str) and isinstance(raw, str) and raw.strip():
            parts.append(raw.strip())
        if len(parts) >= 3:
            break
    return "；".join(parts)


def list_anchors(session: Session, novel_id: str) -> list[StoryTimeAnchorResponse]:
    _require_novel(session, novel_id)
    rows = session.scalars(
        select(StoryTimeAnchor)
        .where(StoryTimeAnchor.novel_id == novel_id)
        .order_by(StoryTimeAnchor.sort_order.asc(), StoryTimeAnchor.id.asc())
    )
    return [_anchor_response(row) for row in rows]


def create_anchor(
    session: Session,
    novel_id: str,
    payload: StoryTimeAnchorCreate,
) -> StoryTimeAnchorResponse:
    _require_novel(session, novel_id)
    now = datetime.now(UTC)
    row = StoryTimeAnchor(
        id=str(uuid.uuid4()),
        novel_id=novel_id,
        label=payload.label,
        kind=payload.kind,
        base_day=payload.base_day,
        sort_order=payload.sort_order,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _anchor_response(row)


def update_anchor(
    session: Session,
    anchor_id: str,
    payload: StoryTimeAnchorUpdate,
) -> StoryTimeAnchorResponse:
    row = _require_anchor(session, anchor_id)
    fields = payload.model_fields_set
    if "label" in fields and payload.label is not None:
        row.label = payload.label
    if "kind" in fields and payload.kind is not None:
        row.kind = payload.kind
    if "base_day" in fields and payload.base_day is not None:
        row.base_day = payload.base_day
    if "sort_order" in fields and payload.sort_order is not None:
        row.sort_order = payload.sort_order
    row.updated_at = datetime.now(UTC)
    session.commit()
    session.refresh(row)
    return _anchor_response(row)


def delete_anchor(session: Session, anchor_id: str) -> None:
    row = _require_anchor(session, anchor_id)
    session.delete(row)
    session.commit()


def _parse_story_clock(text: str | None, *, anchor_day: int | None) -> ParsedStoryTime:
    cleaned = text.strip() if isinstance(text, str) else ""
    if cleaned == "":
        return UNKNOWN
    matched = _ORDINAL_DAY.search(cleaned)
    if matched is not None:
        day = _cn_number(matched.group(1))
        if day is None or day < 1:
            return UNKNOWN
        return _point(day)
    matched = _YMD.search(cleaned)
    if matched is not None:
        placed = _ymd(
            _cn_number(matched.group(1)),
            _cn_number(matched.group(2)),
            _cn_number(matched.group(3)),
        )
        if placed is None:
            return UNKNOWN
        return _point(placed)
    matched = _YM.search(cleaned)
    if matched is not None:
        span = _month_span(_cn_number(matched.group(1)), _cn_number(matched.group(2)))
        if span is None:
            return UNKNOWN
        return span
    matched = _YEAR_SEASON.search(cleaned)
    if matched is not None:
        year = _cn_number(matched.group(1))
        span = _season_span(year, matched.group(2))
        if span is None:
            return UNKNOWN
        return span
    matched = _AFTER.search(cleaned)
    if matched is not None:
        count = _cn_number(matched.group(1))
        if anchor_day is None or count is None or count < 1:
            return UNKNOWN
        return _point(anchor_day + count)
    if _NEXT.search(cleaned) is not None:
        if anchor_day is None:
            return UNKNOWN
        return _point(anchor_day + 1)
    if _PREV.search(cleaned) is not None:
        if anchor_day is None:
            return UNKNOWN
        return _point(anchor_day - 1)
    if _SAME.search(cleaned) is not None or _BEFORE_TOD.search(cleaned) is not None:
        if anchor_day is None:
            return UNKNOWN
        return _point(anchor_day)
    matched = _SEASON.search(cleaned)
    if matched is not None:
        if anchor_day is None:
            return ParsedStoryTime(None, None, "season")
        year = _year_of(anchor_day)
        span = _season_span(year, matched.group(0))
        if span is None:
            return ParsedStoryTime(None, None, "season")
        return span
    return UNKNOWN


def _point(day: int) -> ParsedStoryTime:
    if day < _DAY_MIN or day > _DAY_MAX:
        return UNKNOWN
    return ParsedStoryTime(day, day, "day")


def _ymd(year: int | None, month: int | None, day: int | None) -> int | None:
    if year is None or month is None or day is None:
        return None
    if year < 1 or year > 10000 or month < 1 or month > 12 or day < 1 or day > _MONTH_DAYS:
        return None
    return (year - 1) * _YEAR_DAYS + (month - 1) * _MONTH_DAYS + day


def _month_span(year: int | None, month: int | None) -> ParsedStoryTime | None:
    start = _ymd(year, month, 1)
    end = _ymd(year, month, _MONTH_DAYS)
    if start is None or end is None:
        return None
    return ParsedStoryTime(start, end, "month")


def _season_span(year: int | None, season: str) -> ParsedStoryTime | None:
    bounds = _SEASON_MONTHS.get(season)
    if year is None or bounds is None:
        return None
    start = _ymd(year, bounds[0], 1)
    end = _ymd(year, bounds[1], _MONTH_DAYS)
    if start is None or end is None:
        return None
    return ParsedStoryTime(start, end, "season")


def _year_of(day: int) -> int:
    if day < 1:
        return 1
    return (day - 1) // _YEAR_DAYS + 1


def _cn_number(token: str | None) -> int | None:
    if token is None:
        return None
    cleaned = token.strip()
    if cleaned == "":
        return None
    if cleaned.isdigit():
        value = int(cleaned)
        if value > _DAY_MAX:
            return None
        return value
    total = 0
    current = 0
    seen = False
    for char in cleaned:
        if char in _CN_DIGIT:
            current = _CN_DIGIT[char]
            seen = True
            continue
        scale = {"十": 10, "百": 100, "千": 1000}.get(char)
        if scale is None:
            return None
        total += (current or 1) * scale
        current = 0
        seen = True
    if not seen:
        return None
    value = total + current
    if value > _DAY_MAX:
        return None
    return value


def _coarser(left: Precision, right: Precision) -> Precision:
    if left == "unknown":
        return right
    if right == "unknown":
        return left
    if _PRECISION_RANK[left] >= _PRECISION_RANK[right]:
        return left
    return right


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _later(candidate: AsOfInput, incumbent: AsOfInput) -> bool:
    left_day = candidate.valid_from_day
    right_day = incumbent.valid_from_day
    if left_day is not None and right_day is not None and left_day != right_day:
        return left_day > right_day
    if candidate.chapter_order != incumbent.chapter_order:
        return candidate.chapter_order > incumbent.chapter_order
    try:
        if _aware(candidate.created_at) != _aware(incumbent.created_at):
            return _aware(candidate.created_at) > _aware(incumbent.created_at)
    except (TypeError, ValueError):
        pass
    return candidate.id > incumbent.id


def _require_novel(session: Session, novel_id: str) -> None:
    if catalog_repo.get_novel(session, novel_id) is None:
        raise NotFound("作品不存在。")


def _require_anchor(session: Session, anchor_id: str) -> StoryTimeAnchor:
    row = session.get(StoryTimeAnchor, anchor_id)
    if row is None or catalog_repo.get_novel(session, row.novel_id) is None:
        raise NotFound("故事时间锚点不存在。")
    return row


def _anchor_response(row: StoryTimeAnchor) -> StoryTimeAnchorResponse:
    kind = row.kind if row.kind in {"era", "event", "custom"} else "custom"
    return StoryTimeAnchorResponse(
        id=row.id,
        novel_id=row.novel_id,
        label=row.label,
        kind=kind,  # type: ignore[arg-type]
        base_day=row.base_day,
        sort_order=row.sort_order,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
