from cardpack.stats import TOKENIZER_PRESETS, count_tokens


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
