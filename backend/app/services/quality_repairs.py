"""Repair suggestions for a stored quality issue.

Suggestions describe a possible edit. Nothing in this module writes a chapter.
"""

import difflib
import re
from dataclasses import dataclass

REPAIR_RULE_VERSION = "quality_repair_rules_v1"
REPAIR_MODEL_VERSION = "quality_repair_model_v1"
_NO_AUTO = "这只是候选，不会自动修改正文或正式记忆。"
_CALLED = re.compile(
    r"([\u4e00-\u9fffA-Za-z0-9]{1,16})(?:叫做|名叫|名为)([\u4e00-\u9fffA-Za-z0-9]{1,16})"
)


@dataclass(frozen=True)
class RepairDraft:
    apply_mode: str
    applicable: bool
    original_snippet: str
    replacement_text: str
    rationale: str
    diff_preview: str
    prompt_version: str
    provider_mode: str


def rule_repairs(
    *,
    rule_id: str,
    chapter_text: str,
    snippet: str,
    evidence: list[dict[str, object]],
    related_refs: list[dict[str, object]],
) -> list[RepairDraft]:
    """One or more candidates. Inapplicable rows explain why nothing can be applied."""

    drafts = _drafts_for(rule_id, chapter_text, snippet, evidence, related_refs)
    if drafts:
        return drafts[:3]
    return [
        _manual(
            snippet,
            "没有可安全套用的正文替换。定位只认文本片段，片段缺失、重复或这条问题不对应一处改写时，"
            "都不会猜一个位置去覆盖。请作者自己改。",
        )
    ]


def model_repairs(
    raw_items: object,
    *,
    chapter_text: str,
    snippet: str,
) -> list[RepairDraft]:
    """Model text replaces the stored snippet, or is appended when there is no snippet."""

    if not isinstance(raw_items, list):
        return []
    drafts: list[RepairDraft] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        replacement = item.get("replacement_text")
        rationale = item.get("rationale")
        if not isinstance(replacement, str) or replacement.strip() == "":
            continue
        reason = rationale.strip() if isinstance(rationale, str) else "模型给出的改写候选。"
        cleaned = replacement.strip()
        if snippet.strip():
            if chapter_text.count(snippet) != 1 or cleaned == snippet:
                continue
            drafts.append(
                _replace(
                    chapter_text,
                    snippet,
                    cleaned,
                    reason,
                    prompt_version=REPAIR_MODEL_VERSION,
                    provider_mode="openai_compatible",
                )
            )
        else:
            drafts.append(
                _append(
                    chapter_text,
                    cleaned,
                    reason,
                    prompt_version=REPAIR_MODEL_VERSION,
                    provider_mode="openai_compatible",
                )
            )
        if len(drafts) >= 3:
            break
    return drafts


def _drafts_for(
    rule_id: str,
    chapter_text: str,
    snippet: str,
    evidence: list[dict[str, object]],
    related_refs: list[dict[str, object]],
) -> list[RepairDraft]:
    if rule_id.startswith("fact."):
        return _fact_repairs(chapter_text, snippet, evidence)
    if rule_id == "text.repeated_paragraph":
        return _repeat_repairs(chapter_text, snippet)
    if rule_id == "text.repeated_punctuation":
        return _punctuation_repairs(chapter_text, snippet)
    if rule_id == "text.name_mismatch":
        return _name_repairs(chapter_text, snippet, related_refs)
    if rule_id in {"outline.forbidden_leak", "outline.scene_leak"}:
        return _leak_repairs(chapter_text, snippet, related_refs)
    if rule_id in {"outline.required_missing", "outline.scene_missing"}:
        return _missing_repairs(chapter_text, related_refs)
    return []


def _fact_repairs(
    chapter_text: str,
    snippet: str,
    evidence: list[dict[str, object]],
) -> list[RepairDraft]:
    if snippet == "" or chapter_text.count(snippet) != 1:
        return []
    quote = _quote(evidence, "story_event")
    if quote is None or quote.strip() == "" or quote.strip() == snippet:
        return []
    return [
        _replace(
            chapter_text,
            snippet,
            quote.strip(),
            "建议用已确认事实的原文替换这句正文。作者可以改措辞后再采纳。",
            prompt_version=REPAIR_RULE_VERSION,
            provider_mode="rule",
        )
    ]


def _repeat_repairs(chapter_text: str, snippet: str) -> list[RepairDraft]:
    if snippet == "":
        return []
    doubled = f"{snippet}\n\n{snippet}"
    if chapter_text.count(doubled) != 1:
        return []
    after = chapter_text.replace(doubled, snippet, 1)
    return [
        RepairDraft(
            apply_mode="replace_selection",
            applicable=True,
            original_snippet=doubled,
            replacement_text=snippet,
            rationale=_reason("建议删掉后一处重复段落，保留前一处。"),
            diff_preview=text_diff(chapter_text, after),
            prompt_version=REPAIR_RULE_VERSION,
            provider_mode="rule",
        )
    ]


