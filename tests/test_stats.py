from cardpack.cardspec import Card
from cardpack.stats import TOKENIZER_PRESETS, build_corpus_stats, count_tokens, format_stats_block


def test_heuristic_is_the_default_and_never_touches_network():
    tc = count_tokens("Hello world, this is a short test sentence.")
    assert tc.count > 0
    assert tc.exact is False
    assert tc.method == "heuristic (~0.75 tok/word)"


def test_explicit_heuristic_request_matches_default():
    text = "Some sample card description text for token counting."
    assert count_tokens(text, "heuristic") == count_tokens(text)


def test_unrecognized_tokenizer_name_falls_back_silently_to_heuristic():
    tc = count_tokens("some text", "not-a-real-tokenizer-name")
    assert tc.exact is False
    assert tc.method == "heuristic (~0.75 tok/word)"


def test_gpt_preset_falls_back_with_explanation_when_unavailable(monkeypatch):
    # In CI/sandboxed environments tiktoken's one-time data fetch is often
    # blocked; on a normal machine with internet this preset would return
    # exact=True instead. Either way the result must be internally
    # consistent: exact implies a non-heuristic method label, and vice versa.
    tc = count_tokens("A reasonably long sentence to tokenize for the test.", "gpt")
    assert tc.count > 0
    if tc.exact:
        assert tc.method.startswith("tiktoken")
    else:
        assert "heuristic" in tc.method
        assert "cl100k_base" in tc.method or "tiktoken" in tc.method


def test_hf_presets_fall_back_with_explanation_when_unavailable():
    for name in ("deepseek", "glm"):
        tc = count_tokens("A reasonably long sentence to tokenize for the test.", name)
        assert tc.count > 0
        if tc.exact:
            assert TOKENIZER_PRESETS[name]["key"] in tc.method
        else:
            assert "heuristic" in tc.method
            assert TOKENIZER_PRESETS[name]["key"] in tc.method  # names the repo it tried


def test_custom_hf_repo_id_is_accepted_as_a_tokenizer_name():
    tc = count_tokens("some text", "some-org/some-model")
    assert tc.count > 0
    if not tc.exact:
        assert "some-org/some-model" in tc.method


def test_token_count_is_deterministic_for_repeat_calls():
    text = "Repeated sentence to make sure caching doesn't change the count."
    a = count_tokens(text, "deepseek")
    b = count_tokens(text, "deepseek")
    assert a == b


def _card(**overrides):
    defaults = dict(name="Aria", description="A wandering elf ranger.", spec_version="2.0")
    defaults.update(overrides)
    return Card(**defaults)


def test_corpus_stats_reports_description_length_range():
    stats = build_corpus_stats([_card(description="short"), _card(description="x" * 500)])
    assert stats["min_description_chars"] == 5
    assert stats["max_description_chars"] == 500
    assert stats["avg_description_chars"] > 0


def test_corpus_stats_aggregates_bloat_removed():
    cards = [_card(name="A", bloat_chars_removed=100), _card(name="B", bloat_chars_removed=4000), _card(name="C")]
    stats = build_corpus_stats(cards)
    assert stats["total_bloat_chars_removed"] == 4100
    assert stats["cards_with_bloat"] == 2
    assert stats["top_bloat_cards"][0] == ("B", 4000)


def test_corpus_stats_zero_bloat_when_no_cards_have_any():
    stats = build_corpus_stats([_card(), _card(name="Zed")])
    assert stats["total_bloat_chars_removed"] == 0
    assert stats["cards_with_bloat"] == 0


def test_format_stats_block_mentions_bloat_savings_and_range():
    cards = [_card(description="x" * 500, bloat_chars_removed=4000)]
    stats = build_corpus_stats(cards)
    block = format_stats_block(stats)
    assert "stripped" in block.lower()
    assert "4,000" in block or "4000" in block
    assert "500" in block  # description length range mentions the max

    compact_block = format_stats_block(stats, compact=True)
    assert "bloat_stripped" in compact_block


def test_format_stats_block_omits_bloat_line_when_nothing_removed():
    stats = build_corpus_stats([_card()])
    block = format_stats_block(stats)
    assert "stripped" not in block.lower()


def test_stats_report_the_solo_group_mix():
    # Both shapes belong in the corpus, so the summary names the split
    # instead of treating group cards as outliers to explain away.
    cards = [_card(name="Aria"), _card(name="Zed"), _card(name="Kate & Andrew")]
    stats = build_corpus_stats(cards)
    assert stats["single_character_cards"] == 2
    assert stats["multi_character_cards"] == 1

    block = format_stats_block(stats)
    assert "2 built around a single character" in block
    assert "1 built around a group" in block
    assert "cast=solo:2,group:1" in format_stats_block(stats, compact=True)


def test_stats_skip_the_cast_line_when_every_card_is_the_same_shape():
    stats = build_corpus_stats([_card(name="Aria"), _card(name="Zed")])
    assert "built around a group" not in format_stats_block(stats)
    assert "cast=" not in format_stats_block(stats, compact=True)


# --- context budget -------------------------------------------------------
# A corpus of full-length dossiers outgrows what any current model can read
# in one prompt, and the failure is quiet: the model answers from whatever
# fragment reached it, which looks like it ignoring the instructions.


def test_no_context_warning_for_an_export_that_fits():
    from cardpack.stats import CONTEXT_BUDGET_TOKENS, context_warning, context_warning_ui

    assert context_warning(CONTEXT_BUDGET_TOKENS, card_count=113) == []
    assert context_warning_ui(1000, card_count=5) == []


def test_context_warning_states_the_overage_and_the_levers():
    from cardpack.stats import context_warning

    notes = "\n".join(context_warning(394_000, card_count=113))
    assert "394,000 tokens" in notes
    assert "3.1×" in notes
    assert "--full-top" in notes
    assert "--best 40" in notes  # offered only when there are cards to drop


def test_context_warning_omits_the_drop_cards_lever_for_a_small_corpus():
    from cardpack.stats import context_warning

    notes = "\n".join(context_warning(400_000, card_count=12))
    assert "--best" not in notes
    assert "--full-top" in notes


def test_ui_warning_names_ui_controls_not_cli_flags():
    from cardpack.stats import context_warning_ui

    notes = "\n".join(context_warning_ui(394_000, card_count=113))
    assert "--" not in notes
    assert "Show best N cards in full" in notes
