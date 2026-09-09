import json
import re

from cardpack.cardspec import Card, parse_card_payload
from cardpack.formats import (
    card_to_dict,
    estimate_export,
    normalize_extra_fields,
    to_compact,
    to_json,
    to_markdown,
)
from cardpack.png_chunks import read_text_chunks
from cardpack.stats import count_tokens
from tests.conftest import b64_json, build_png, card_v2_payload


def _sample_card(**overrides):
    png = build_png([("tEXt", "chara", b64_json(card_v2_payload(**overrides)))])
    card = parse_card_payload(read_text_chunks(png))
    card.source_file = "sample.png"
    return card


def test_markdown_contains_key_fields_and_truncates_beyond_the_full_tier():
    # full_top=0 disables the untrimmed tier, so ordinary truncation applies.
    card = _sample_card(mes_example="x" * 2000)
    out = to_markdown([card], full=False, max_chars=100, full_top=0)
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
    # Measured over a real-sized corpus: both formats carry the same fixed
    # preamble/template overhead, so the per-card encoding is what the
    # claim is actually about and a single card can't show it.
    cards = [_sample_card(name=f"C{i:02}") for i in range(20)]
    compact = to_compact(cards, full=False, max_chars=600)
    as_json = to_json(cards, full=True)
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


def _card_with_all_optional_fields():
    return _sample_card(
        tags=["fantasy", "adventure"],
        system_prompt="SYSPROMPT_MARKER stay in character.",
        post_history_instructions="POSTHISTORY_MARKER never break character.",
        alternate_greetings=["ALTGREETING_MARKER one.", "ALTGREETING_MARKER two."],
        character_book={
            "entries": [
                {"keys": ["sword"], "content": "LOREBOOK_MARKER the Sunblade.", "comment": ""},
                {"keys": ["castle"], "content": "LOREBOOK_MARKER Castle Myrr.", "comment": ""},
            ]
        },
    )


# Regression: opting a field in must yield its CONTENT, not a bare count,
# and must not silently require --full as well. Previously `compact`
# dropped system_prompt/post_history_instructions entirely unless full
# was set, and both formats showed only counts for alt_greetings/lorebook
# - so ticking those boxes in the UI looked like it did nothing.
def test_opted_in_optional_fields_render_content_without_full():
    card = _card_with_all_optional_fields()
    for writer in (to_markdown, to_compact):
        out = writer([card], extra_fields="all", full=False)
        body = out.split("REQUIRED RESPONSE FORMAT")[0]
        assert "SYSPROMPT_MARKER" in body, writer.__name__
        assert "POSTHISTORY_MARKER" in body, writer.__name__
        assert "LOREBOOK_MARKER the Sunblade." in body, writer.__name__
        assert "LOREBOOK_MARKER Castle Myrr." in body, writer.__name__
        assert "ALTGREETING_MARKER one." in body, writer.__name__
        assert "ALTGREETING_MARKER two." in body, writer.__name__
        assert "fantasy" in body, writer.__name__


def test_opted_in_optional_fields_render_content_in_json_without_full():
    payload = json.loads(to_json([_card_with_all_optional_fields()], extra_fields="all", full=False))
    card = payload["cards"][0]
    assert "SYSPROMPT_MARKER" in card["system_prompt"]
    assert "POSTHISTORY_MARKER" in card["post_history_instructions"]
    assert card["tags"] == ["fantasy", "adventure"]
    # Types must stay stable regardless of `full` - these used to collapse
    # to bare ints, which corrupted Card.from_dict() round-trips.
    assert isinstance(card["alternate_greetings"], list)
    assert isinstance(card["lorebook_entries"], list)
    assert isinstance(card["mes_example"], str)
    assert "LOREBOOK_MARKER" in card["lorebook_entries"][0]["content"]


def test_card_dict_round_trips_without_type_corruption():
    original = _card_with_all_optional_fields()
    for full in (True, False):
        restored = Card.from_dict(card_to_dict(original, full=full, max_chars=600, extra_fields="all"))
        assert isinstance(restored.alternate_greetings, list)
        assert isinstance(restored.lorebook_entries, list)
        assert isinstance(restored.mes_example, str)
        assert restored.tags == ["fantasy", "adventure"]
        assert "SYSPROMPT_MARKER" in restored.system_prompt


def test_not_opted_in_optional_fields_stay_out():
    card = _card_with_all_optional_fields()
    for writer in (to_markdown, to_compact):
        body = writer([card], extra_fields="none", full=True).split("REQUIRED RESPONSE FORMAT")[0]
        assert "SYSPROMPT_MARKER" not in body
        assert "POSTHISTORY_MARKER" not in body
        assert "LOREBOOK_MARKER" not in body
        assert "ALTGREETING_MARKER" not in body


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
    assert "writing the new character" in md.lower()
    for label in ("Name:", "Description:", "Personality:", "Scenario:", "First Message:", "Example Dialogue:"):
        assert label in md
    # It must be the true tail of the file, not buried mid-document - the
    # revision instruction is the last thing in the template.
    assert md.strip().endswith("revision.")

    compact = to_compact([card])
    assert "writing the new character" in compact.lower()
    assert compact.strip().endswith("changed one.")

    payload = json.loads(to_json([card]))
    assert payload["response_template"]["fields"] == expected_fields
    # response_template comes after "cards" (only trailing metadata like
    # tokens/token_method follows it), not buried before the reference data.
    keys = list(payload.keys())
    assert keys.index("response_template") > keys.index("cards")


