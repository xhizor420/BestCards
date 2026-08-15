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
# Ranking has a real blind spot: group cards are longer with more sections,
# so they crowd the full-depth tier even when the reader wants one
# character. The curator knows their corpus better than the score does.

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
