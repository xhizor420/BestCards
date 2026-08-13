import pytest

from cardpack.cardspec import CardExtractionError, parse_card_payload
from cardpack.png_chunks import read_text_chunks
from tests.conftest import b64_json, build_png, card_v2_payload


def test_parses_v2_card():
    png = build_png([("tEXt", "chara", b64_json(card_v2_payload()))])
    card = parse_card_payload(read_text_chunks(png))
    assert card.name == "Aria"
    assert card.spec_version == "2.0"
    assert card.source_keyword == "chara"
    assert "guarded" in card.personality
    assert card.tags == ["fantasy", "adventure"]
    assert len(card.alternate_greetings) == 2
    assert len(card.lorebook_entries) == 0


def test_parses_v1_unwrapped_card():
    raw = {
        "name": "OldCard",
        "description": "A legacy V1 card with no spec wrapper.",
        "first_mes": "Hello there.",
    }
    png = build_png([("tEXt", "chara", b64_json(raw))])
    card = parse_card_payload(read_text_chunks(png))
    assert card.name == "OldCard"
    assert card.spec_version == "1.0"


def test_prefers_ccv3_over_chara_when_both_present():
    v2 = card_v2_payload(name="V2Name")
    v3 = card_v2_payload(name="V3Name")
    v3["spec"] = "chara_card_v3"
    v3["spec_version"] = "3.0"
    png = build_png([("tEXt", "chara", b64_json(v2)), ("tEXt", "ccv3", b64_json(v3))])
    card = parse_card_payload(read_text_chunks(png))
    assert card.name == "V3Name"
    assert card.spec_version == "3.0"
    assert card.source_keyword == "ccv3"


def test_extracts_lorebook_entries():
    payload = card_v2_payload(
        character_book={
            "entries": [
                {"keys": ["sword"], "content": "A magic sword.", "comment": "weapon"},
                {"keys": ["castle"], "content": "The ruined castle.", "comment": ""},
            ]
        }
    )
    png = build_png([("tEXt", "chara", b64_json(payload))])
    card = parse_card_payload(read_text_chunks(png))
    assert len(card.lorebook_entries) == 2
    assert card.lorebook_entries[0]["keys"] == ["sword"]


def test_raises_when_no_card_data_present():
    png = build_png([("tEXt", "Software", "not a card")])
    with pytest.raises(CardExtractionError):
        parse_card_payload(read_text_chunks(png))


def test_raises_on_garbage_base64():
    png = build_png([("tEXt", "chara", "%%%not-valid-base64-or-json%%%")])
    with pytest.raises(CardExtractionError):
        parse_card_payload(read_text_chunks(png))


def test_bloat_is_stripped_from_fields_at_extraction_time():
    huge_b64 = "A" * 3000
    payload = card_v2_payload(
        description=f'A wandering elf ranger. <img src="data:image/png;base64,{huge_b64}"> Very brave.',
        mes_example="Aria smiles.\n————————————\n{{user}}: Hi",
    )
    png = build_png([("tEXt", "chara", b64_json(payload))])
    card = parse_card_payload(read_text_chunks(png))

    assert "base64" not in card.description
    assert "A wandering elf ranger." in card.description
    assert "Very brave." in card.description
    assert "————" not in card.mes_example
    assert card.bloat_chars_removed > 2900  # mostly the embedded image data


def test_clean_card_reports_zero_bloat_removed():
    card = parse_card_payload(read_text_chunks(build_png([("tEXt", "chara", b64_json(card_v2_payload()))])))
    assert card.bloat_chars_removed == 0
