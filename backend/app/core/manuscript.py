"""Render canonical Tiptap JSON to Markdown or plain text.

Export is a projection. The database keeps a single ``tiptap_json`` body.
"""

from app.core.content import document_to_text

_PREVIEW_LIMIT = 120
_BLOCK_TYPES = {
    "blockquote",
    "bulletList",
    "codeBlock",
    "doc",
    "heading",
    "horizontalRule",
    "listItem",
    "orderedList",
    "paragraph",
}


def document_to_plain(document: dict[str, object]) -> str:
    return _plain_node(document).strip("\n")


def document_to_markdown(document: dict[str, object]) -> str:
    content = document.get("content")
    if not isinstance(content, list):
        return document_to_text(document).strip("\n")
    parts = [_markdown_block(node) for node in content if isinstance(node, dict)]
    return "\n\n".join(part for part in parts if part != "")


def preview_text(document: dict[str, object], limit: int = _PREVIEW_LIMIT) -> str:
    collapsed = " ".join(document_to_plain(document).split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "…"


def _plain_node(node: dict[str, object]) -> str:
    node_type = node.get("type")
    if node_type == "text":
        text = node.get("text")
        return text if isinstance(text, str) else ""
    if node_type == "hardBreak":
        return "\n"
    if node_type == "horizontalRule":
        return ""
    if node_type == "image":
        return _attr_text(node, "alt")
    content = node.get("content")
    children = content if isinstance(content, list) else []
    if node_type in {"bulletList", "orderedList"}:
        lines = [_plain_node(child).strip("\n") for child in children if isinstance(child, dict)]
        return "\n".join(line for line in lines if line != "")
    if node_type == "doc" or _children_are_blocks(children):
        blocks = [_plain_node(child).strip("\n") for child in children if isinstance(child, dict)]
        separator = "\n\n" if node_type == "doc" else "\n"
        return separator.join(block for block in blocks if block != "")
    return "".join(_plain_node(child) if isinstance(child, dict) else "" for child in children)


def _markdown_block(node: dict[str, object]) -> str:
    node_type = node.get("type")
    if node_type == "heading":
        level = _heading_level(node)
        text = _markdown_inline(node.get("content")).strip()
        return f"{'#' * level} {text}".rstrip()
    if node_type == "paragraph":
        return _markdown_inline(node.get("content"))
    if node_type == "blockquote":
        inner = _markdown_container(node.get("content"))
        if inner == "":
            return ">"
        return "\n".join(f"> {line}" if line else ">" for line in inner.split("\n"))
    if node_type == "codeBlock":
        return f"```\n{_raw_text(node.get('content'))}\n```"
    if node_type == "bulletList":
        return _markdown_list(node, ordered=False)
    if node_type == "orderedList":
        return _markdown_list(node, ordered=True)
    if node_type == "horizontalRule":
        return "---"
    if node_type == "image":
        return _image_markdown(node)
    if node_type == "listItem":
        return _markdown_container(node.get("content"))
    content = node.get("content")
    if isinstance(content, list) and _children_are_blocks(content):
        return _markdown_container(content)
    return _markdown_inline(content)


def _markdown_container(nodes: object) -> str:
    if not isinstance(nodes, list):
        return ""
    parts = [_markdown_block(node) for node in nodes if isinstance(node, dict)]
    return "\n\n".join(part for part in parts if part != "")


def _markdown_list(node: dict[str, object], *, ordered: bool) -> str:
    content = node.get("content")
    if not isinstance(content, list):
        return ""
    index = 1
    attrs = node.get("attrs")
    if ordered and isinstance(attrs, dict) and isinstance(attrs.get("start"), int):
        index = attrs["start"]
    lines: list[str] = []
    for child in content:
        if not isinstance(child, dict):
            continue
        item = (
            _markdown_container(child.get("content"))
            if child.get("type") == "listItem"
            else _markdown_block(child)
        )
        item_lines = item.split("\n") if item else [""]
        prefix = f"{index}. " if ordered else "- "
        pad = " " * len(prefix)
        lines.append(prefix + item_lines[0])
        lines.extend(pad + extra for extra in item_lines[1:])
        if ordered:
            index += 1
    return "\n".join(lines)


def _markdown_inline(nodes: object) -> str:
    if not isinstance(nodes, list):
        return ""
    pieces: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_type = node.get("type")
        if node_type == "text" and isinstance(node.get("text"), str):
            pieces.append(_apply_marks(node["text"], node.get("marks")))
        elif node_type == "hardBreak":
            pieces.append("\\\n")
        else:
            pieces.append(_plain_node(node))
    return "".join(pieces)


def _apply_marks(text: str, marks: object) -> str:
    if not isinstance(marks, list) or not marks:
        return _escape_markdown(text)
    if any(isinstance(mark, dict) and mark.get("type") == "code" for mark in marks):
        return _wrap_code(text)
    rendered = _escape_markdown(text)
    for mark in marks:
        if not isinstance(mark, dict):
            continue
        mark_type = mark.get("type")
        if mark_type == "bold":
            rendered = f"**{rendered}**"
        elif mark_type == "italic":
            rendered = f"*{rendered}*"
        elif mark_type == "strike":
            rendered = f"~~{rendered}~~"
        elif mark_type == "link":
            href = _safe_href(_attr(mark, "href"))
            if href:
                rendered = f"[{rendered}]({href})"
    return rendered


def _image_markdown(node: dict[str, object]) -> str:
    alt = _attr_text(node, "alt")
    src = _safe_href(_attr(node, "src"))
    if src:
        return f"![{_escape_markdown(alt)}]({src})"
    return alt


def _raw_text(nodes: object) -> str:
    if not isinstance(nodes, list):
        return ""
    return _plain_node({"type": "paragraph", "content": nodes})


def _children_are_blocks(children: list[object]) -> bool:
    return any(isinstance(child, dict) and child.get("type") in _BLOCK_TYPES for child in children)


def _heading_level(node: dict[str, object]) -> int:
    attrs = node.get("attrs")
    level = attrs.get("level") if isinstance(attrs, dict) else None
    if isinstance(level, int):
        return min(max(level, 1), 6)
    return 1


def _attr(node: dict[str, object], key: str) -> object:
    attrs = node.get("attrs")
    if isinstance(attrs, dict):
        return attrs.get(key)
    return None


def _attr_text(node: dict[str, object], key: str) -> str:
    value = _attr(node, key)
    return value if isinstance(value, str) else ""


def _safe_href(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    href = value.strip()
    lowered = href.lower()
    if lowered.startswith(("https://", "http://", "mailto:")):
        return href.replace(" ", "%20")
    return None


def _escape_markdown(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("*", "\\*")
        .replace("_", "\\_")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )


def _wrap_code(text: str) -> str:
    fence = "`"
    while fence in text:
        fence += "`"
    return f"{fence}{text}{fence}"
