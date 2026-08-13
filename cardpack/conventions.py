"""Detect the writing conventions a corpus of cards actually uses.

"Write it the way the strongest cards above wrote theirs" is not an
actionable instruction - a model handed 100 cards and a vague style note
will produce something structurally unlike the corpus, and the
mes_example field is where this fails hardest, because its conventions
(a `<START>` marker, `{{user}}:` / `{{char}}:` turn prefixes, asterisk
actions) are *conventions*, not things a model would infer reliably from
prose descriptions of what the field is for.

So instead of describing the fields abstractly, measure what the corpus
actually does and state it as explicit instructions with the real
percentages behind them. A model told "94% of these cards start
mes_example with <START> and alternate {{user}}: / {{char}}: turns" has
something concrete to match; one told "write an example exchange
demonstrating the character's voice" does not.

Only conventions that are actually dominant get reported (see
_MIN_SHARE), and only when enough cards carry the field to say anything
meaningful (_MIN_CARDS) - reporting "20% of cards do X" would invite
mimicking a minority style, and reporting anything at all from a 2-card
corpus is noise.
"""

from __future__ import annotations

import re
import statistics
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
# Turn lines like `{{user}}: hello` / `{{char}}: hi` at the start of a line.
_TURN_LINE_RE = re.compile(r"^\s*\{\{(?:user|char)\}\}\s*:", re.IGNORECASE | re.MULTILINE)


def _share(matching: int, total: int) -> float:
    return (matching / total) if total else 0.0


def _dominant(matching: int, total: int) -> bool:
    return total >= _MIN_CARDS and _share(matching, total) >= _MIN_SHARE


def analyze_conventions(cards: Iterable[Card]) -> dict:
    """Measure structural/formatting conventions across the corpus.

    Returns raw counts and shares; deciding what's worth *telling* a model
    is format_conventions_block()'s job.
    """
    cards = list(cards)

    with_example = [c for c in cards if c.mes_example.strip()]
    with_first_mes = [c for c in cards if c.first_mes.strip()]
    # Placeholder usage is a whole-card convention, so look across the
    # fields where {{char}}/{{user}} would plausibly appear.
    combined_text = [
        "\n".join([c.description, c.personality, c.scenario, c.first_mes, c.mes_example]) for c in cards
    ]

    example_turn_counts = [len(_TURN_LINE_RE.findall(c.mes_example)) for c in with_example]
    example_turn_counts = [n for n in example_turn_counts if n > 0]

    first_mes_paragraphs = [len([p for p in c.first_mes.split("\n\n") if p.strip()]) for c in with_first_mes]

    return {
        "total_cards": len(cards),
        "cards_with_example": len(with_example),
        "cards_with_first_mes": len(with_first_mes),
        "char_placeholder": sum(1 for t in combined_text if _CHAR_PLACEHOLDER_RE.search(t)),
        "user_placeholder": sum(1 for t in combined_text if _USER_PLACEHOLDER_RE.search(t)),
        "start_marker": sum(1 for c in with_example if _START_MARKER_RE.search(c.mes_example)),
        "turn_prefixed_example": sum(1 for c in with_example if _TURN_LINE_RE.search(c.mes_example)),
        "median_example_turns": round(statistics.median(example_turn_counts)) if example_turn_counts else 0,
        "asterisk_action": sum(
            1 for c in with_first_mes if _ASTERISK_ACTION_RE.search(c.first_mes) or _ASTERISK_ACTION_RE.search(c.mes_example)
        ),
        "quoted_speech": sum(1 for c in with_first_mes if _QUOTED_SPEECH_RE.search(c.first_mes)),
        "median_first_mes_paragraphs": round(statistics.median(first_mes_paragraphs)) if first_mes_paragraphs else 0,
    }


def _pct(matching: int, total: int) -> int:
    return round(_share(matching, total) * 100)


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

    if _dominant(conv["char_placeholder"], total) or _dominant(conv["user_placeholder"], total):
        both = _dominant(conv["char_placeholder"], total) and _dominant(conv["user_placeholder"], total)
        which = "{{char}} and {{user}}" if both else ("{{char}}" if _dominant(conv["char_placeholder"], total) else "{{user}}")
        pct = max(_pct(conv["char_placeholder"], total), _pct(conv["user_placeholder"], total))
        lines.append(
            f"- Use the {which} placeholder(s) rather than writing names literally "
            f"({pct}% of these cards do)."
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
            f"- Write Example Dialogue as alternating `{{{{user}}}}:` and `{{{{char}}}}:` "
            f"lines, one turn per line ({_pct(conv['turn_prefixed_example'], n_example)}% of "
            f"these cards do{turn_note})."
        )

    if _dominant(conv["asterisk_action"], n_first):
        lines.append(
            f"- Wrap actions/narration in *asterisks*, keeping speech outside them "
            f"({_pct(conv['asterisk_action'], n_first)}% of these cards do)."
        )

    if _dominant(conv["quoted_speech"], n_first):
        lines.append(
            f"- Put spoken dialogue in \"double quotes\" "
            f"({_pct(conv['quoted_speech'], n_first)}% of these cards do)."
        )

    if n_first >= _MIN_CARDS and conv["median_first_mes_paragraphs"] >= 2:
        lines.append(
            f"- First Message typically runs about {conv['median_first_mes_paragraphs']} "
            f"paragraphs in these cards, not one line."
        )

    return lines


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