def test_response_template_asks_for_one_clean_copy_pasteable_block():
    card = _sample_card()
    for out in (to_markdown([card]), to_compact([card])):
        low = out.lower()
        assert "one clean block" in low
        assert "no commentary" in low
        assert "copied and pasted" in low or "copy-paste" in low

    payload = json.loads(to_json([card]))
    instruction = payload["response_template"]["instruction"].lower()
    assert "one clean block" in instruction
    assert "no commentary" in instruction


def test_response_template_asks_for_revision_loop_with_full_card_resend():
    card = _sample_card()
    # Whitespace normalized so these don't break on line-wrap position.
    for out in (to_markdown([card]), to_compact([card])):
        flat = " ".join(out.lower().split())
        assert "changes are wanted" in flat
        assert "full card again" in flat
        assert "not just the changed one" in flat

    payload = json.loads(to_json([card]))
    instruction = payload["response_template"]["instruction"].lower()
    assert "changes are wanted" in instruction
    assert "full card again" in instruction


def test_response_template_guides_toward_real_content_without_hard_mandates():
    # Deliberately guidance, not commands: the corpus is the authority, so
    # the template points at it ("what these cards actually do") and asks
    # for real content rather than issuing prohibitions.
    card = _sample_card()
    for out in (to_markdown([card]), to_compact([card])):
        flat = " ".join(out.lower().split())
        assert "guided by the cards above" in flat
        assert "where those cards show a clear convention, follow it" in flat
        assert "rather than a description of it" in flat
        assert "blank line between" in flat
        # The restrictive phrasing this replaced should be gone.
        assert "do not skip, rename, merge, or reorder" not in flat
        assert "a thin sketch is a failed answer" not in flat


def test_template_marks_unused_fields_optional_rather_than_required():
    # A corpus that never fills `personality`/`mes_example` shouldn't be
    # told those slots are mandatory - it should be told where the corpus
    # actually keeps that content, and that filling them is optional.
    dossier = "<A>\n>Appearance\n+ tall\n>Personality\n+ guarded\n</A>"
    cards = [
        Card(name=f"C{i}", description=dossier, first_mes="Hi there.", scenario="A tavern.", spec_version="2.0")
        for i in range(5)
    ]
    for out in (to_markdown(cards), to_compact(cards)):
        flat = " ".join(out.lower().split())
        assert "optional" in flat
        # Says where the corpus really keeps personality.
        assert "`>personality` section inside description" in flat


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


# --- tiered depth --------------------------------------------------------
# A flat cap forces a false choice between structure (learned from a few
# COMPLETE cards) and breadth (many partial ones). The top-ranked cards
# are rendered whole; the rest are trimmed, so a 100+ card corpus stays
# affordable without hiding the structure it's meant to teach.

def _numbered_cards(n, body_chars=3000):
    return [
        _sample_card(name=f"C{i:02}", description=f"Card {i} " + ("y" * body_chars))
        for i in range(n)
    ]


def test_first_cards_are_untrimmed_and_later_ones_are_trimmed():
    out = to_markdown(_numbered_cards(6), full=False, max_chars=100, full_top=3)
    # The template brackets the cards - it is emitted before them and
    # again after - so the card body is the slice between the two copies.
    body = out.split("WRITING THE NEW CHARACTER")[1]
    # Anchored to line start: the template mentions '"## Card i/N" headers'
    # inline, which a plain substring split would count as a card.
    per_card = re.split(r"^## Card ", body, flags=re.M)[1:]
    assert len(per_card) == 6
    for section in per_card[:3]:
        assert "[truncated]" not in section, "a top-tier card was trimmed"
    for section in per_card[3:]:
        assert "[truncated]" in section, "a lower-tier card was not trimmed"


def test_full_top_applies_to_compact_too():
    out = to_compact(_numbered_cards(4), full=False, max_chars=100, full_top=2)
    body = out.split("=== WRITING THE NEW CHARACTER")[1]
    per_card = re.split(r"^=== CARD ", body, flags=re.M)[1:]
    assert [("[truncated]" in s) for s in per_card] == [False, False, True, True]


def test_full_flag_still_overrides_every_tier():
    out = to_markdown(_numbered_cards(6), full=True, max_chars=100, full_top=2)
    assert "[truncated]" not in out


def test_json_gives_full_text_to_the_top_tier_only():
    payload = json.loads(to_json(_numbered_cards(4), full=False, max_chars=100, full_top=2))
    lens = [len(c["description"]) for c in payload["cards"]]
    assert lens[0] > 1000 and lens[1] > 1000, "top tier should keep full description"
    assert lens[2] < 200 and lens[3] < 200, "lower tier should be trimmed"


