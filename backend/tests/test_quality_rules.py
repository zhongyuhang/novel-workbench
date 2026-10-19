"""Offline quality rules: positive, negative, and undetermined cases."""

import json
from pathlib import Path

from app.services.quality_rules import (
    ChapterMaterial,
    EventMaterial,
    OutlineMaterial,
    QualityMaterials,
    RelationMaterial,
    StateMaterial,
    materials_from_mapping,
    model_findings_from_payload,
    run_rules,
)

FIXTURE = Path(__file__).parent / "fixtures" / "eval" / "quality_samples.json"


def test_eval_samples_cover_positive_negative_and_undetermined() -> None:
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(cases, list)
    expects = {case["expect"] for case in cases}
    assert expects == {"issue", "none", "undetermined"}

    for case in cases:
        assert isinstance(case, dict)
        first = run_rules(materials_from_mapping(case))
        second = run_rules(materials_from_mapping(case))
        assert [item.fingerprint_key for item in first] == [item.fingerprint_key for item in second]
        for item in first:
            assert "性格不合理" not in item.suggested_action
            assert "剧情存在逻辑错误" not in item.suggested_action
            assert "不会自动修改正文或正式记忆" in item.suggested_action
            if item.evidence_status == "insufficient":
                assert "证据不足" in item.suggested_action
            else:
                assert item.evidence
        if case["expect"] == "none":
            assert first == []
            continue
        matched = [
            item
            for item in first
            if item.issue_type == case["issue_type"]
            and item.evidence_status == case["evidence_status"]
        ]
        assert matched, case["id"]


def test_parsed_validity_overlap_is_suspected_and_separate_intervals_are_not() -> None:
    overlap = _states(
        ("第1天", "第5天", "京城"),
        ("第4天", "第6天", "江南"),
    )
    separate = _states(
        ("第1天", "第2天", "京城"),
        ("第3天", "第4天", "江南"),
    )
    overlap_findings = run_rules(overlap)
    separate_findings = run_rules(separate)
    assert any(item.rule_id == "time.validity_overlap" for item in overlap_findings)
    assert overlap_findings[0].evidence_status == "sufficient"
    assert separate_findings == []


def test_event_order_uses_story_time_not_chapter_order_alone() -> None:
    materials = QualityMaterials(
        chapters=(
            ChapterMaterial("c1", "前", 0, 1, "阿宁第三天才动身。"),
            ChapterMaterial("c2", "后", 1, 1, "阿宁第一天已经到了。"),
        ),
        events=(
            EventMaterial("e1", "c1", "动身", "第三天才动身", "第3天", ("阿宁",), 1),
            EventMaterial("e2", "c2", "到达", "第一天已经到了", "第1天", ("阿宁",), 1),
        ),
        states=(),
        relations=(),
        outlines=(),
        scenes=(),
        foreshadowing=(),
        entities=(),
    )
    findings = run_rules(materials)
    assert any(item.rule_id == "time.event_order" for item in findings)
    assert findings[0].chapter_id == "c2"


def test_relation_negation_is_suspected_without_judging_character() -> None:
    materials = QualityMaterials(
        chapters=(ChapterMaterial("c1", "本章", 0, 1, "阿宁不是周伯的师父。"),),
        events=(),
        states=(),
        relations=(RelationMaterial("r1", "阿宁", "周伯", "师父", "拜师", "c1", 1),),
        outlines=(),
        scenes=(),
        foreshadowing=(),
        entities=(),
    )
    findings = run_rules(materials)
    assert len(findings) == 1
    assert findings[0].issue_type == "character_continuity"
    assert "性格不合理" not in findings[0].suggested_action
    assert "关系" in findings[0].suggested_action


def test_vague_outline_is_undetermined() -> None:
    materials = QualityMaterials(
        chapters=(ChapterMaterial("c1", "本章", 0, 1, "他走在街上。"),),
        events=(),
        states=(),
        relations=(),
        outlines=(OutlineMaterial("o1", "c1", "推进", None, None),),
        scenes=(),
        foreshadowing=(),
        entities=(),
    )
    findings = run_rules(materials)
    assert len(findings) == 1
    assert findings[0].evidence_status == "insufficient"
    assert "证据不足" in findings[0].suggested_action


def test_model_hint_without_a_known_quote_stays_insufficient() -> None:
    chapter = ChapterMaterial("c1", "本章", 0, 2, "阿宁是右撇子。")
    findings = model_findings_from_payload(
        [
            {
                "issue_type": "character_continuity",
                "manuscript_snippet": "阿宁是右撇子。",
                "source_quote": "",
                "severity": "high",
                "confidence": 0.9,
                "suggested_action": "人物性格不合理，剧情存在逻辑错误。",
            }
        ],
        chapter=chapter,
        known_quotes={},
    )
    assert len(findings) == 1
    assert findings[0].evidence_status == "insufficient"
    assert "证据不足" in findings[0].suggested_action
    assert "性格不合理" not in findings[0].suggested_action
    assert "剧情存在逻辑错误" not in findings[0].suggested_action


def test_model_hint_drops_snippets_that_are_not_in_the_chapter() -> None:
    chapter = ChapterMaterial("c1", "本章", 0, 1, "阿宁推门进来。")
    assert (
        model_findings_from_payload(
            [
                {
                    "issue_type": "fact_continuity",
                    "manuscript_snippet": "这句不在正文里",
                    "source_quote": "",
                    "severity": "low",
                    "confidence": 0.4,
                    "suggested_action": "核对",
                }
            ],
            chapter=chapter,
            known_quotes={},
        )
        == []
    )


def _states(
    earlier: tuple[str, str, str],
    later: tuple[str, str, str],
) -> QualityMaterials:
    return QualityMaterials(
        chapters=(
            ChapterMaterial("c1", "前", 0, 1, "前文。"),
            ChapterMaterial("c2", "后", 1, 1, "后文。"),
        ),
        events=(),
        states=(
            StateMaterial(
                "s1",
                "ent",
                "阿宁",
                "c1",
                (("location", earlier[2]),),
                "人在京城",
                earlier[0],
                earlier[1],
                1,
            ),
            StateMaterial(
                "s2",
                "ent",
                "阿宁",
                "c2",
                (("location", later[2]),),
                "到了江南",
                later[0],
                later[1],
                1,
            ),
        ),
        relations=(),
        outlines=(),
        scenes=(),
        foreshadowing=(),
        entities=(),
    )
