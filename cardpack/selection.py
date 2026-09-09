"""Rank cards by how much they can teach, and pick the best subset.

The default export caps every field at --max-chars, which for a corpus of
richly-structured cards is quietly catastrophic: with a median
description of ~8,400 characters, a 600-char cap shows a model roughly 7%
of each card and only 17 of 125 `>Section` headers across the whole file.
The template then asks it to build a six-section dossier it has almost
never seen completed. Breadth was being bought with depth, and depth is
the part that carries the structure.

The fix is to spend the token budget on FEWER, COMPLETE cards rather than
many fragments - and to spend it on the cards that demonstrate the most.
`rank_cards` scores each card on how much a reader can learn from it, so
`--best N --full` yields a corpus of whole, richly-structured exemplars
that fits a real context window.

Scoring deliberately rewards structure over raw size: a long unstructured
description is worth less as a teaching example than a shorter one that
lays out clean `>Sections`, because the structure is what the export is
trying to convey.
"""

from __future__ import annotations

from .cardspec import Card
from .conventions import (
    _PLUS_BULLET_RE,
    _XML_BLOCK_RE,
    _section_headers,
)


def score_card(card: Card) -> float:
    """How much this card can teach a reader, roughly 0-100.

    Structure is weighted well above length: the point of the corpus is to
    convey how these cards are organised, and a sprawling wall of prose
    conveys less of that than a compact, cleanly sectioned dossier.
    """
    desc = card.description or ""
    score = 0.0

    # Structure - the most valuable thing a card demonstrates.
    # Same detector the reporting uses, so a card that counts as
    # "structured" in the template also scores as structured here.
    sections = {name.strip().lower() for _marker, name in _section_headers(desc)}
    score += min(len(sections), 8) * 6.0  # up to 48
    if _PLUS_BULLET_RE.search(desc):
        score += 8.0
    if _XML_BLOCK_RE.search(desc):
        score += 6.0

    # Substance - real content to learn voice and depth from, with
    # diminishing returns so one enormous card can't dominate the ranking.
    score += min(len(desc) / 1000.0, 12.0)  # up to 12
    score += min(len(card.first_mes) / 500.0, 8.0)  # up to 8

    # Completeness across the fields the corpus actually uses.
    if card.scenario.strip():
        score += 5.0
    if card.mes_example.strip():
        score += 4.0
    if card.tags:
        score += 2.0
    if card.creator_notes.strip():
        score += 1.0
    if card.alternate_greetings:
        score += 2.0
    if card.lorebook_entries:
        score += 4.0

    return round(score, 2)


def rank_cards(cards: list[Card]) -> list[Card]:
    """Best-teaching cards first; ties broken by name for stable output."""
    return sorted(cards, key=lambda c: (-score_card(c), (c.name or "").lower()))


def select_best(cards: list[Card], limit: int | None) -> list[Card]:
    """The `limit` most instructive cards, still ranked best-first."""
    ranked = rank_cards(cards)
    return ranked[:limit] if limit and limit > 0 else ranked


def exemplar_names(cards: list[Card], n: int = 3) -> list[str]:
    """Names of the top-scoring cards, for pointing a reader at the
    clearest worked examples instead of leaving it to skim all of them."""
    out: list[str] = []
    for card in rank_cards(cards)[:n]:
        name = (card.name or card.nickname or "").strip()
        if name and score_card(card) > 0:
            out.append(name)
    return out


def apply_pins(cards: list[Card], pinned_files: list[str] | None) -> list[Card]:
    """Move explicitly pinned cards to the front, keeping relative order.

    Ranking is a heuristic and it can only see the page. Group cards carry
    more characters, so they run longer with more sections and tend to lead
    the ranking - on a real corpus 5 of the top 10 were multi-character.
    That's not a fault to correct: group cards are long because they hold a
    group, and the export deliberately keeps both kinds so a solo request
    and a group request each have something to follow.

    What the score genuinely cannot know is which shape the reader is
    about to write. Someone building a solo card may want solo cards in
    the full-depth tier; someone building an ensemble may want the
    opposite. The person who curated the corpus knows that, so pinning
    overrides the score - pinned cards lead the export and fill the
    untrimmed tier first.
    """
    if not pinned_files:
        return cards
    wanted = {f for f in pinned_files if f}
    pinned = [c for c in cards if c.source_file in wanted]
    rest = [c for c in cards if c.source_file not in wanted]
    return pinned + rest


