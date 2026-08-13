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
GLM, DeepSeek, Llama, etc. all split text differently, so "the" token
count doesn't exist independent of a target model. TOKENIZER_PRESETS
below maps a short name to a real tokenizer for a few model families
people actually target with exports from this tool:

- "gpt" uses tiktoken's cl100k_base (exact for GPT-4/3.5).
- "deepseek" / "glm" load that model family's real tokenizer.json from
  the Hugging Face Hub via the `tokenizers` package (no torch/transformers
  needed - just the tokenizer, not the model).

Any of these requires the matching optional package AND, the first time
a given tokenizer is used, a one-time network fetch to cache its data
(tiktoken -> openaipublic's CDN, deepseek/glm -> huggingface.co). If the
package isn't installed or the fetch can't complete (offline, restrictive
proxy, gated repo), counting falls back to a word-aware heuristic rather
than failing the export - but the returned method label always says
plainly which one actually produced the number, including *why* it fell
back, so it's never presented as more precise than it is.

You aren't limited to the three presets: pass any "org/repo" Hugging Face
model id as the tokenizer name and its tokenizer.json is used the same
way as the deepseek/glm presets.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from .cardspec import Card

_WORD_RE = re.compile(r"\S+")

TOKENIZER_PRESETS = {
    "gpt": {"kind": "tiktoken", "key": "cl100k_base", "label": "tiktoken/cl100k_base (GPT-4/3.5-exact)"},
    "deepseek": {"kind": "hf", "key": "deepseek-ai/DeepSeek-V3", "label": "deepseek-ai/DeepSeek-V3 tokenizer"},
    "glm": {"kind": "hf", "key": "zai-org/GLM-4.5", "label": "zai-org/GLM-4.5 tokenizer"},
}
DEFAULT_TOKENIZER = "heuristic"

_tokenizer_cache: dict[str, tuple[object | None, str | None]] = {}  # "{kind}:{key}" -> (encoder, failure_reason)


def _load_tiktoken(encoding: str) -> tuple[object | None, str | None]:
    """Returns (encoder, failure_reason). failure_reason distinguishes the
    package being missing from the (far more common) one-time data
    download failing, so the fallback message can tell someone whether
    `pip install` or a network/proxy issue is what's actually blocking
    them."""
    try:
        import tiktoken
    except ImportError:
        return None, "`tiktoken` not installed (pip install tiktoken)"
    try:
        return tiktoken.get_encoding(encoding), None
    except Exception as e:
        return None, f"couldn't fetch its encoding data ({type(e).__name__}; usually offline/blocked network)"


def _load_hf_tokenizer(repo_id: str) -> tuple[object | None, str | None]:
    try:
        from tokenizers import Tokenizer
    except ImportError:
        return None, "`tokenizers` not installed (pip install tokenizers huggingface_hub)"
    try:
        return Tokenizer.from_pretrained(repo_id), None
    except Exception as e:
        return None, f"couldn't fetch {repo_id}'s tokenizer.json ({type(e).__name__}; offline/blocked/gated repo)"


def _resolve_backend(name: str) -> tuple[str, str | None, str]:
    """name -> (kind, key, label). kind is "heuristic" | "tiktoken" | "hf"."""
    if not name or name == "heuristic":
        return "heuristic", None, "heuristic"
    preset = TOKENIZER_PRESETS.get(name)
    if preset:
        return preset["kind"], preset["key"], preset["label"]
    if "/" in name:  # a raw Hugging Face "org/repo" id
        return "hf", name, f"{name} tokenizer"
    return "heuristic", None, "heuristic"  # unrecognized name: don't raise, just fall back


def _get_encoder(name: str) -> tuple[str, object | None, str]:
    kind, key, label = _resolve_backend(name)
    if kind == "heuristic":
        return "heuristic", None, label

    cache_key = f"{kind}:{key}"
    if cache_key not in _tokenizer_cache:
        loader = _load_tiktoken if kind == "tiktoken" else _load_hf_tokenizer
        _tokenizer_cache[cache_key] = loader(key)
    encoder, failure_reason = _tokenizer_cache[cache_key]

    if encoder is None:
        return "heuristic", None, f"heuristic - {label} unavailable: {failure_reason}"
    return kind, encoder, label


@dataclass(frozen=True)
class TokenCount:
    count: int
    method: str
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


def count_tokens(text: str, tokenizer: str = DEFAULT_TOKENIZER) -> TokenCount:
    kind, encoder, label = _get_encoder(tokenizer)
    if encoder is None:
        # _get_encoder already produced a label explaining why (plain
        # "heuristic" for an explicit heuristic request, or a "heuristic -
        # X unavailable (...)" explanation when a real tokenizer couldn't load)
        method = "heuristic (~0.75 tok/word)" if label == "heuristic" else label
        return TokenCount(_heuristic_token_count(text), method, False)
    try:
        if kind == "tiktoken":
            return TokenCount(len(encoder.encode(text, disallowed_special=())), label, True)
        return TokenCount(len(encoder.encode(text).ids), label, True)  # HF tokenizers.Tokenizer
    except Exception:
        return TokenCount(_heuristic_token_count(text), f"heuristic - {label} failed on this text", False)


def build_corpus_stats(cards: Iterable[Card], *, include_tags: bool = True) -> dict:
    """include_tags controls whether the top-tags breakdown is computed at
    all - if a caller has excluded the `tags` field from the export itself
    (to save tokens), showing an aggregate tag list here would spend those
    tokens right back and mention data the model can't see per-card."""
    cards = list(cards)
    tag_counts: Counter[str] = Counter()
    spec_counts: Counter[str] = Counter()
    desc_lengths = []
    total_bloat_removed = 0
    cards_with_bloat = 0
    bloat_by_card: list[tuple[str, int]] = []
    for c in cards:
        if include_tags:
            tag_counts.update(t.strip().lower() for t in c.tags if t.strip())
        spec_counts[c.spec_version] += 1
        if c.description:
            desc_lengths.append(len(c.description))
        if c.bloat_chars_removed:
            total_bloat_removed += c.bloat_chars_removed
            cards_with_bloat += 1
            bloat_by_card.append((c.name or c.nickname or "(unnamed)", c.bloat_chars_removed))
    bloat_by_card.sort(key=lambda pair: pair[1], reverse=True)

    return {
        "count": len(cards),
        "spec_versions": dict(sorted(spec_counts.items())),
        "top_tags": tag_counts.most_common(20),
        "avg_description_chars": round(sum(desc_lengths) / len(desc_lengths)) if desc_lengths else 0,
        "min_description_chars": min(desc_lengths) if desc_lengths else 0,
        "max_description_chars": max(desc_lengths) if desc_lengths else 0,
        "cards_missing_description": len(cards) - len(desc_lengths),
        "total_bloat_chars_removed": total_bloat_removed,
        "cards_with_bloat": cards_with_bloat,
        "top_bloat_cards": bloat_by_card[:3],
    }


def format_stats_block(stats: dict, *, compact: bool = False) -> str:
    if compact:
        parts = [f"n={stats['count']}"]
        if stats["spec_versions"]:
            parts.append("spec=" + ",".join(f"v{v}:{n}" for v, n in stats["spec_versions"].items()))
        if stats["top_tags"]:
            parts.append("top_tags=" + ",".join(f"{t}:{n}" for t, n in stats["top_tags"][:10]))
        if stats["max_description_chars"]:
            parts.append(
                f"desc_len={stats['min_description_chars']}-{stats['max_description_chars']}"
                f"(avg {stats['avg_description_chars']})"
            )
        if stats["total_bloat_chars_removed"]:
            parts.append(
                f"bloat_stripped={stats['total_bloat_chars_removed']}chars"
                f"(~{round(stats['total_bloat_chars_removed'] / 4)}tok) from {stats['cards_with_bloat']} cards"
            )
        return " | ".join(parts)

    lines = [f"- Cards: {stats['count']}"]
    if stats["spec_versions"]:
        versions = ", ".join(f"v{v}: {n}" for v, n in stats["spec_versions"].items())
        lines.append(f"- Spec versions: {versions}")
    if stats["top_tags"]:
        tags = ", ".join(f"{t} ({n})" for t, n in stats["top_tags"])
        lines.append(f"- Top tags: {tags}")
    if stats["max_description_chars"]:
        lines.append(
            f"- Description length: {stats['min_description_chars']}–{stats['max_description_chars']} chars "
            f"(avg {stats['avg_description_chars']}) — real variety, not noise; see the note above about not "
            f"averaging toward the middle of that range."
        )
    if stats["cards_missing_description"]:
        lines.append(f"- Cards with no description: {stats['cards_missing_description']}")
    if stats["total_bloat_chars_removed"]:
        approx_tokens = round(stats["total_bloat_chars_removed"] / 4)
        lines.append(
            f"- Markup/decoration already stripped: ~{stats['total_bloat_chars_removed']:,} chars "
            f"(~{approx_tokens:,} tokens) of embedded images/HTML/decorative separators removed from "
            f"{stats['cards_with_bloat']} card(s) before the text below — nothing of substance was lost."
        )
        if stats["top_bloat_cards"]:
            worst = ", ".join(f"{name} (~{n:,} chars)" for name, n in stats["top_bloat_cards"])
            lines.append(f"  Heaviest: {worst}")
    return "\n".join(lines)
