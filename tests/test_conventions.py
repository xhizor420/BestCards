from cardpack.cardspec import Card
from cardpack.conventions import (
    analyze_conventions,
    build_absent_core_fields,
    build_convention_lines,
    build_coverage_notes,
    build_description_skeleton,
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


# --- document structure inside `description` -----------------------------
# Real high-quality cards pack a structured dossier into `description`
# (">Appearance" headers, "+ " bullets, "<Name>" wrappers) and leave the
# spec's own `personality`/`mes_example` fields empty. Rendering
# "Description: <appearance, background, key facts>" as a one-liner taught
# models to throw all that away.

_DOSSIER = """<Aria>
>Appearance
+ 165cm, dark hair, green eyes.
+ Wears oversized shirts.
>Personality
+ Introverted but teasing once comfortable.
>Backstory
+ Grew up in a coastal town.
</Aria>"""


def _dossier_corpus(n=5):
    return [_card(name=f"C{i}", description=_DOSSIER, first_mes="Hello there.") for i in range(n)]


def test_detects_section_headers_bullets_and_xml_blocks():
    conv = analyze_conventions(_dossier_corpus())
    assert conv["section_header_cards"] == 5
    assert conv["plus_bullet_cards"] == 5
    assert conv["xml_block_cards"] == 5
    names = [n for n, _c, _p in conv["section_names"]]
    assert names == ["Appearance", "Personality", "Backstory"]  # corpus order, not frequency order


def test_convention_lines_describe_the_dossier_structure():
    joined = "\n".join(build_convention_lines(analyze_conventions(_dossier_corpus())))
    assert "STRUCTURED DOSSIER" in joined
    assert ">Appearance" in joined and ">Backstory" in joined
    assert "+ " in joined
    assert "<Name>" in joined


def test_description_skeleton_mirrors_real_sections():
    skeleton = build_description_skeleton(analyze_conventions(_dossier_corpus()))
    assert skeleton.startswith("<Name>")
    for section in (">Appearance", ">Personality", ">Backstory"):
        assert section in skeleton
    assert "+ <specific, concrete detail>" in skeleton
    assert skeleton.rstrip().endswith("</Name>")


def test_description_skeleton_stays_generic_without_structure():
    plain = [_card(name=f"C{i}", description="Just a plain prose description.") for i in range(5)]
    skeleton = build_description_skeleton(analyze_conventions(plain))
    assert ">Appearance" not in skeleton
    assert skeleton.startswith("<")


def test_minority_dossier_structure_is_not_reported():
    cards = [_card(name="A", description=_DOSSIER)]
    cards += [_card(name=f"B{i}", description="Plain prose only.") for i in range(4)]
    joined = "\n".join(build_convention_lines(analyze_conventions(cards)))
    assert "STRUCTURED DOSSIER" not in joined


# --- field coverage ------------------------------------------------------

def test_field_coverage_counts_populated_fields():
    cards = _dossier_corpus()  # description + first_mes only
    coverage = analyze_conventions(cards)["field_coverage"]
    assert coverage["description"] == 5
    assert coverage["first_mes"] == 5
    assert coverage["personality"] == 0
    assert coverage["mes_example"] == 0
    assert coverage["tags"] == 0


def test_coverage_notes_flag_fields_the_corpus_cannot_teach():
    notes = "\n".join(build_coverage_notes(analyze_conventions(_dossier_corpus())))
    assert "Personality" in notes and "0/5" in notes
    assert "Example Dialogue" in notes
    assert "tags" in notes


def test_absent_core_fields_lists_empty_template_labels():
    absent = build_absent_core_fields(analyze_conventions(_dossier_corpus()))
    assert "Personality" in absent
    assert "Example Dialogue" in absent
    assert "Description" not in absent


def test_no_coverage_notes_when_every_field_is_populated():
    cards = _corpus_with_full_conventions()
    for c in cards:
        c.personality = "Curious and guarded."
        c.scenario = "A rain-soaked tavern."
        c.tags = ["fantasy"]
    assert build_coverage_notes(analyze_conventions(cards)) == []
    assert build_absent_core_fields(analyze_conventions(cards)) == []


# --- reporting tiers -----------------------------------------------------
# A diverse corpus often has NO majority structure. A strict 50% rule threw
# a coherent 37% dossier pattern away entirely and fell back to a useless
# one-line Description placeholder - losing exactly the structure worth
# mirroring. Substantial minorities are surfaced, honestly qualified.

def _mixed_corpus(dossier_count, plain_count):
    cards = [_card(name=f"D{i}", description=_DOSSIER) for i in range(dossier_count)]
    cards += [_card(name=f"P{i}", description="Just a plain prose description.") for i in range(plain_count)]
    return cards


def test_substantial_minority_structure_is_offered_not_discarded():
    # 3/10 = 30%: under the majority bar, over the "worth offering" bar.
    joined = "\n".join(build_convention_lines(analyze_conventions(_mixed_corpus(3, 7))))
    assert "STRUCTURED DOSSIER" in joined
    assert "A good number of these cards" in joined
    assert "Most of these cards build" not in joined
    # ...and the skeleton keeps the real structure rather than falling back.
    skeleton = build_description_skeleton(analyze_conventions(_mixed_corpus(3, 7)))
    assert ">Appearance" in skeleton


def test_dominant_structure_is_labelled_most():
    joined = "\n".join(build_convention_lines(analyze_conventions(_mixed_corpus(8, 2))))
    assert "Most of these cards build" in joined
    assert "A good number" not in joined


def test_rare_structure_stays_unreported():
    # 2/20 = 10%: below the "worth offering" bar entirely.
    joined = "\n".join(build_convention_lines(analyze_conventions(_mixed_corpus(2, 18))))
    assert "STRUCTURED DOSSIER" not in joined


def test_qualifier_never_produces_a_doubled_of():
    for dossier in (3, 8):
        joined = "\n".join(build_convention_lines(analyze_conventions(_mixed_corpus(dossier, 10 - dossier))))
        assert " of of " not in joined


def test_bullet_line_has_no_dangling_section_reference():
    # "+ " bullets present but section headers too rare to report: the
    # bullet line must not say "inside those sections" when no section
    # line was emitted above it.
    cards = [_card(name=f"C{i}", description="+ a fact\n+ another fact") for i in range(5)]
    joined = "\n".join(build_convention_lines(analyze_conventions(cards)))
    assert "`+ ` bullet" in joined
    assert "those sections" not in joined
