"""Detect the writing conventions a corpus of cards actually uses.

"Write it the way the strongest cards above wrote theirs" is not an
actionable instruction - a model handed 100 cards and a vague style note
will produce something structurally unlike the corpus. So instead of
describing the fields abstractly, measure what the corpus actually does
and state it as explicit instructions with the real percentages behind
them.

Two families of convention matter, and the second was the one that made
real-world output come back "half-assed":

1. Inline formatting - {{char}}/{{user}} placeholders, `<START>` markers,
   `{{user}}:`/`{{char}}:` turn prefixes, *asterisk actions*, "quoted
   speech", `backtick thoughts`.

2. Document structure INSIDE a field. Real high-quality cards routinely
   pack an entire structured dossier into `description` - `>Appearance`,
   `>Personality`, `>Backstory` section headers with `+ ` bullet lines,
   sometimes wrapped in `<Name>...</Name>` blocks with a separate `<NPC>`
   block for side characters - while leaving the spec's own `personality`
   field completely empty. A template that renders "Description: <appearance,
   background, key facts>" as a one-liner teaches a model to throw all of
   that away, which is exactly what it then does.

Field coverage is measured too, and matters just as much: a corpus where
0 of 10 cards populate `mes_example` cannot teach a model to write one, so
the export says so plainly rather than demanding a field it never
demonstrates.

A convention is reported when it's either a majority (_MIN_SHARE), a
substantial share (_COMMON_SHARE), or demonstrated by enough cards in
absolute terms (_MIN_STRUCTURE_CARDS) - and never from a corpus too
small to mean anything (_MIN_CARDS). Every structural line carries its
real count and share ("11 of 43 cards (26%)"), so a minority style is
offered as a usable option without ever being dressed up as the house
style.
"""

from __future__ import annotations

import re
import statistics
from collections import defaultdict
from typing import Iterable

from .cardspec import Card

# A convention used by at least this share is reported as the dominant
# pattern - "most of these cards do X".
_MIN_SHARE = 0.5
# A convention between _COMMON_SHARE and _MIN_SHARE is a real, coherent
# minority worth offering as a strong option rather than discarding.
# A diverse corpus often has NO majority structure (30 mixed cards had the
# `>Section` dossier at 37%), and a strict majority rule would throw that
# signal away entirely and fall back to a useless one-line placeholder -
# losing exactly the structure worth mirroring.
_COMMON_SHARE = 0.25
# ...and at least this many cards must have the field at all, so tiny
# corpora don't produce confident-sounding claims from 1-2 examples.
_MIN_CARDS = 3
# An absolute floor that survives corpus growth. Share alone is fragile:
# a coherent dossier style held by 11 real cards read as 37% at 30 cards
# and 26% at 43 - not because those cards changed, but because unrelated
# cards were added around them. Dropping a structure with 11 worked
# examples in it, purely because the denominator grew, throws away the
# best material in the file. If this many cards demonstrate a structure,
# there is plenty to learn from regardless of what share of the whole
# they represent - and the wording always reports the real count AND
# share, so a minority is never dressed up as the house style.
_MIN_STRUCTURE_CARDS = 5
# At or above this share a convention isn't really a "choice" any more -
# it's simply how cards in this corpus are written, and can be followed
# without deliberation. Below it, competing approaches genuinely coexist
# and should be presented as options rather than a single house style.
_UNIVERSAL_SHARE = 0.8

_CHAR_PLACEHOLDER_RE = re.compile(r"\{\{char\}\}", re.IGNORECASE)
_USER_PLACEHOLDER_RE = re.compile(r"\{\{user\}\}", re.IGNORECASE)
_START_MARKER_RE = re.compile(r"<START>", re.IGNORECASE)
# An asterisk-wrapped span on one line: *she smiles*. Requires non-space
# right after the opening star so a lone "*" or a bullet list doesn't count.
_ASTERISK_ACTION_RE = re.compile(r"\*\S[^*\n]*\*")
_QUOTED_SPEECH_RE = re.compile(r"[\"“][^\"”\n]{3,}[\"”]")
_BACKTICK_THOUGHT_RE = re.compile(r"`[^`\n]{3,}`")
# Turn lines like `{{user}}: hello` / `{{char}}: hi` at the start of a line.
_TURN_LINE_RE = re.compile(r"^\s*\{\{(?:user|char)\}\}\s*:", re.IGNORECASE | re.MULTILINE)

