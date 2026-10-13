"""Whole-novel Markdown and TXT export."""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import cast
from urllib.parse import quote

from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.core.manuscript import document_to_markdown, document_to_plain
from app.models.catalog import Chapter, Volume
from app.repositories import catalog as catalog_repo

_FILENAME_UNSAFE = re.compile(r"[\\/:*?\"<>|\r\n]+")


@dataclass(frozen=True)
class ExportFile:
    filename: str
    media_type: str
    body: str
    disposition: str


def export_novel(session: Session, novel_id: str, export_format: str) -> ExportFile:
    novel = catalog_repo.get_novel(session, novel_id)
    if novel is None:
        raise NotFound("作品不存在。")
    volumes = catalog_repo.list_volumes(session, novel_id)
    chapters = catalog_repo.list_chapters(session, novel_id)
    extension = "md" if export_format == "markdown" else "txt"
    media_type = (
        "text/markdown; charset=utf-8"
        if export_format == "markdown"
        else "text/plain; charset=utf-8"
    )
    if export_format == "markdown":
        body = _markdown_book(novel.title, novel.synopsis, volumes, chapters)
    else:
        body = _plain_book(novel.title, novel.synopsis, volumes, chapters)
    filename = _filename(novel.title, extension)
    return ExportFile(
        filename=filename,
        media_type=media_type,
        body=body,
        disposition=_disposition(filename, extension),
    )


def _markdown_book(
    title: str,
    synopsis: str | None,
    volumes: list[Volume],
    chapters: list[Chapter],
) -> str:
    parts = [f"# {_one_line(title)}"]
    if synopsis and synopsis.strip():
        parts.append(synopsis.strip())
    parts.extend(_markdown_sections(volumes, chapters))
    return "\n\n".join(parts).rstrip() + "\n"


def _plain_book(
    title: str,
    synopsis: str | None,
    volumes: list[Volume],
    chapters: list[Chapter],
) -> str:
    parts = [_one_line(title)]
    if synopsis and synopsis.strip():
        parts.append(synopsis.strip())
    parts.extend(_plain_sections(volumes, chapters))
    return "\n\n".join(parts).rstrip() + "\n"


def _markdown_sections(volumes: list[Volume], chapters: list[Chapter]) -> list[str]:
    sections: list[str] = []
    for heading, grouped in _ordered_groups(volumes, chapters):
        block = [f"## {_one_line(heading)}"] if heading else []
        for chapter in grouped:
            block.append(f"### {_one_line(chapter.title)}")
            body = _body_markdown(chapter.content)
            if body:
                block.append(body)
        if block:
            sections.append("\n\n".join(block))
    return sections


def _plain_sections(volumes: list[Volume], chapters: list[Chapter]) -> list[str]:
    sections: list[str] = []
    for heading, grouped in _ordered_groups(volumes, chapters):
        block = [_one_line(heading)] if heading else []
        for chapter in grouped:
            block.append(_one_line(chapter.title))
            body = _body_plain(chapter.content)
            if body:
                block.append(body)
        if block:
            sections.append("\n\n".join(block))
    return sections


def _ordered_groups(
    volumes: list[Volume],
    chapters: list[Chapter],
) -> list[tuple[str | None, list[Chapter]]]:
    """Match the workspace table of contents.

    Unassigned chapters come first, then volumes by ``sort_order``.
    Chapters inside a group follow ``sort_order``.
    """

    groups: list[tuple[str | None, list[Chapter]]] = []
    unassigned = _sorted_chapters(chapter for chapter in chapters if chapter.volume_id is None)
    if unassigned:
        groups.append(("未分卷", unassigned))
    for volume in sorted(volumes, key=lambda item: (item.sort_order, item.id)):
        grouped = _sorted_chapters(
            chapter for chapter in chapters if chapter.volume_id == volume.id
        )
        groups.append((volume.title, grouped))
    return groups


def _sorted_chapters(chapters: Iterable[Chapter]) -> list[Chapter]:
    return sorted(chapters, key=lambda chapter: (chapter.sort_order, chapter.id))


def _as_document(content: object) -> dict[str, object] | None:
    if isinstance(content, dict):
        return cast(dict[str, object], content)
    return None


def _body_markdown(content: object) -> str:
    document = _as_document(content)
    if document is None:
        return ""
    return document_to_markdown(document)


def _body_plain(content: object) -> str:
    document = _as_document(content)
    if document is None:
        return ""
    return document_to_plain(document)


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _filename(title: str, extension: str) -> str:
    cleaned = _FILENAME_UNSAFE.sub(" ", title).strip()
    cleaned = cleaned[:80] or "novel"
    return f"{cleaned}.{extension}"


def _disposition(filename: str, extension: str) -> str:
    fallback = f"novel.{extension}"
    encoded = quote(filename, safe="")
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"