def test_stats_cover_every_card_not_just_the_full_tier():
    # The corpus is still a database of all N cards - trimming for display
    # must not shrink what the stats and conventions are measured over.
    out = to_markdown(_numbered_cards(6), full=False, max_chars=100, full_top=2)
    assert "- Cards: 6" in out
    assert "description 6/6" in out


def test_estimate_matches_the_tiered_export():
    cards = _numbered_cards(6)
    result = estimate_export(cards, format="md", full=False, max_chars=100, full_top=2)
    # The untrimmed top-tier cards must cost visibly more than trimmed ones.
    assert result["cards"][0]["tokens"] > result["cards"][5]["tokens"] * 3


def test_response_template_brackets_the_cards_at_both_ends():
    # A large export rarely reaches a model whole - it gets truncated or
    # chunk-retrieved - and instructions living only after the last card
    # are the first thing lost. So they open the file as well.
    out = to_markdown(_numbered_cards(4))
    assert out.count("WRITING THE NEW CHARACTER") == 2
    first = out.index("WRITING THE NEW CHARACTER")
    last = out.rindex("WRITING THE NEW CHARACTER")
    first_card = re.search(r"^## Card 1/4", out, re.M).start()
    last_card = re.search(r"^## Card 4/4", out, re.M).start()
    assert first < first_card < last_card < last

    compact = to_compact(_numbered_cards(4))
    assert compact.count("WRITING THE NEW CHARACTER") == 2


def test_preamble_points_at_both_copies_of_the_template():
    out = to_markdown(_numbered_cards(3))
    assert "both immediately below and again at the very end" in out
    assert "repeated verbatim at the end of this file" in out


def test_estimate_reports_a_context_warning_only_when_oversized():
    small = estimate_export(_numbered_cards(2), format="md")
    assert small["context_warning"] == []


# --- per-field caps -------------------------------------------------------
# On a real 33-card corpus, descriptions were 73% of the export and first
# messages 21%. Descriptions are what teach structure; 33 complete opening
# messages teach little more than 10 do. The tier control couldn't separate
# them - a card was wholly full or wholly trimmed - so one field needs its
# own ceiling.


def _long_card():
    return _sample_card(description="D" * 5000, first_mes="F" * 5000)


def test_field_cap_trims_only_that_field():
    out = to_markdown([_long_card()], full=True, field_caps={"first_mes": 500})
    assert "D" * 5000 in out, "description must be untouched"
    assert "F" * 5000 not in out
    assert "F" * 500 in out


def test_field_cap_applies_even_inside_the_untrimmed_top_tier():
    # The whole point: --full / the full-depth tier must not exempt it.
    for kwargs in ({"full": True}, {"full": False, "full_top": 5}):
        out = to_markdown([_long_card()], field_caps={"first_mes": 400}, **kwargs)
        assert "F" * 5000 not in out
        assert "D" * 5000 in out


def test_field_cap_never_loosens_an_existing_cap():
    # A 2000-char ceiling must not un-trim a field the 300-char tier cap
    # already trimmed - the tighter of the two wins.
    out = to_markdown([_long_card()], full=False, max_chars=300, full_top=0,
                      field_caps={"first_mes": 2000})
    assert "F" * 400 not in out


def test_field_cap_works_in_compact_and_json():
    compact = to_compact([_long_card()], full=True, field_caps={"first_mes": 500})
    assert "D" * 5000 in compact and "F" * 5000 not in compact

    payload = json.loads(to_json([_long_card()], full=True, field_caps={"first_mes": 500}))
    card = payload["cards"][0]
    assert len(card["description"]) >= 5000
    assert "F" * 5000 not in card["first_mes"]


def test_field_cap_is_reflected_in_the_token_estimate():
    cards = [_long_card()]
    uncapped = estimate_export(cards, format="md", full=True)
    capped = estimate_export(cards, format="md", full=True, field_caps={"first_mes": 300})
    assert capped["total_tokens"] < uncapped["total_tokens"]
    assert capped["cards"][0]["tokens"] < uncapped["cards"][0]["tokens"]


def test_normalize_field_caps_accepts_both_shapes_and_drops_junk():
    from cardpack.formats import normalize_field_caps

    assert normalize_field_caps({"first_mes": 1200}) == {"first_mes": 1200}
    assert normalize_field_caps(["first_mes=1200", "scenario=300"]) == {
        "first_mes": 1200,
        "scenario": 300,
    }
    assert normalize_field_caps(["nosuchfield=100"]) == {}   # unknown name
    assert normalize_field_caps(["first_mes=abc"]) == {}     # unparseable
    assert normalize_field_caps(["first_mes=0"]) == {}       # non-positive
    assert normalize_field_caps(["first_mes"]) == {}         # missing "="
    assert normalize_field_caps(None) == {}