# Document-structure conventions inside a field.
# ">Appearance", ">Behavior & Interests", ">Sex & Intimacy", ">Powers/Skills"
_SECTION_HEADER_RE = re.compile(r"^>[ \t]*([A-Za-z][A-Za-z0-9 &/'’\-]{2,40})[ \t]*$", re.MULTILINE)
_PLUS_BULLET_RE = re.compile(r"^\+[ \t]+\S", re.MULTILINE)
# <Audrey> ... </Audrey> style wrappers, and <NPC> side-character blocks.
_XML_BLOCK_RE = re.compile(r"<([A-Za-z][A-Za-z0-9_ ]{0,30})>")
_NPC_BLOCK_RE = re.compile(r"<NPC>", re.IGNORECASE)
# A card covering more than one character: an explicit <NPC> block, or a
# name joining several ("Susan & Sera", "Kate and Andrew", "Hero Family").
# Group cards are longer because they carry more characters - that is the
# format working as intended, not noise to correct for.
_GROUP_NAME_RE = re.compile(r"\s(?:&|\+|and)\s|,|\bfamily\b|\btwins\b|\bsisters\b|\bbrothers\b", re.IGNORECASE)
_INSTRUCTIONS_BLOCK_RE = re.compile(r"<instructions>", re.IGNORECASE)
# A leading status/header line like "11:12 PM | August 6 | 11°C Raining | Apartment Hallway"
_STATUS_LINE_RE = re.compile(r"^[^\n|]{1,60}\|[^\n|]{1,60}\|[^\n]{1,120}$")

# The six fields the export is built around, in template order.
CORE_FIELDS = ("name", "description", "personality", "scenario", "first_mes", "mes_example")
_CORE_FIELD_LABELS = {
    "name": "Name",
    "description": "Description",
    "personality": "Personality",
    "scenario": "Scenario",
    "first_mes": "First Message",
    "mes_example": "Example Dialogue",
}


def is_multi_character(card: Card) -> bool:
    """True when a card carries a cast rather than one character.

    Detected two ways: an explicit `<NPC>` block in the description, or a
    name that joins several ("Susan & Sera", "Kate and Andrew", "The Hale
    Family"). Both are conservative - a group card written as plain prose
    under a single name reads as solo here, which is the safe direction to
    be wrong in.

    This exists to REPORT the corpus's mix, never to filter it. Group
    cards are longer because they carry more characters; that is the
    format doing its job, and both kinds are worth keeping in the export
    so a solo request and a group request each have something to follow.
    """
    return bool(_NPC_BLOCK_RE.search(card.description) or _GROUP_NAME_RE.search(card.name or ""))


def _share(matching: int, total: int) -> float:
    return (matching / total) if total else 0.0


def _dominant(matching: int, total: int) -> bool:
    return total >= _MIN_CARDS and _share(matching, total) >= _MIN_SHARE


def _common(matching: int, total: int) -> bool:
    """Dominant, or a substantial coherent minority worth offering.

    Passes on share OR on absolute count, so a well-attested structure
    isn't discarded just because the corpus grew around it.
    """
    if total < _MIN_CARDS:
        return False
    return _share(matching, total) >= _COMMON_SHARE or matching >= _MIN_STRUCTURE_CARDS


def _count_share(matching: int, total: int) -> str:
    """"11 of 43 cards (26%)" - the real count alongside the share, so a
    minority reads as the minority it is."""
    return f"{matching} of {total} cards ({_pct(matching, total)}%)"


def _cards(n: int) -> str:
    return "card" if n == 1 else "cards"


def _verb(n: int) -> str:
    return "gives" if n == 1 else "give"


def _pct(matching: int, total: int) -> int:
    return round(_share(matching, total) * 100)


def _first_nonempty_line(text: str) -> str:
    for line in text.split("\n"):
        if line.strip():
            return line.strip()
    return ""


def _ordered_section_names(per_card_sections: list[list[str]]) -> list[tuple[str, int, float]]:
    """Section names used by a majority of the section-using cards, ordered
    by where they typically appear (average index), so the skeleton we show
    reads in the corpus's own natural order rather than by raw frequency."""
    counts: dict[str, int] = defaultdict(int)
    positions: dict[str, list[float]] = defaultdict(list)
    for sections in per_card_sections:
        # De-duplicate within a card so a repeated header can't inflate counts.
        seen: set[str] = set()
        for idx, name in enumerate(sections):
            key = name.strip()
            if key.lower() in seen:
                continue
            seen.add(key.lower())
            counts[key] += 1
            positions[key].append(idx / max(1, len(sections) - 1) if len(sections) > 1 else 0.0)

    total = len(per_card_sections)
    common = [(name, n, statistics.mean(positions[name])) for name, n in counts.items() if _share(n, total) >= _MIN_SHARE]
    common.sort(key=lambda t: t[2])
    return common


