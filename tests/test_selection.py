from cardpack.cardspec import Card
from cardpack.selection import apply_pins, exemplar_names, rank_cards, score_card, select_best

_DOSSIER = """<Aria>
>Appearance
+ 165cm, dark hair.
>Personality
+ Guarded but warm.
>Behavior & Interests
+ Reads constantly.
>Backstory
+ Coastal town.
>Speech
+ Dry, clipped.
>Sex & Intimacy
+ Slow to trust.
</Aria>"""


def _card(**kw):
    base = dict(name="X", description="", first_mes="", scenario="", mes_example="", spec_version="2.0")
    base.update(kw)
    return Card(**base)


def test_structure_outweighs_raw_length():
    # The whole point of the corpus is to convey how cards are ORGANISED,
    # so a compact well-sectioned dossier must outrank a longer wall of
    # prose - otherwise --best would surface the least instructive cards.
    structured = _card(name="Structured", description=_DOSSIER)
    sprawling = _card(name="Sprawling", description="Just prose. " * 2000)
    assert len(sprawling.description) > len(structured.description) * 5
    assert score_card(structured) > score_card(sprawling)


def test_more_sections_scores_higher():
    two = _card(description="<A>\n>Appearance\n+ x\n>Personality\n+ y\n</A>")
    six = _card(description=_DOSSIER)
    assert score_card(six) > score_card(two)


def test_completeness_adds_to_the_score():
    bare = _card(description=_DOSSIER)
    complete = _card(
        description=_DOSSIER,
        scenario="A tavern.",
        mes_example="{{user}}: hi\n{{char}}: hey",
        tags=["fantasy"],
        alternate_greetings=["alt"],
    )
    assert score_card(complete) > score_card(bare)


def test_rank_puts_the_most_instructive_first():
    cards = [
        _card(name="Thin", description="Short."),
        _card(name="Rich", description=_DOSSIER, scenario="A tavern.", tags=["x"]),
        _card(name="Middling", description="<A>\n>Appearance\n+ x\n</A>"),
    ]
    assert [c.name for c in rank_cards(cards)] == ["Rich", "Middling", "Thin"]


def test_ranking_is_stable_for_equal_scores():
    a = _card(name="Bravo", description=_DOSSIER)
    b = _card(name="Alpha", description=_DOSSIER)
    assert score_card(a) == score_card(b)
    assert [c.name for c in rank_cards([a, b])] == ["Alpha", "Bravo"]  # tie broken by name


def test_select_best_takes_the_top_n_only():
    cards = [_card(name=f"C{i}", description=_DOSSIER if i < 3 else "Short.") for i in range(10)]
    picked = select_best(cards, 3)
    assert len(picked) == 3
    assert all(c.description == _DOSSIER for c in picked)


def test_select_best_without_a_limit_returns_everything_ranked():
    cards = [_card(name=f"C{i}", description="Short.") for i in range(4)]
    assert len(select_best(cards, None)) == 4
    assert len(select_best(cards, 0)) == 4


def test_exemplar_names_point_at_the_clearest_examples():
    cards = [
        _card(name="Rich", description=_DOSSIER, scenario="s"),
        _card(name="AlsoRich", description=_DOSSIER),
        _card(name="Thin", description="Short."),
    ]
    names = exemplar_names(cards, n=2)
    assert names == ["Rich", "AlsoRich"]


def test_exemplar_names_skip_worthless_cards():
    assert exemplar_names([_card(name="Empty")], n=3) == []


# --- pinning --------------------------------------------------------------
# Group cards are longer with more sections because they hold more
# characters, so they tend to lead the full-depth tier - correct behaviour,
# not a defect. What the score can't know is whether the reader is about to
# write a solo card or a group one, so the curator gets the override.

def _named(name, path):
    return _card(name=name, description=_DOSSIER, source_file=path)


def test_pins_move_cards_to_the_front():
    cards = [_named("A", "a.png"), _named("B", "b.png"), _named("C", "c.png")]
    assert [c.name for c in apply_pins(cards, ["c.png"])] == ["C", "A", "B"]


def test_pins_preserve_relative_order_within_each_group():
    cards = [_named(n, f"{n}.png") for n in "ABCD"]
    assert [c.name for c in apply_pins(cards, ["D.png", "B.png"])] == ["B", "D", "A", "C"]


def test_no_pins_leaves_the_ranking_untouched():
    cards = [_named(n, f"{n}.png") for n in "ABC"]
    assert apply_pins(cards, None) == cards
    assert apply_pins(cards, []) == cards


def test_unknown_pins_are_ignored():
    cards = [_named("A", "a.png"), _named("B", "b.png")]
    assert [c.name for c in apply_pins(cards, ["missing.png"])] == ["A", "B"]


# --- corpus consistency ---------------------------------------------------
# More cards is not monotonically better. On a real 113-card corpus the top
# 50 agreed on one structure 98% of the time - so the export stated it as
# the house style - while all 113 agreed only 43%, demoting the very same
# instruction to "one option among several".

from cardpack.selection import consistency_note, structure_consistency  # noqa: E402


def _plain(name):
    return _card(name=name, description="Just a plain prose description, no sections.")


def test_a_consistent_corpus_is_reported_as_teaching_one_style():
    stats = structure_consistency([_named(f"C{i}", f"{i}.png") for i in range(25)])
    assert stats["share"] == 1.0
    assert stats["stable"] is True
    note = " ".join(consistency_note(stats))
    assert "house style" in note
    assert "single clear pattern" in note


def test_a_diluted_corpus_is_called_out_with_the_agreeing_prefix():
    # 25 structured cards followed by 25 unstructured ones: exactly the
    # shape of a corpus that grew past its own consistency.
    cards = [_named(f"S{i}", f"s{i}.png") for i in range(25)] + [_plain(f"P{i}") for i in range(25)]
    stats = structure_consistency(cards)
    assert stats["share"] == 0.5
    # The LARGEST prefix still clearing the bar, not the run of structured
    # cards: 25 of the first 31 is 81%, still the house style; 25 of 32 is
    # 78% and no longer is. A few stragglers inside the set are fine.
    assert stats["agreeing_prefix"] == 31
    note = " ".join(consistency_note(stats))
    assert "one approach among several" in note
    assert "top 31 cards do agree" in note


def test_a_small_corpus_is_flagged_as_not_yet_stable():
    # Below the stability floor one card's own headings can be reported as
    # the house style, so the advice is "add more", not "trim".
    stats = structure_consistency([_named(f"C{i}", f"{i}.png") for i in range(8)])
    assert stats["stable"] is False
    note = " ".join(consistency_note(stats))
    assert "unstable" in note
    assert "a few more comparable cards" in note


def test_consistency_ignores_cards_with_no_description():
    cards = [_named("A", "a.png"), _card(name="Empty", description="")]
    assert structure_consistency(cards)["cards"] == 1


def test_consistency_is_safe_on_an_empty_corpus():
    stats = structure_consistency([])
    assert stats == {"cards": 0, "structured": 0, "share": 0.0, "agreeing_prefix": 0, "stable": False}
    assert consistency_note(stats) == []
