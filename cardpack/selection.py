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
    _SECTION_HEADER_RE,
    _XML_BLOCK_RE,
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
    sections = {m.strip().lower() for m in _SECTION_HEADER_RE.findall(desc)}
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