def analyze_conventions(cards: Iterable[Card]) -> dict:
    """Measure structural/formatting conventions across the corpus.

    Returns raw counts and shares; deciding what's worth *telling* a model
    is format_conventions_block()'s job.
    """
    cards = list(cards)

    with_example = [c for c in cards if c.mes_example.strip()]
    with_first_mes = [c for c in cards if c.first_mes.strip()]
    with_description = [c for c in cards if c.description.strip()]
    with_scenario = [c for c in cards if c.scenario.strip()]
    combined_text = [
        "\n".join([c.description, c.personality, c.scenario, c.first_mes, c.mes_example]) for c in cards
    ]

    example_turn_counts = [len(_TURN_LINE_RE.findall(c.mes_example)) for c in with_example]
    example_turn_counts = [n for n in example_turn_counts if n > 0]

    first_mes_paragraphs = [len([p for p in c.first_mes.split("\n\n") if p.strip()]) for c in with_first_mes]

    # Document structure inside `description`.
    per_card_sections: list[list[str]] = []
    for c in with_description:
        found = _SECTION_HEADER_RE.findall(c.description)
        if found:
            per_card_sections.append(found)

    multi_character = sum(1 for c in cards if is_multi_character(c))

    field_coverage = {
        f: sum(1 for c in cards if str(getattr(c, f, "") or "").strip()) for f in CORE_FIELDS
    }
    field_coverage["tags"] = sum(1 for c in cards if c.tags)

    return {
        "total_cards": len(cards),
        "multi_character_cards": multi_character,
        "cards_with_example": len(with_example),
        "cards_with_first_mes": len(with_first_mes),
        "cards_with_description": len(with_description),
        "cards_with_scenario": len(with_scenario),
        "field_coverage": field_coverage,
        # inline formatting
        "char_placeholder": sum(1 for t in combined_text if _CHAR_PLACEHOLDER_RE.search(t)),
        "user_placeholder": sum(1 for t in combined_text if _USER_PLACEHOLDER_RE.search(t)),
        "start_marker": sum(1 for c in with_example if _START_MARKER_RE.search(c.mes_example)),
        "turn_prefixed_example": sum(1 for c in with_example if _TURN_LINE_RE.search(c.mes_example)),
        "median_example_turns": round(statistics.median(example_turn_counts)) if example_turn_counts else 0,
        "asterisk_action": sum(
            1
            for c in with_first_mes
            if _ASTERISK_ACTION_RE.search(c.first_mes) or _ASTERISK_ACTION_RE.search(c.mes_example)
        ),
        "quoted_speech": sum(1 for c in with_first_mes if _QUOTED_SPEECH_RE.search(c.first_mes)),
        "backtick_thoughts": sum(1 for t in combined_text if _BACKTICK_THOUGHT_RE.search(t)),
        "median_first_mes_paragraphs": round(statistics.median(first_mes_paragraphs)) if first_mes_paragraphs else 0,
        "first_mes_status_line": sum(
            1 for c in with_first_mes if _STATUS_LINE_RE.match(_first_nonempty_line(c.first_mes))
        ),
        # document structure
        "section_header_cards": len(per_card_sections),
        "section_names": _ordered_section_names(per_card_sections),
        "plus_bullet_cards": sum(1 for c in with_description if _PLUS_BULLET_RE.search(c.description)),
        "xml_block_cards": sum(1 for c in with_description if _XML_BLOCK_RE.search(c.description)),
        "npc_block_cards": sum(1 for c in with_description if _NPC_BLOCK_RE.search(c.description)),
        "scenario_instructions_cards": sum(1 for c in with_scenario if _INSTRUCTIONS_BLOCK_RE.search(c.scenario)),
        "median_description_chars": (
            round(statistics.median([len(c.description) for c in with_description])) if with_description else 0
        ),
    }