def _punctuation_repairs(chapter_text: str, snippet: str) -> list[RepairDraft]:
    if snippet == "" or chapter_text.count(snippet) != 1:
        return []
    replacement = snippet
    for bad, good in (("。。", "。"), ("，，", "，"), ("！！", "！"), ("？？", "？")):
        replacement = replacement.replace(bad, good)
    if replacement == snippet:
        return []
    return [
        _replace(
            chapter_text,
            snippet,
            replacement,
            "建议把连续的重复标点收成一个。",
            prompt_version=REPAIR_RULE_VERSION,
            provider_mode="rule",
        )
    ]


def _name_repairs(
    chapter_text: str,
    snippet: str,
    related_refs: list[dict[str, object]],
) -> list[RepairDraft]:
    if snippet == "" or chapter_text.count(snippet) != 1:
        return []
    canonical = _label(related_refs, "entity")
    matched = _CALLED.search(snippet)
    if canonical is None or matched is None:
        return []
    called = matched.group(2)
    if called == canonical or called not in snippet:
        return []
    replacement = snippet.replace(called, canonical, 1)
    if replacement == snippet:
        return []
    return [
        _replace(
            chapter_text,
            snippet,
            replacement,
            f"建议把「{called}」改成设定里的「{canonical}」。如果这是新的别名，请改设定而不是正文。",
            prompt_version=REPAIR_RULE_VERSION,
            provider_mode="rule",
        )
    ]


def _leak_repairs(
    chapter_text: str,
    snippet: str,
    related_refs: list[dict[str, object]],
) -> list[RepairDraft]:
    phrase = _label(related_refs, "outline") or _label(related_refs, "scene")
    if snippet == "" or phrase is None or chapter_text.count(snippet) != 1 or phrase not in snippet:
        return []
    replacement = snippet.replace(phrase, "……", 1)
    if replacement == snippet:
        return []
    return [
        _replace(
            chapter_text,
            snippet,
            replacement,
            f"建议先隐去「{phrase}」。这不是判定剧情错误，只是按已确认大纲给出的一种写法。",
            prompt_version=REPAIR_RULE_VERSION,
            provider_mode="rule",
        )
    ]


def _missing_repairs(
    chapter_text: str,
    related_refs: list[dict[str, object]],
) -> list[RepairDraft]:
    phrase = _label(related_refs, "outline") or _label(related_refs, "scene")
    if phrase is None:
        return []
    return [
        _append(
            chapter_text,
            phrase,
            "建议把大纲里的这句要求补到章末，方便作者再改成叙述。没有把它写成已经发生的事实。",
            prompt_version=REPAIR_RULE_VERSION,
            provider_mode="rule",
        )
    ]


def _replace(
    chapter_text: str,
    snippet: str,
    replacement: str,
    rationale: str,
    *,
    prompt_version: str,
    provider_mode: str,
) -> RepairDraft:
    after = chapter_text.replace(snippet, replacement.strip(), 1)
    return RepairDraft(
        apply_mode="replace_selection",
        applicable=True,
        original_snippet=snippet,
        replacement_text=replacement.strip(),
        rationale=_reason(rationale),
        diff_preview=text_diff(chapter_text, after),
        prompt_version=prompt_version,
        provider_mode=provider_mode,
    )


def _append(
    chapter_text: str,
    replacement: str,
    rationale: str,
    *,
    prompt_version: str,
    provider_mode: str,
) -> RepairDraft:
    cleaned = replacement.strip()
    after = cleaned if chapter_text.strip() == "" else f"{chapter_text}\n\n{cleaned}"
    return RepairDraft(
        apply_mode="append",
        applicable=True,
        original_snippet="",
        replacement_text=cleaned,
        rationale=_reason(rationale),
        diff_preview=text_diff(chapter_text, after),
        prompt_version=prompt_version,
        provider_mode=provider_mode,
    )


def _manual(snippet: str, rationale: str) -> RepairDraft:
    return RepairDraft(
        apply_mode="replace_selection",
        applicable=False,
        original_snippet=snippet,
        replacement_text="",
        rationale=_reason(rationale),
        diff_preview="",
        prompt_version=REPAIR_RULE_VERSION,
        provider_mode="rule",
    )


def _reason(text: str) -> str:
    body = text.strip()
    if _NO_AUTO not in body:
        body = f"{body}{_NO_AUTO}"
    return body[:800]


def text_diff(before: str, after: str) -> str:
    if before == after:
        return "（正文没有变化）"
    preview = "\n".join(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile="当前正文",
            tofile="建议正文",
            lineterm="",
        )
    )
    if len(preview) > 8000:
        return preview[:8000] + "\n…（差异已截断）"
    return preview


def _quote(evidence: list[dict[str, object]], kind: str) -> str | None:
    for item in evidence:
        if item.get("kind") != kind:
            continue
        quote = item.get("quote")
        if isinstance(quote, str) and quote.strip():
            return quote.strip()
    return None


def _label(related_refs: list[dict[str, object]], kind: str) -> str | None:
    for item in related_refs:
        if item.get("kind") != kind:
            continue
        label = item.get("label")
        if isinstance(label, str) and label.strip():
            return label.strip()
    return None