# --- how much the corpus agrees with itself -------------------------------
# Adding cards is not monotonically good, and the failure is invisible.
# Measured on a real 113-card corpus, ranked best-first: the top 50 cards
# used the same dossier structure 98% of the time, so the export told the
# model "this is the house style, follow it". The remaining 63 dropped that
# to 43%, which demotes the very same instruction to "here is one option
# among several". The extra cards did not add information - they diluted
# the signal the corpus exists to carry.
#
# So the useful question is not "how many tokens fit" but "how far down the
# ranking do the cards still agree with each other".

# A convention at or above this share reads as the house style rather than
# one option - the same bar conventions.py uses to promote a line into the
# "shared, just follow it" group.
_AGREEMENT_BAR = 0.8
# Below this many cards the vocabulary is still unstable: on the same real
# corpus, one card's idiosyncratic headings (Powers/Skills, Likes,
# Dislikes) were still being reported as house style at N=15, and the
# section list only settled from N=20 onward.
_MIN_STABLE_CARDS = 20


def structure_consistency(cards: list[Card]) -> dict:
    """How much of this corpus shares one description structure.

    Returns the share for the whole set plus `agreeing_prefix`: the largest
    number of top-ranked cards that still clear the agreement bar. Cards
    are assumed already ranked best-first; the per-card test runs once and
    every prefix is then a running total, so this is cheap enough to call
    on every keystroke in a UI.
    """
    described = [c for c in cards if c.description.strip()]
    if not described:
        return {"cards": 0, "structured": 0, "share": 0.0, "agreeing_prefix": 0, "stable": False}

    flags = [1 if _section_headers(c.description) else 0 for c in described]
    running = 0
    agreeing_prefix = 0
    for i, f in enumerate(flags, 1):
        running += f
        if running / i >= _AGREEMENT_BAR:
            agreeing_prefix = i

    total = len(described)
    structured = sum(flags)
    return {
        "cards": total,
        "structured": structured,
        "share": structured / total,
        "agreeing_prefix": agreeing_prefix,
        "stable": total >= _MIN_STABLE_CARDS,
    }


def consistency_note(stats: dict) -> list[str]:
    """Plain-language read on whether this corpus is teaching one style.

    Says nothing when the corpus already agrees with itself - there is no
    advice to give - and never proposes dropping cards on its own: which
    cards are worth keeping is the curator's call, so this reports what the
    numbers do and leaves the decision alone.
    """
    total, share, prefix = stats["cards"], stats["share"], stats["agreeing_prefix"]
    if not total:
        return []
    if total < _MIN_STABLE_CARDS:
        return [
            f"Only {total} cards carry a description. Below about {_MIN_STABLE_CARDS} the detected "
            f"section vocabulary is still unstable — one card's own headings can be reported as "
            f"the house style — so a few more comparable cards will sharpen the guidance."
        ]
    if share >= _AGREEMENT_BAR:
        return [
            f"{stats['structured']} of {total} cards ({share:.0%}) share one description "
            f"structure, so the export states it as the house style to follow rather than as "
            f"one option among several. This corpus is teaching a single clear pattern."
        ]
    lines = [
        f"Only {stats['structured']} of {total} cards ({share:.0%}) share one description "
        f"structure, so the export can only offer it as one approach among several — the "
        f"strongest instruction it can give is reserved for a pattern most cards agree on."
    ]
    if prefix >= _MIN_STABLE_CARDS:
        lines.append(
            f"Your top {prefix} cards do agree ({_AGREEMENT_BAR:.0%}+). Cards ranked below that "
            f"are pulling the shared pattern apart, so a smaller, more consistent set would give "
            f"the model a stronger instruction than this larger one does."
        )
    return lines