def build_style_sections(conv: dict) -> dict:
    """Split observed conventions into two honestly-labelled groups.

    Real corpora contain near-universal habits (asterisk actions, quoted
    speech, {{user}} placeholders - effectively just how cards are
    written here) sitting alongside structural choices (a `>Section`
    dossier, `+ ` bullets, `<Name>` wrappers) that only some cards make.
    Flattening both into one list buries the distinction between "this is
    simply the local convention" and "this is a deliberate way of
    organising a card".

    Crucially, share here is NOT a quality signal. This corpus is already
    curated - every card in it was picked as a good one - so a structure
    appearing in 11 of 57 cards means eleven cards that cleared the bar
    chose it, not that it's a fringe habit diluted by better
    alternatives. Low share means "less common", never "less good", and
    the templates lead with the most structured approach on exactly that
    basis rather than deferring to raw frequency.

    Three buckets, because two different things sit below universal and
    lumping them together reads badly: "approaches" are mutually
    comparable ways of ORGANISING a card (pick one), while "touches" are
    independent formatting flourishes (take any, or none). Presenting a
    backtick-thoughts habit as an alternative to a dossier structure -
    under a "default to the first one" instruction - would be nonsense.

    "shared" holds what nearly every card does, safe to just follow.
    "approaches" holds the structural options, most-organised first.
    "touches" holds optional formatting habits, each with its real count.
    """
    shared: list[str] = []
    approaches: list[str] = []
    touches: list[str] = []
    total = conv["total_cards"]
    n_example = conv["cards_with_example"]
    n_first = conv["cards_with_first_mes"]
    n_desc = conv["cards_with_description"]
    n_scenario = conv["cards_with_scenario"]

    def add(matching: int, denominator: int, text: str, *, structural: bool = False) -> None:
        """Route a line by how universal it is, and by whether it's a way
        of organising the card or an independent formatting habit."""
        line = f"- {text} [{_count_share(matching, denominator)}]"
        if _share(matching, denominator) >= _UNIVERSAL_SHARE:
            shared.append(line)
        elif structural:
            approaches.append(line)
        else:
            touches.append(line)

    # --- structural approaches to Description -------------------------
    sections_reported = _common(conv["section_header_cards"], n_desc)
    if sections_reported:
        names = [n for n, _c, _p in conv["section_names"]]
        listed = ", ".join(f"`>{n}`" for n in names) if names else "`>Appearance`, `>Personality`, ..."
        add(
            conv["section_header_cards"],
            n_desc,
            f"**Structured dossier** — build Description from `>Section` header lines rather than "
            f"prose, typically in this order: {listed}. This is the most organised approach in the "
            f"corpus and the recommended default: it's what the most thorough cards here do, and it "
            f"scales to as much detail as the character needs.",
            structural=True,
        )
    if _common(conv["plus_bullet_cards"], n_desc):
        where = "inside those sections" if sections_reported else "in Description"
        add(
            conv["plus_bullet_cards"],
            n_desc,
            f"**Bulleted facts** — write details as `+ ` bullet lines {where}, rather than "
            f"running them together as sentences.",
            structural=True,
        )
    if _common(conv["xml_block_cards"], n_desc):
        extra = ""
        if _common(conv["npc_block_cards"], n_desc):
            extra = " Side characters go in their own `<NPC>` block."
        add(
            conv["xml_block_cards"],
            n_desc,
            f"**Tagged blocks** — wrap the character's dossier in `<Name>` … `</Name>` tags.{extra}",
            structural=True,
        )
    if _common(conv["scenario_instructions_cards"], n_scenario):
        add(
            conv["scenario_instructions_cards"],
            n_scenario,
            "**Directive scenario** — write Scenario as an `<instructions>` block of explicit "
            "roleplay rules rather than prose setting.",
            structural=True,
        )

    # --- prose/formatting habits --------------------------------------
    if _common(conv["char_placeholder"], total) or _common(conv["user_placeholder"], total):
        both = _common(conv["char_placeholder"], total) and _common(conv["user_placeholder"], total)
        which = (
            "{{char}} and {{user}}"
            if both
            else ("{{char}}" if _common(conv["char_placeholder"], total) else "{{user}}")
        )
        best = max(conv["char_placeholder"], conv["user_placeholder"])
        add(best, total, f"Use the {which} placeholder(s) rather than writing names literally.")
    if _common(conv["asterisk_action"], n_first):
        add(
            conv["asterisk_action"],
            n_first,
            "Wrap actions/narration in *asterisks*, keeping speech outside them.",
        )
    if _common(conv["quoted_speech"], n_first):
        add(conv["quoted_speech"], n_first, 'Put spoken dialogue in "double quotes".')
    if _common(conv["backtick_thoughts"], total):
        add(conv["backtick_thoughts"], total, "Put inner thoughts in `backticks`.")
    if _common(conv["first_mes_status_line"], n_first):
        add(
            conv["first_mes_status_line"],
            n_first,
            "Open First Message with a pipe-separated status line, e.g. "
            "`11:12 PM | August 6 | 11°C Raining | Apartment Hallway`.",
        )
    if _common(conv["start_marker"], n_example):
        add(conv["start_marker"], n_example, "Begin Example Dialogue with a `<START>` line.")
    if _common(conv["turn_prefixed_example"], n_example):
        turns = conv["median_example_turns"]
        turn_note = f" — typically about {turns} turn lines" if turns else ""
        add(
            conv["turn_prefixed_example"],
            n_example,
            f"Write Example Dialogue as alternating `{{{{user}}}}:` / `{{{{char}}}}:` lines, one turn "
            f"per line{turn_note}.",
        )

    # Scale note: a plain observation about how much these cards contain,
    # not a target - length guidance elsewhere is explicit that complexity,
    # not a number, should drive it.
    scale: list[str] = []
    if conv["median_description_chars"] and n_desc >= _MIN_CARDS:
        scale.append(
            f"- Descriptions here are substantial — the median is about "
            f"{conv['median_description_chars']:,} characters. Whatever structure you pick, these "
            f"cards carry a lot of concrete detail."
        )
    if n_first >= _MIN_CARDS and conv["median_first_mes_paragraphs"] >= 2:
        scale.append(
            f"- First Messages run about {conv['median_first_mes_paragraphs']} paragraphs — long, "
            f"scene-setting and in-voice, not a single line."
        )

    return {"shared": shared, "approaches": approaches, "touches": touches, "scale": scale}


