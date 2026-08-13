import json
import re

from cardpack.cardspec import parse_card_payload
from cardpack.formats import estimate_export, normalize_extra_fields, to_compact, to_json, to_markdown
from cardpack.png_chunks import read_text_chunks
from cardpack.stats import count_tokens
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


def test_creator_notes_excluded_by_default_in_every_format():
    card = _sample_card(creator_notes="Loved for its banter and slow burn.")
    for writer in (to_markdown, to_compact):
        out = writer([card])
        assert "banter" not in out
    out = to_json([card], full=True)
    assert "banter" not in out
    assert "creator_notes" not in out


def test_creator_notes_included_when_field_requested():
    card = _sample_card(creator_notes="Loved for its banter and slow burn.")
    for writer in (to_markdown, to_compact):
        out = writer([card], extra_fields={"tags", "creator_notes"})
        assert "banter" in out
    out = to_json([card], full=True, extra_fields={"creator_notes"})
    assert "banter" in out


def test_tags_included_by_default_but_removable():
    card = _sample_card(tags=["fantasy", "adventure"])
    assert "fantasy" in to_compact([card])
    assert "fantasy" not in to_compact([card], extra_fields="none")


def test_normalize_extra_fields_handles_all_none_and_junk():
    assert normalize_extra_fields("all") == {
        "tags",
        "creator_notes",
        "system_prompt",
        "post_history_instructions",
        "alt_greetings",
        "lorebook",
    }
    assert normalize_extra_fields("none") == frozenset()
    assert normalize_extra_fields("") == frozenset()
    assert normalize_extra_fields("tags, bogus_field") == {"tags"}
    assert normalize_extra_fields(["tags", "creator_notes"]) == {"tags", "creator_notes"}


def test_count_tokens_labels_method_and_falls_back_without_tiktoken():
    tc = count_tokens("Hello world, this is a short test sentence.")
    assert tc.count > 0
    assert tc.method  # always labeled, never silent about which method produced it
    # In this sandboxed test environment tiktoken's data file can't be
    # fetched, so we should reliably be on the heuristic fallback here -
    # this also guards against the heuristic path silently breaking.
    if not tc.exact:
        assert "heuristic" in tc.method


# A model reading a batch of cards would sometimes echo the compact
# format's old single/double-letter labels (N:, D:, P:, EX:, ...) back in
# its own response instead of writing a normal character - and a human
# skimming the file couldn't tell what half of them meant either. Labels
# must stay spelled-out words, not cryptic codes, and the file should
# explicitly tell the model not to reuse its structure.
def test_compact_format_uses_spelled_out_labels_not_cryptic_codes():
    card = _sample_card(
        tags=["fantasy"], creator_notes="popular for its banter", mes_example="<START>\n{{user}}: hi"
    )
    out = to_compact([card], extra_fields="all", full=True)
    assert "Name: Aria" in out
    assert "Desc:" in out
    assert "Personality:" in out
    assert "Scenario:" in out
    assert "Greeting:" in out
    assert "Example:" in out
    assert "Notes:" in out
    assert "Tags:" in out
    # None of the old one/two-letter label prefixes should appear at the
    # start of a line anymore.
    for line in out.splitlines():
        assert not re.match(r"^(N|T|D|P|S|G|EX|CN|AG|LB|SYS|PHI):", line), f"cryptic label leaked back in: {line!r}"


def test_response_template_tells_model_not_to_reuse_corpus_wrapper():
    # The multi-card "=== CARD i/N ===" / "## Card i/N" wrapper exists to
    # hold many reference cards in one file - a model echoing that same
    # wrapper back for its single new character was the original bug this
    # is guarding against.
    card = _sample_card()
    for out in (to_markdown([card]), to_compact([card])):
        low = out.lower()
        assert "card i/n" in low or "=== card i/n ===" in low
    out_json = to_json([card])
    assert "response_template" in out_json
    assert '"fields"' in out_json


def test_response_template_gives_the_six_field_schema_and_is_last():
    card = _sample_card()
    expected_fields = ["name", "description", "personality", "scenario", "first_mes", "mes_example"]

    md = to_markdown([card])
    assert "when you respond" in md.lower()
    for label in ("Name:", "Description:", "Personality:", "Scenario:", "First Message:", "Example Dialogue:"):
        assert label in md
    # It must be the true tail of the file, not buried mid-document.
    assert md.strip().endswith("voice>")

    compact = to_compact([card])
    assert "when you respond" in compact.lower()
    assert compact.strip().endswith("card.")

    payload = json.loads(to_json([card]))
    assert payload["response_template"]["fields"] == expected_fields
    # response_template comes after "cards" (only trailing metadata like
    # tokens/token_method follows it), not buried before the reference data.
    keys = list(payload.keys())
    assert keys.index("response_template") > keys.index("cards")


def test_preamble_warns_against_averaging_into_a_composite():
    card = _sample_card()
    for out in (to_markdown([card]), to_compact([card]), to_json([card])):
        low = out.lower()
        assert "do not average" in low or "not average" in low
        assert "curated" in low or "high-quality" in low


def test_preamble_says_length_tracks_complexity_not_a_target():
    # Complexity (a single character vs. several) legitimately varies a
    # card's natural length - the file must say so explicitly and must
    # NOT tell the model to hit any particular length, so a genuinely
    # complex new character isn't squeezed to match the corpus.
    card = _sample_card()
    for out in (to_markdown([card]), to_compact([card]), to_json([card])):
        low = out.lower()
        assert "complexity" in low
        assert "not a target" in low or "as a target" in low
        assert "several characters" in low or "multi-character" in low


def test_description_length_stats_line_ties_range_to_complexity():
    cards = [_sample_card(name="Simple", description="short"), _sample_card(name="Complex", description="x" * 3000)]
    out = to_markdown(cards)
    assert "complexity" in out.lower()
    assert "not a target" in out.lower()
