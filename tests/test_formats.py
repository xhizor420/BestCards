from cardpack.cardspec import parse_card_payload
from cardpack.formats import to_compact, to_json, to_markdown
from cardpack.png_chunks import read_text_chunks
from tests.conftest import b64_json, build_png, card_v2_payload


def _sample_card(**overrides):
    png = build_png([("tEXt", "chara", b64_json(card_v2_payload(**overrides)))])
    card = parse_card_payload(read_text_chunks(png))
    card.source_file = "sample.png"
    return card


def test_markdown_contains_key_fields_and_truncates_by_default():
    card = _sample_card(mes_example="x" * 2000)
    out = to_markdown([card], full=False, max_chars=100)
    assert "Aria" in out
    assert "wandering elf ranger" in out
    assert "[truncated]" in out
    assert "x" * 2000 not in out


def test_markdown_full_mode_includes_everything_untruncated():
    card = _sample_card(mes_example="x" * 2000)
    out = to_markdown([card], full=True, max_chars=100)
    assert "x" * 2000 in out
    assert "[truncated]" not in out


def test_compact_is_smaller_than_markdown_for_same_card():
    card = _sample_card()
    md = to_markdown([card], full=True, max_chars=None)
    compact = to_compact([card], full=True, max_chars=None)
    assert len(compact) < len(md)


def test_compact_smaller_than_json_for_same_data():
    card = _sample_card()
    compact = to_compact([card], full=False, max_chars=600)
    as_json = to_json([card], full=True)
    assert len(compact) < len(as_json)


def test_json_roundtrip_has_expected_shape():
    card = _sample_card()
    out = to_json([card], full=True)
    assert '"name": "Aria"' in out
    assert '"count": 1' in out