def build_cast_note(conv: dict) -> list[str]:
    """Tell the reader the corpus holds BOTH solo and group cards.

    Without this, a model reading 45 solo cards and 12 group ones tends to
    average them: it writes a solo card when asked for a group, or bolts a
    stray sidekick onto a solo request. Both shapes are demonstrated here
    on purpose, so name them and say to follow whichever the request asks
    for. Notably this is not a length instruction - a group card is longer
    because it carries more characters, which is the format working, not
    padding to imitate or trim.
    """
    total = conv["total_cards"]
    multi = conv["multi_character_cards"]
    if total < _MIN_CARDS or multi == 0 or multi == total:
        # Nothing to choose between - one shape, no guidance to give.
        return []

    solo = total - multi
    lines = [
        f"- This corpus demonstrates both shapes: {solo} {_cards(solo)} built around a single "
        f"character, and {multi} built around a cast. Follow whichever matches what's "
        f"being asked for — write a solo card for a solo request, a group card for a "
        f"group one — rather than splitting the difference.",
        "- Group cards run longer than solo ones here, and that's the format working: "
        "more characters means more to describe. Length follows the cast and the "
        "concept, so don't pad a solo card toward the group ones or trim a group card "
        "toward the solo ones.",
    ]
    npc = conv["npc_block_cards"]
    if npc:
        lines.append(
            f"- For side characters specifically, {npc} {_cards(npc)} here {_verb(npc)} each one "
            f"its own `<NPC>` block after the main character's dossier, written in the same "
            f"structure — that's the pattern to follow when a card needs a supporting cast."
        )
    return lines


def build_convention_lines(conv: dict) -> list[str]:
    """Flat list of every observed convention (shared habits, structural
    options, and scale notes), for consumers that want one list."""
    sections = build_style_sections(conv)
    return sections["shared"] + sections["approaches"] + sections["touches"] + sections["scale"]


def build_description_skeleton(conv: dict) -> str:
    """A concrete skeleton for the Description field mirroring the corpus's
    own section/bullet structure, or a plain placeholder when the corpus
    has no dominant structure to mirror."""
    n_desc = conv["cards_with_description"]
    if not _common(conv["section_header_cards"], n_desc):
        return "<appearance, background, key facts>"

    names = [n for n, _c, _p in conv["section_names"]] or ["Appearance", "Personality", "Backstory"]
    bullet = "+ " if _common(conv["plus_bullet_cards"], n_desc) else "- "
    uses_xml = _common(conv["xml_block_cards"], n_desc)

    lines: list[str] = []
    if uses_xml:
        lines.append("<Name>")
    for name in names:
        lines.append(f">{name}")
        lines.append(f"{bullet}<specific, concrete detail>")
        lines.append(f"{bullet}<more detail — several bullets per section>")
    if uses_xml:
        lines.append("</Name>")
        if _dominant(conv["npc_block_cards"], n_desc):
            lines.append("<NPC>")
            lines.append("<SideCharacter> <their own dossier> </SideCharacter>")
            lines.append("</NPC>")
    return "\n".join(lines)


