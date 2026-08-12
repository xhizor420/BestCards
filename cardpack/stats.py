"""Corpus-level aggregates and token counting.

Individual card fields matter, but when an AI model is being handed
hundreds of cards to spot *patterns* from, a frequency summary up front
(most common tags, spec-version mix, how prose-heavy the batch is) is
worth more per token than another paragraph of description text — it
tells the model what's typical vs. what's an outlier before it even
reads the individual entries.

Deliberately excluded: per-creator/attribution stats. Who made a card
isn't a content pattern a model can learn from, so it's just token cost
with no analytical payoff for this use case.

Token counting: there is no single universal tokenizer — GPT, Claude,
Llama, etc. all split text differently, so no number here is "exact" for
every model. If the optional `tiktoken` package is installed (and can
reach its one-time encoding-data download), we use it for a real BPE
count that matches GPT-4/3.5 exactly and is a close proxy for most other
modern BPE tokenizers, including Claude's. Otherwise we fall back to a
word-aware heuristic. Every count is labeled with which method produced
it so it's never presented as more precise than it is.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from .cardspec import Card

_WORD_RE = re.compile(r"\S+")

_tiktoken_encoder = "unchecked"  # sentinel; becomes an Encoding or None after first attempt


def _get_tiktoken_encoder():
    global _tiktoken_encoder
    if _tiktoken_encoder == "unchecked":
        try:
            import tiktoken

            _tiktoken_encoder = tiktoken.get_encoding("cl100k_base")
        except Exception:
            # Not installed, or (common in sandboxed/offline environments) its
            # one-time BPE-ranks download couldn't reach openaipublic's CDN.
            _tiktoken_encoder = None
    return _tiktoken_encoder


@dataclass(frozen=True)
class TokenCount:
    count: int
    method: str  # short label, safe to show in output: "tiktoken/cl100k_base" | "heuristic"
    exact: bool


def _heuristic_token_count(text: str) -> int:
    """Better than a flat chars/4: BPE tokenizers roughly average ~0.75
    tokens per whitespace-delimited word for English prose, with a
    per-character floor for chunks with unusually long/short "words"
    (numbers, code, CJK text, punctuation runs) where that ratio breaks
    down. Still an estimate, not a real tokenizer.
    """
    if not text:
        return 0
    words = _WORD_RE.findall(text)
    by_words = round(len(words) * 0.75) if words else 0
    by_chars = round(len(text) / 4)
    return max(by_words, by_chars, 1 if text.strip() else 0)


def count_tokens(text: str) -> TokenCount:
    encoder = _get_tiktoken_encoder()
    if encoder is not None:
        try:
            return TokenCount(len(encoder.encode(text, disallowed_special=())), "tiktoken/cl100k_base", True)
        except Exception:
            pass  # fall through to heuristic if encoding this particular text fails
    return TokenCount(_heuristic_token_count(text), "heuristic (~0.75 tok/word)", False)


def build_corpus_stats(cards: Iterable[Card], *, include_tags: bool = True) -> dict:
    """include_tags controls whether the top-tags breakdown is computed at
    all - if a caller has excluded the `tags` field from the export itself
    (to save tokens), showing an aggregate tag list here would spend those
    tokens right back and mention data the model can't see per-card."""
    cards = list(cards)
    tag_counts: Counter[str] = Counter()
    spec_counts: Counter[str] = Counter()
    desc_lengths = []
    for c in cards:
        if include_tags:
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
