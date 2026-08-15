from cardpack.cardspec import Card
from cardpack.conventions import (
    analyze_conventions,
    build_absent_core_fields,
    build_cast_note,
    build_convention_lines,
    build_coverage_notes,
    build_description_skeleton,
    build_example_dialogue_sample,
    build_style_sections,
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
    assert "Structured dossier" in joined
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
    assert "Structured dossier" not in joined


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
    assert "Structured dossier" in joined
    # Reported with its real count and share, so a minority reads as one.
    assert "3 of 10 cards (30%)" in joined
    # ...and the skeleton keeps the real structure rather than falling back.
    skeleton = build_description_skeleton(analyze_conventions(_mixed_corpus(3, 7)))
    assert ">Appearance" in skeleton


def test_dominant_structure_reports_its_real_share():
    joined = "\n".join(build_convention_lines(analyze_conventions(_mixed_corpus(8, 2))))
    assert "Structured dossier" in joined
    assert "8 of 10 cards (80%)" in joined


def test_well_attested_structure_survives_corpus_growth():
    # The real failure this guards: a coherent dossier style held by a
    # fixed set of cards kept sliding toward the share threshold purely
    # because unrelated cards were added around it (37% at 30 cards, 26%
    # at 43). Those 8 cards are just as instructive at 8/100 as at 8/20.
    for prose in (12, 32, 92):
        joined = "\n".join(build_convention_lines(analyze_conventions(_mixed_corpus(8, prose))))
        assert "Structured dossier" in joined, f"lost the structure at 8/{8 + prose}"
        assert f"8 of {8 + prose} cards" in joined


def test_rare_structure_stays_unreported():
    # 2 cards, 10%: below both the share bar and the absolute-count floor.
    joined = "\n".join(build_convention_lines(analyze_conventions(_mixed_corpus(2, 18))))
    assert "Structured dossier" not in joined


def test_bullet_line_has_no_dangling_section_reference():
    # "+ " bullets present but section headers too rare to report: the
    # bullet line must not say "inside those sections" when no section
    # line was emitted above it.
    cards = [_card(name=f"C{i}", description="+ a fact\n+ another fact") for i in range(5)]
    joined = "\n".join(build_convention_lines(analyze_conventions(cards)))
    assert "`+ ` bullet" in joined
    assert "those sections" not in joined


# --- shared conventions vs structural approaches -------------------------
# Near-universal habits and genuinely optional structure are different
# kinds of guidance. Flattening them hides which is which; splitting them
# lets the shared ones be followed without thought while the structural
# ones stay a real choice - led by the most organised, since every card
# in a curated corpus already cleared the quality bar.

def test_near_universal_habits_are_separated_from_structural_choices():
    cards = _mixed_corpus(3, 7)
    for c in cards:
        c.first_mes = '*She looks up.* "Hey."'  # asterisks + quotes in all 10
    sections = build_style_sections(analyze_conventions(cards))

    shared = "\n".join(sections["shared"])
    approaches = "\n".join(sections["approaches"])
    assert "asterisks" in shared and "10 of 10" in shared
    assert "double quotes" in shared
    # The 3-of-10 dossier is a choice, not a shared habit.
    assert "Structured dossier" in approaches
    assert "Structured dossier" not in shared


def test_structural_approaches_lead_with_the_most_organised():
    sections = build_style_sections(analyze_conventions(_mixed_corpus(3, 7)))
    assert sections["approaches"], "expected structural approaches"
    assert "Structured dossier" in sections["approaches"][0]
    assert "recommended default" in sections["approaches"][0]


def test_scale_notes_are_kept_out_of_both_rule_groups():
    sections = build_style_sections(analyze_conventions(_dossier_corpus()))
    scale = "\n".join(sections["scale"])
    assert "median" in scale
    assert "median" not in "\n".join(sections["shared"])
    assert "median" not in "\n".join(sections["approaches"])


def test_flat_convention_lines_still_include_every_group():
    conv = analyze_conventions(_dossier_corpus())
    sections = build_style_sections(conv)
    flat = build_convention_lines(conv)
    assert len(flat) == len(sections["shared"]) + len(sections["approaches"]) + len(sections["scale"])


def test_optional_touches_are_not_listed_as_structural_alternatives():
    # A backtick-thoughts habit is not an alternative to a dossier
    # structure - listing it under "default to the first one" would be
    # nonsense, so independent formatting habits get their own bucket.
    cards = _mixed_corpus(3, 7)
    for c in cards[:3]:  # 3/10 = 30%, over the reporting bar but well under universal
        c.first_mes = "She thinks `maybe later` and shrugs."
    sections = build_style_sections(analyze_conventions(cards))
    approaches = "\n".join(sections["approaches"])
    touches = "\n".join(sections["touches"])
    assert "Structured dossier" in approaches
    assert "backticks" not in approaches
    assert "backticks" in touches


# --- solo vs group cast ---------------------------------------------------
# The corpus deliberately holds both shapes. A card is multi-character when
# it has an <NPC> block or a name joining several characters; group cards
# are longer because they hold more characters, which is the format working.


def test_detects_group_cards_by_npc_block_and_by_name():
    cards = [
        _card(name="Aria"),
        _card(name="Susan & Sera"),
        _card(name="Kate and Andrew"),
        _card(name="The Hale Family"),
        _card(name="Rowan", description="<Rowan>\n>Appearance\n+ tall\n</Rowan>\n<NPC>\n<Mira> her sister </Mira>\n</NPC>"),
    ]
    conv = analyze_conventions(cards)
    assert conv["total_cards"] == 5
    assert conv["multi_character_cards"] == 4


def test_solo_names_are_not_mistaken_for_groups():
    # A one-word name, and one that merely contains the letters "and".
    cards = [_card(name="Aria"), _card(name="Alexander"), _card(name="Sandy")]
    assert analyze_conventions(cards)["multi_character_cards"] == 0


def test_cast_note_names_both_shapes_and_defends_group_length():
    cards = _dossier_corpus() + [_card(name="Susan & Sera", description=_DOSSIER)]
    note = "\n".join(build_cast_note(analyze_conventions(cards)))
    assert "single character" in note
    assert "cast" in note
    # Length is explained, never prescribed - a group card is long because
    # it holds a group, so neither shape should be nudged toward the other.
    assert "don't pad" in note
    assert "Follow whichever matches" in note


def test_cast_note_is_silent_when_the_corpus_is_all_one_shape():
    assert build_cast_note(analyze_conventions(_dossier_corpus())) == []
    groups = [_card(name=f"A{i} & B{i}") for i in range(5)]
    assert build_cast_note(analyze_conventions(groups)) == []
