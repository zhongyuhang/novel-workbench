"""Empty and near-empty chapters.

A resume that asks for the same title again should reopen the short draft
instead of inserting a second chapter in that slot. The next numbered title
is computed from the chapters the server already has.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

# A bridge sentence of a few dozen characters is still a shell. A real scene is longer.
SHELL_WORD_LIMIT = 40

_NUMBERED = re.compile(r"^第\s*([0-9]{1,4})\s*章$")


@dataclass(frozen=True)
class ShellChapter:
    id: str
    title: str
    word_count: int
    sort_order: int
    volume_id: str | None


def is_shell(word_count: int) -> bool:
    return word_count <= SHELL_WORD_LIMIT


def chapter_number(title: str) -> int | None:
    match = _NUMBERED.match(title.strip())
    if match is None:
        return None
    return int(match.group(1))


def next_numbered_title(titles: Sequence[str]) -> str:
    """Next「第N章」from the server list. Callers must not keep their own counter."""

    highest = 0
    numbered = False
    for title in titles:
        number = chapter_number(title)
        if number is None:
            continue
        numbered = True
        highest = max(highest, number)
    if not numbered:
        return "未命名章节"
    return f"第{max(highest, len(titles)) + 1}章"


def title_for_new_chapter(chapters: Sequence[tuple[str, int]]) -> str:
    """Reading-order (title, word_count) pairs. A trailing shell is reused by name."""

    if not chapters:
        return "未命名章节"
    last_title, last_count = chapters[-1]
    if is_shell(last_count) and last_title.strip():
        return last_title.strip()
    if any(chapter_number(title) is not None for title, _count in chapters):
        return next_numbered_title([title for title, _count in chapters])
    return "未命名章节"


def reusable_shell_id(
    chapters: Sequence[ShellChapter],
    title: str,
    volume_id: str | None,
) -> str | None:
    """Return an existing shell to open instead of inserting another row."""

    key = title.strip()
    number = chapter_number(key)
    shells = [
        chapter
        for chapter in chapters
        if chapter.volume_id == volume_id and is_shell(chapter.word_count)
    ]
    same_title = [chapter for chapter in shells if chapter.title.strip() == key]
    if same_title:
        return same_title[-1].id
    if number is None:
        return None
    same_number = [chapter for chapter in shells if chapter_number(chapter.title) == number]
    if same_number:
        return same_number[-1].id
    return None


def duplicate_shell_ids(chapters: Sequence[ShellChapter]) -> list[str]:
    """Shells that share a title with a longer chapter, or extra copies of the same shell."""

    groups: dict[tuple[str | None, str], list[ShellChapter]] = {}
    for chapter in chapters:
        groups.setdefault((chapter.volume_id, chapter.title.strip()), []).append(chapter)
    remove: list[str] = []
    for rows in groups.values():
        if len(rows) < 2:
            continue
        fullest = max(rows, key=lambda row: (row.word_count, row.sort_order, row.id))
        for row in rows:
            if row.id == fullest.id:
                continue
            if is_shell(row.word_count):
                remove.append(row.id)
    return remove
