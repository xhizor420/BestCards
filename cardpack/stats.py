"""Corpus-level aggregates across a batch of cards.

Individual card fields matter, but when an AI model is being handed
hundreds of cards to spot *patterns* from, a frequency summary up front
(most common tags, spec-version mix, how prose-heavy the batch is) is
worth more per token than another paragraph of description text — it
tells the model what's typical vs. what's an outlier before it even
reads the individual entries.

Deliberately excluded: per-creator/attribution stats. Who made a card
isn't a content pattern a model can learn from, so it's just token cost
with no analytical payoff for this use case.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable

from .cardspec import Card


def build_corpus_stats(cards: Iterable[Card]) -> dict:
    cards = list(cards)
    tag_counts: Counter[str] = Counter()
    spec_counts: Counter[str] = Counter()
    desc_lengths = []
    for c in cards:
        tag_counts.update(t.strip().lower() for t in c.tags if t.strip())
        spec_counts[c.spec_version] += 1
        if c.description:
            desc_lengths.append(len(c.description))

    return {
        "count": len(cards),
        "spec_versions": dict(sorted(spec_counts.items())),
        "top_tags": tag_counts.most_common(20),
        "avg_description_chars": round(sum(desc_lengths) / len(desc_lengths)) if desc_lengths else 0,
        "cards_missing_description": len(cards) - len(desc_lengths),
    }


def estimate_tokens(text: str) -> int:
    """Rough size hint, not a real tokenizer: ~4 chars/token is the usual
    ballpark for English prose across most current model tokenizers."""
    return max(0, round(len(text) / 4))


def format_stats_block(stats: dict, *, compact: bool = False) -> str:
    if compact:
        parts = [f"n={stats['count']}"]
        if stats["spec_versions"]:
            parts.append("spec=" + ",".join(f"v{v}:{n}" for v, n in stats["spec_versions"].items()))
        if stats["top_tags"]:
            parts.append("top_tags=" + ",".join(f"{t}:{n}" for t, n in stats["top_tags"][:10]))
        return " | ".join(parts)

    lines = [f"- Cards: {stats['count']}"]
    if stats["spec_versions"]:
        versions = ", ".join(f"v{v}: {n}" for v, n in stats["spec_versions"].items())
        lines.append(f"- Spec versions: {versions}")
    if stats["top_tags"]:
        tags = ", ".join(f"{t} ({n})" for t, n in stats["top_tags"])
        lines.append(f"- Top tags: {tags}")
    lines.append(f"- Avg description length: {stats['avg_description_chars']} chars")
    if stats["cards_missing_description"]:
        lines.append(f"- Cards with no description: {stats['cards_missing_description']}")
    return "\n".join(lines)
