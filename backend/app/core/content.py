"""Canonical chapter body format. See docs/adr/ADR-001-content-format.md."""

import copy
import json

from app.core.errors import InvalidDocument, SelectionNotFound

CANONICAL_CONTENT_FORMAT = "tiptap_json"
CANONICAL_CONTENT_FORMAT_VERSION = 1
MAX_DOCUMENT_CHARS = 1_500_000
_MAX_DEPTH = 40


def empty_document() -> dict[str, object]:
    return {"type": "doc", "content": [{"type": "paragraph"}]}


def validate_document(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or value.get("type") != "doc":
        raise InvalidDocument()
    encoded = json.dumps(value, ensure_ascii=False)
    if len(encoded) > MAX_DOCUMENT_CHARS:
        raise InvalidDocument("正文超过可保存的长度。")
    _walk(value, 0)
    return value


def document_to_text(document: dict[str, object]) -> str:
    content = document.get("content")
    if not isinstance(content, list):
        return ""
    blocks = [_inline_text(node) for node in content if isinstance(node, dict)]
    return "\n\n".join(blocks)


def word_count(document: dict[str, object]) -> int:
    return sum(1 for char in document_to_text(document) if not char.isspace())


def canonical_dump(document: dict[str, object]) -> str:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def text_to_document(text: str) -> dict[str, object]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if normalized == "":
        return empty_document()
    blocks: list[dict[str, object]] = []
    for paragraph in normalized.split("\n\n"):
        children: list[dict[str, object]] = []
        for index, line in enumerate(paragraph.split("\n")):
            if index:
                children.append({"type": "hardBreak"})
            if line:
                children.append({"type": "text", "text": line})
        if children:
            blocks.append({"type": "paragraph", "content": children})
        else:
            blocks.append({"type": "paragraph"})
    return {"type": "doc", "content": blocks}


def apply_candidate_text(
    document: dict[str, object],
    candidate: str,
    *,
    mode: str,
    selection_text: str,
) -> dict[str, object]:
    """Return a new Tiptap document. Does not write the chapter."""

    base = validate_document(copy.deepcopy(document))
    cleaned = candidate.strip()
    if cleaned == "":
        raise InvalidDocument("候选文本是空的，没有改写正文。")
    blocks = _paragraphs(cleaned)
    content = base.get("content")
    if not isinstance(content, list):
        content = []
        base["content"] = content
    selection = selection_text.strip()
    if mode == "append" or (mode == "insert" and selection == ""):
        content.extend(copy.deepcopy(blocks))
        return validate_document(base)
    source = document_to_text(base)
    if mode == "replace_selection":
        if selection == "":
            return validate_document(text_to_document(cleaned))
        if selection not in source:
            raise SelectionNotFound()
        return validate_document(text_to_document(source.replace(selection, cleaned, 1)))
    if mode == "insert":
        if selection not in source:
            raise SelectionNotFound()
        inserted = source.replace(selection, f"{selection}\n\n{cleaned}", 1)
        return validate_document(text_to_document(inserted))
    raise InvalidDocument("不支持的采纳方式。")


def _paragraphs(text: str) -> list[dict[str, object]]:
    content = text_to_document(text).get("content")
    if not isinstance(content, list):
        return []
    return [node for node in content if isinstance(node, dict)]


def _inline_text(node: dict[str, object]) -> str:
    pieces: list[str] = []
    _collect_inline(node, pieces, 0)
    return "".join(pieces)


def _walk(node: object, depth: int) -> None:
    if depth > _MAX_DEPTH:
        raise InvalidDocument("正文结构过深。")
    if isinstance(node, dict):
        for child in node.values():
            _walk(child, depth + 1)
        return
    if isinstance(node, list):
        for child in node:
            _walk(child, depth + 1)


def _collect_inline(node: object, pieces: list[str], depth: int) -> None:
    if depth > _MAX_DEPTH:
        raise InvalidDocument("正文结构过深。")
    if isinstance(node, list):
        for item in node:
            _collect_inline(item, pieces, depth + 1)
        return
    if not isinstance(node, dict):
        return
    node_type = node.get("type")
    if node_type == "text" and isinstance(node.get("text"), str):
        pieces.append(str(node["text"]))
        return
    if node_type == "hardBreak":
        pieces.append("\n")
        return
    children = node.get("content")
    if isinstance(children, list):
        for child in children:
            _collect_inline(child, pieces, depth + 1)
