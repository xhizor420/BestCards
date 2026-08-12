from cardpack.cardspec import parse_card_payload
from cardpack.formats import estimate_export, to_compact, to_json, to_markdown
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


def test_estimate_export_reports_total_and_per_card_tokens():
    small = _sample_card(name="Small", description="short")
    big = _sample_card(name="Big", description="x" * 5000)
    result = estimate_export([small, big], format="compact", full=False, max_chars=600)

    assert result["total_tokens"] > 0
    assert len(result["cards"]) == 2
    assert result["cards"][0]["name"] == "Small"
    assert result["cards"][1]["name"] == "Big"
    # The truncated-but-longer description should still cost more tokens
    # than the short one, even after both are capped at max_chars.
    assert result["cards"][1]["tokens"] > result["cards"][0]["tokens"]
    # Per-card tokens are each card's own section, not shared preamble, so
    # they should sum to comfortably less than the full export's total.
    assert sum(c["tokens"] for c in result["cards"]) < result["total_tokens"]


def test_estimate_export_rejects_unknown_format():
    card = _sample_card()
    try:
        estimate_export([card], format="xml")
        assert False, "expected ValueError"
    except ValueError:
        pass
