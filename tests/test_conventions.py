from cardpack.cardspec import Card
from cardpack.conventions import (
    analyze_conventions,
    build_convention_lines,
    build_example_dialogue_sample,
)


def _card(**overrides):
    defaults = dict(name="Aria", description="An elf ranger.", first_mes="Hello.", mes_example="")
    defaults.update(overrides)
    return Card(**defaults)


def _corpus_with_full_conventions(n=5):
    return [
        _card(
            name=f"C{i}",
            first_mes='*She looks up from her drink.* "You\'re late."\n\nThe tavern is loud tonight.',
            mes_example='<START>\n{{user}}: Hi\n{{char}}: *nods* "Evening."',
        )
        for i in range(n)
    ]


def test_detects_start_marker_and_turn_lines():
    conv = analyze_conventions(_corpus_with_full_conventions())
    assert conv["cards_with_example"] == 5
    assert conv["start_marker"] == 5
    assert conv["turn_prefixed_example"] == 5
    assert conv["median_example_turns"] == 2


def test_detects_placeholders_asterisks_and_quotes():
    conv = analyze_conventions(_corpus_with_full_conventions())
    assert conv["char_placeholder"] == 5
    assert conv["user_placeholder"] == 5
    assert conv["asterisk_action"] == 5
    assert conv["quoted_speech"] == 5


def test_convention_lines_mention_the_dominant_conventions():
    lines = build_convention_lines(analyze_conventions(_corpus_with_full_conventions()))
    joined = "\n".join(lines)
    assert "<START>" in joined
    assert "{{user}}:" in joined and "{{char}}:" in joined
    assert "asterisk" in joined.lower()
    assert "100%" in joined


def test_minority_conventions_are_not_reported():
    # 1 of 5 cards uses <START>; that must NOT become "how this corpus does it".
    cards = [_card(name="A", mes_example="<START>\n{{user}}: Hi\n{{char}}: Yo")]
    cards += [_card(name=f"B{i}", mes_example="{{user}}: Hi\n{{char}}: Yo") for i in range(4)]
    joined = "\n".join(build_convention_lines(analyze_conventions(cards)))
    assert "<START>" not in joined
    # ...but the turn-line convention IS unanimous here and should appear.
    assert "{{char}}:" in joined


def test_tiny_corpus_reports_nothing():
    # Two cards is not enough to assert a house style, even if unanimous.
    cards = [_card(name=f"C{i}", mes_example="<START>\n{{user}}: Hi\n{{char}}: Yo") for i in range(2)]
    assert build_convention_lines(analyze_conventions(cards)) == []


def test_corpus_with_no_conventions_reports_nothing_structural():
    cards = [_card(name=f"C{i}", first_mes="Just plain prose.", mes_example="Plain prose example.") for i in range(5)]
    joined = "\n".join(build_convention_lines(analyze_conventions(cards)))
    assert "<START>" not in joined
    assert "asterisk" not in joined.lower()


def test_example_sample_mirrors_detected_conventions():
    sample = build_example_dialogue_sample(analyze_conventions(_corpus_with_full_conventions()))
    assert sample.startswith("<START>")
    assert "{{user}}:" in sample
    assert "{{char}}:" in sample
    assert "*" in sample  # asterisk action included since the corpus uses them


def test_example_sample_omits_start_when_corpus_does_not_use_it():
    cards = [_card(name=f"C{i}", mes_example="{{user}}: Hi\n{{char}}: Yo") for i in range(5)]
    sample = build_example_dialogue_sample(analyze_conventions(cards))
    assert "<START>" not in sample
    assert "{{user}}:" in sample


def test_example_sample_falls_back_to_generic_without_turn_convention():
    cards = [_card(name=f"C{i}", mes_example="Some freeform example text.") for i in range(5)]
    sample = build_example_dialogue_sample(analyze_conventions(cards))
    assert "{{user}}:" not in sample
    assert sample.startswith("<")  # the generic angle-bracket placeholder


def test_empty_corpus_is_safe():
    conv = analyze_conventions([])
    assert conv["total_cards"] == 0
    assert build_convention_lines(conv) == []
    assert build_example_dialogue_sample(conv)
