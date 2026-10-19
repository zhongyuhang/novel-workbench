"""Line diff for chapter plain text. This is a display aid, not a manuscript format."""

import difflib
from dataclasses import dataclass


@dataclass(frozen=True)
class TextHunk:
    op: str
    text: str


def diff_lines(left: str, right: str) -> list[TextHunk]:
    """Return equal, delete, and insert hunks. ``left`` is the older side."""

    if left == right:
        if left == "":
            return []
        return [TextHunk("equal", left)]
    matcher = difflib.SequenceMatcher(
        a=left.splitlines(),
        b=right.splitlines(),
        autojunk=False,
    )
    hunks: list[TextHunk] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            _push(hunks, "equal", left.splitlines()[i1:i2])
        elif tag == "delete":
            _push(hunks, "delete", left.splitlines()[i1:i2])
        elif tag == "insert":
            _push(hunks, "insert", right.splitlines()[j1:j2])
        else:
            _push(hunks, "delete", left.splitlines()[i1:i2])
            _push(hunks, "insert", right.splitlines()[j1:j2])
    return hunks


def _push(hunks: list[TextHunk], op: str, lines: list[str]) -> None:
    if not lines:
        return
    hunks.append(TextHunk(op, "\n".join(lines)))
