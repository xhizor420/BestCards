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

Only conventions that are actually dominant get reported (see _MIN_SHARE),
and only when enough cards carry the field to say anything meaningful
(_MIN_CARDS) - reporting "20% of cards do X" would invite mimicking a
minority style, and reporting anything at all from a 2-card corpus is
noise.
"""

from __future__ import annotations

import re
import statistics
from collections import defaultdict
from typing import Iterable

from .cardspec import Card

# A convention must appear in at least this share of the cards that have
# the relevant field before it's reported as "how this corpus does it".
_MIN_SHARE = 0.5
# ...and at least this many cards must have the field at all, so tiny
# corpora don't produce confident-sounding claims from 1-2 examples.
_MIN_CARDS = 3

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


def _share(matching: int, total: int) -> float:
    return (matching / total) if total else 0.0


def _dominant(matching: int, total: int) -> bool:
    return total >= _MIN_CARDS and _share(matching, total) >= _MIN_SHARE


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

    field_coverage = {
        f: sum(1 for c in cards if str(getattr(c, f, "") or "").strip()) for f in CORE_FIELDS
    }
    field_coverage["tags"] = sum(1 for c in cards if c.tags)

    return {
        "total_cards": len(cards),
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


def build_convention_lines(conv: dict) -> list[str]:
    """Human/model-readable instruction lines for the dominant conventions.

    Empty when the corpus is too small or too inconsistent to claim a
    house style - better to say nothing than to assert a convention half
    the cards don't follow.
    """
    lines: list[str] = []
    total = conv["total_cards"]
    n_example = conv["cards_with_example"]
    n_first = conv["cards_with_first_mes"]
    n_desc = conv["cards_with_description"]
    n_scenario = conv["cards_with_scenario"]

    # --- document structure first: it's the biggest determinant of whether
    # --- the result looks like the corpus at all.
    if _dominant(conv["section_header_cards"], n_desc):
        names = [n for n, _c, _p in conv["section_names"]]
        listed = ", ".join(f"`>{n}`" for n in names) if names else "`>Appearance`, `>Personality`, ..."
        lines.append(
            f"- Build Description as a STRUCTURED DOSSIER, not a paragraph: "
            f"`>Section` header lines ({_pct(conv['section_header_cards'], n_desc)}% of these cards do), "
            f"typically these in this order — {listed}."
        )
        if conv["median_description_chars"]:
            lines.append(
                f"- That dossier is substantial: the median Description here is about "
                f"{conv['median_description_chars']:,} characters. A few short paragraphs is nowhere near it."
            )
    if _dominant(conv["plus_bullet_cards"], n_desc):
        lines.append(
            f"- Inside those sections, write facts as `+ ` bullet lines "
            f"({_pct(conv['plus_bullet_cards'], n_desc)}% of these cards do)."
        )
    if _dominant(conv["xml_block_cards"], n_desc):
        extra = ""
        if _dominant(conv["npc_block_cards"], n_desc):
            extra = ", and put side characters in a separate `<NPC>` block"
        lines.append(
            f"- Wrap the character's dossier in `<Name>` … `</Name>` tags"
            f"{extra} ({_pct(conv['xml_block_cards'], n_desc)}% of these cards do)."
        )
    if _dominant(conv["scenario_instructions_cards"], n_scenario):
        lines.append(
            f"- Write Scenario as an `<instructions>` block of explicit roleplay directives "
            f"({_pct(conv['scenario_instructions_cards'], n_scenario)}% of these cards do), not as prose setting."
        )

    # --- inline formatting
    if _dominant(conv["char_placeholder"], total) or _dominant(conv["user_placeholder"], total):
        both = _dominant(conv["char_placeholder"], total) and _dominant(conv["user_placeholder"], total)
        which = (
            "{{char}} and {{user}}"
            if both
            else ("{{char}}" if _dominant(conv["char_placeholder"], total) else "{{user}}")
        )
        pct = max(_pct(conv["char_placeholder"], total), _pct(conv["user_placeholder"], total))
        lines.append(
            f"- Use the {which} placeholder(s) rather than writing names literally ({pct}% of these cards do)."
        )
    if _dominant(conv["first_mes_status_line"], n_first):
        lines.append(
            f"- Open First Message with a pipe-separated status line "
            f"(e.g. `11:12 PM | August 6 | 11°C Raining | Apartment Hallway`) — "
            f"{_pct(conv['first_mes_status_line'], n_first)}% of these cards do."
        )
    if _dominant(conv["asterisk_action"], n_first):
        lines.append(
            f"- Wrap actions/narration in *asterisks*, keeping speech outside them "
            f"({_pct(conv['asterisk_action'], n_first)}% of these cards do)."
        )
    if _dominant(conv["quoted_speech"], n_first):
        lines.append(
            f'- Put spoken dialogue in "double quotes" ({_pct(conv["quoted_speech"], n_first)}% of these cards do).'
        )
    if _dominant(conv["backtick_thoughts"], total):
        lines.append(
            f"- Put inner thoughts in `backticks` ({_pct(conv['backtick_thoughts'], total)}% of these cards do)."
        )
    if n_first >= _MIN_CARDS and conv["median_first_mes_paragraphs"] >= 2:
        lines.append(
            f"- First Message runs about {conv['median_first_mes_paragraphs']} paragraphs in these cards, "
            f"not one line — long, scene-setting, and in-voice."
        )
    if _dominant(conv["start_marker"], n_example):
        lines.append(
            f"- Begin Example Dialogue with a `<START>` line "
            f"({_pct(conv['start_marker'], n_example)}% of these cards do)."
        )
    if _dominant(conv["turn_prefixed_example"], n_example):
        turns = conv["median_example_turns"]
        turn_note = f" — typically about {turns} turn lines" if turns else ""
        lines.append(
            f"- Write Example Dialogue as alternating `{{{{user}}}}:` and `{{{{char}}}}:` lines, one turn per "
            f"line ({_pct(conv['turn_prefixed_example'], n_example)}% of these cards do{turn_note})."
        )

    return lines


def build_description_skeleton(conv: dict) -> str:
    """A concrete skeleton for the Description field mirroring the corpus's
    own section/bullet structure, or a plain placeholder when the corpus
    has no dominant structure to mirror."""
    n_desc = conv["cards_with_description"]
    if not _dominant(conv["section_header_cards"], n_desc):
        return "<appearance, background, key facts>"

    names = [n for n, _c, _p in conv["section_names"]] or ["Appearance", "Personality", "Backstory"]
    bullet = "+ " if _dominant(conv["plus_bullet_cards"], n_desc) else "- "
    uses_xml = _dominant(conv["xml_block_cards"], n_desc)

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