def build_example_dialogue_sample(conv: dict) -> str:
    """A concrete, correctly-formatted Example Dialogue snippet matching
    whatever conventions this corpus actually uses - so the template can
    *show* the shape instead of describing it in the abstract, which is
    where models were producing malformed example dialogue."""
    n_example = conv["cards_with_example"]
    uses_start = _dominant(conv["start_marker"], n_example)
    uses_turns = _dominant(conv["turn_prefixed_example"], n_example)
    uses_asterisk = _dominant(conv["asterisk_action"], conv["cards_with_first_mes"])

    if not uses_turns:
        # No dominant turn convention detected - keep it generic rather
        # than inventing a house style this corpus doesn't have.
        return "<a short sample exchange showing this character's voice>"

    char_line = (
        '{{char}}: *glances up, then looks away.* "You\'re early."'
        if uses_asterisk
        else '{{char}}: "You\'re early."'
    )
    lines = ["<START>"] if uses_start else []
    lines += ["{{user}}: Hello?", char_line]
    return "\n".join(lines)


def build_coverage_notes(conv: dict) -> list[str]:
    """Honest notes about fields this corpus does NOT demonstrate.

    A corpus where no card populates `mes_example` cannot teach a model to
    write one; silently demanding it anyway is how you get a field filled
    in with something arbitrary. Say so instead - it's also the signal the
    corpus owner needs to decide whether to add cards that do have it.
    """
    notes: list[str] = []
    total = conv["total_cards"]
    if total < _MIN_CARDS:
        return notes
    coverage = conv["field_coverage"]
    for field in ("personality", "mes_example", "scenario"):
        n = coverage.get(field, 0)
        if n == 0:
            notes.append(
                f"- No card in this corpus fills the separate `{_CORE_FIELD_LABELS[field]}` field "
                f"(0/{total}) — so there is no house style here to copy for it."
            )
    if coverage.get("tags", 0) == 0:
        notes.append(f"- None of these cards carry tags (0/{total}).")
    return notes


def build_absent_core_fields(conv: dict) -> list[str]:
    """Core fields no card populates, as template labels."""
    if conv["total_cards"] < _MIN_CARDS:
        return []
    coverage = conv["field_coverage"]
    return [_CORE_FIELD_LABELS[f] for f in CORE_FIELDS if coverage.get(f, 0) == 0]


def build_field_guidance(conv: dict) -> list[dict]:
    """Per-core-field guidance derived from what the corpus actually does.

    The point is to GUIDE using the data rather than impose a fixed
    six-field contract. A field no card fills isn't "missing" - very often
    the corpus deliberately keeps that content somewhere else (these cards
    put personality in a `>Personality` section inside description and
    leave the spec's own `personality` field empty). Saying "required, but
    we can't show you one" is worse than saying where the corpus actually
    puts it and letting the writer follow suit.

    Each entry: {label, field, count, total, used, note}.
    """
    total = conv["total_cards"]
    coverage = conv["field_coverage"]
    section_names = {n.lower() for n, _c, _p in conv["section_names"]}

    out: list[dict] = []
    for field in CORE_FIELDS:
        if field == "name":
            continue
        label = _CORE_FIELD_LABELS[field]
        count = coverage.get(field, 0)
        entry = {"label": label, "field": field, "count": count, "total": total, "used": count > 0, "note": ""}

        if count == 0 and total >= _MIN_CARDS:
            # Does the corpus keep this content inside description instead?
            if label.lower() in section_names:
                entry["note"] = (
                    f"no card fills this separate field — these cards put it in the "
                    f"`>{label}` section inside Description instead. Following the corpus "
                    f"means doing the same; fill this field too only if it helps."
                )
            else:
                entry["note"] = (
                    "no card here uses this field, so there's no house style to follow for it. "
                    "Optional — include it only if it genuinely adds something, in the same "
                    "voice and formatting as the rest."
                )
        elif total >= _MIN_CARDS and _share(count, total) < _COMMON_SHARE:
            # Rare-but-present is different from absent: these cards
            # mostly get by without it, which is itself the guidance.
            entry["note"] = (
                f"only {count} of {total} cards use it — this corpus mostly does without it, "
                f"so treat it as optional rather than something to fill in for completeness."
            )
        elif total >= _MIN_CARDS and count < total:
            entry["note"] = f"used by {count} of {total} cards — include it when it fits."
        out.append(entry)
    return out
