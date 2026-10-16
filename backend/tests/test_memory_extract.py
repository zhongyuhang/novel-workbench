"""Mock analyzer and model payload parsing never create formal memory."""

from app.services.memory_extract import extract_from_chapter, parse_analysis_output


def test_mock_extractor_quotes_the_chapter_and_marks_guesses() -> None:
    text = "林晚说道：“夜里城门已经关了。”疑似沈照。"
    drafts = extract_from_chapter(text)

    confirmed = [item for item in drafts if item.payload.get("name") == "林晚"]
    guessed = [item for item in drafts if item.payload.get("name") == "沈照"]
    assert confirmed
    assert confirmed[0].proposal_type == "entity_create"
    assert confirmed[0].certainty == "confirmed"
    assert confirmed[0].evidence_quote in text
    assert confirmed[0].evidence_in_source is True
    assert guessed
    assert guessed[0].certainty == "uncertain"
    assert guessed[0].evidence_quote == ""
    assert guessed[0].evidence_in_source is False
    assert any(item.proposal_type == "chapter_summary" for item in drafts)


def test_model_claim_without_source_quote_is_downgraded() -> None:
    raw = """
    {"proposals":[{"proposal_type":"entity_create","certainty":"confirmed",
    "evidence_quote":"我其实是皇子","payload":{"entity_type":"character","name":"沈照",
    "aliases":[],"profile":{},"status":"active"}}]}
    """
    drafts = parse_analysis_output(raw, "林晚说道：城门关了。")

    assert len(drafts) == 1
    assert drafts[0].certainty == "uncertain"
    assert drafts[0].evidence_in_source is False
    assert drafts[0].payload["name"] == "沈照"


def test_empty_chapter_produces_no_proposals() -> None:
    assert extract_from_chapter("  \n") == []
