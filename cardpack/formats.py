"""Writers that turn a list of Card objects into one combined export file.

Why not just dump JSON? Two reasons the user called out: some places you'd
paste this (chat uploads, other tools) don't take .json, and even when they
do, JSON's braces/quotes/escaped-newlines burn a lot of tokens for what is
mostly prose fields. So the default formats here are plain text, and the
"compact" one in particular optimizes hard for token count while staying
unambiguous enough for a model to parse back out.

This is meant to be handed to a model as a *reference corpus* — "here are
N existing characters, use them to understand what works and design a new
one" — not as one blob of text. Every writer therefore opens with an
explicit framing paragraph (so the model doesn't mistake dozens of cards
for one character's info) and gives every card an unambiguous section
delimiter it can't blend into its neighbor.

The six fields the corpus exists to compare across cards — name,
description, personality, scenario, first_mes, mes_example — are always
present (truncated, not dropped, when not --full). tags and creator_notes
are included too: tags are the closest thing to a genre/archetype label,
and creator_notes is often where a creator explains what the card is for
or how it's meant to be used, which is exactly the "why do people use
this" signal a reference corpus is for. Everything else (system prompt,
post-history instructions, full alternate greetings, full lorebook text)
is configuration/runtime detail rather than content signal, so it's
summarized to a count by default and only spelled out with --full.
"""

from __future__ import annotations

import json
import os
from typing import Iterable

from .cardspec import Card
from .stats import build_corpus_stats, estimate_tokens, format_stats_block

# Fields whose text can be huge relative to how useful they are for
# cross-card pattern analysis. In digest (non --full) mode we cap them.
_DEFAULT_MAX_CHARS = 600

_CORPUS_PREAMBLE = (
    "This file is a REFERENCE CORPUS of {n} separate, existing character cards. "
    "It is not one character. Each numbered section below is a distinct card, "
    "included so you can compare them and identify patterns — recurring "
    "personality archetypes, what makes a first_mes hook effective, how "
    "description/personality/scenario are typically structured, and (from "
    "tags and creator notes) what these cards are used for and why. Use "
    "those patterns as inspiration to design a NEW, original character. Do "
    "not copy any single card's text verbatim."
)


def _truncate(text: str, max_chars: int | None) -> str:
    if not text:
        return ""
    if max_chars is None or len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + " …[truncated]"


def _clean(text: str) -> str:
    return (text or "").strip()


def _basename(path: str) -> str:
    return os.path.basename(path) if path else ""


def to_markdown(cards: Iterable[Card], *, full: bool = False, max_chars: int | None = _DEFAULT_MAX_CHARS) -> str:
    cards = list(cards)
    cap = None if full else max_chars
    lines: list[str] = []
    lines.append(f"# Character Reference Corpus ({len(cards)} cards)")
    lines.append("")
    lines.append(_CORPUS_PREAMBLE.format(n=len(cards)))
    lines.append("")
    lines.append("## Corpus Stats")
    lines.append(format_stats_block(build_corpus_stats(cards)))
    lines.append("")
    for i, card in enumerate(cards, 1):
        title = card.name or card.nickname or "(unnamed)"
        lines.append(f"## Card {i}/{len(cards)}: {title}")
        lines.append(f"- (file: {_basename(card.source_file)})")
        if card.tags:
            lines.append(f"- Tags: {', '.join(card.tags)}")
        if card.description:
            lines.append(f"- Description: {_truncate(_clean(card.description), cap)}")
        if card.personality:
            lines.append(f"- Personality: {_truncate(_clean(card.personality), cap)}")
        if card.scenario:
            lines.append(f"- Scenario: {_truncate(_clean(card.scenario), cap)}")
        if card.first_mes:
            lines.append(f"- First message: {_truncate(_clean(card.first_mes), cap)}")
        if card.mes_example:
            lines.append(f"- Example dialogue: {_truncate(_clean(card.mes_example), cap)}")
        if card.creator_notes:
            lines.append(f"- Creator notes: {_truncate(_clean(card.creator_notes), cap)}")
        if full and card.alternate_greetings:
            lines.append(f"- Alt greetings ({len(card.alternate_greetings)}):")
            for g in card.alternate_greetings:
                lines.append(f"  - {_truncate(_clean(g), cap)}")
        elif card.alternate_greetings:
            lines.append(f"- Alt greetings: {len(card.alternate_greetings)} (use --full to include)")
        if full and card.system_prompt:
            lines.append(f"- System prompt: {_truncate(_clean(card.system_prompt), cap)}")
        if full and card.lorebook_entries:
            lines.append(f"- Lorebook ({len(card.lorebook_entries)} entries):")
            for entry in card.lorebook_entries:
                keys = ", ".join(entry.get("keys") or [])
                content = _truncate(_clean(entry.get("content", "")), cap)
                lines.append(f"  - [{keys}] {content}")
        elif card.lorebook_entries:
            lines.append(f"- Lorebook: {len(card.lorebook_entries)} entries (use --full to include)")
        lines.append("")
    body = "\n".join(lines).rstrip() + "\n"
    return body + f"\n---\n~{estimate_tokens(body)} tokens (rough estimate, ~4 chars/token)\n"


# Abbreviated field labels for the compact format, documented in a header
# block so both humans and the receiving model can decode them.
_COMPACT_LEGEND = (
    "N=name T=tags D=description P=personality S=scenario G=first_mes "
    "EX=example-dialogue CN=creator-notes AG=alt-greeting-count "
    "LB=lorebook-entry-count"
)


def to_compact(cards: Iterable[Card], *, full: bool = False, max_chars: int | None = _DEFAULT_MAX_CHARS) -> str:
    cards = list(cards)
    cap = None if full else max_chars
    stats_line = format_stats_block(build_corpus_stats(cards), compact=True)
    lines: list[str] = [
        _CORPUS_PREAMBLE.format(n=len(cards)),
        f"Fields: {_COMPACT_LEGEND}",
        f"Stats: {stats_line}",
        "",
    ]
    for i, card in enumerate(cards, 1):
        lines.append(f"=== CARD {i}/{len(cards)} ===")
        title = card.name or card.nickname or "(unnamed)"
        lines.append(f"N: {title}")
        if card.tags:
            lines.append(f"T: {', '.join(card.tags)}")
        if card.description:
            lines.append(f"D: {_truncate(_clean(card.description), cap)}")
        if card.personality:
            lines.append(f"P: {_truncate(_clean(card.personality), cap)}")
        if card.scenario:
            lines.append(f"S: {_truncate(_clean(card.scenario), cap)}")
        if card.first_mes:
            lines.append(f"G: {_truncate(_clean(card.first_mes), cap)}")
        if card.mes_example:
            lines.append(f"EX: {_truncate(_clean(card.mes_example), cap)}")
        if card.creator_notes:
            lines.append(f"CN: {_truncate(_clean(card.creator_notes), cap)}")
        if card.alternate_greetings:
            lines.append(f"AG: {len(card.alternate_greetings)}")
        if card.lorebook_entries:
            lines.append(f"LB: {len(card.lorebook_entries)}")
        if full and card.system_prompt:
            lines.append(f"SYS: {_truncate(_clean(card.system_prompt), cap)}")
        lines.append("")
    body = "\n".join(lines).rstrip() + "\n"
    return body + f"\n# ~{estimate_tokens(body)} tokens (rough estimate)\n"


def card_to_dict(card: Card, *, full: bool = True) -> dict:
    d = {
        "name": card.name,
        "nickname": card.nickname,
        "character_version": card.character_version,
        "tags": card.tags,
        "description": card.description,
        "personality": card.personality,
        "scenario": card.scenario,
        "first_mes": card.first_mes,
        "alternate_greetings": card.alternate_greetings if full else len(card.alternate_greetings),
        "system_prompt": card.system_prompt,
        "post_history_instructions": card.post_history_instructions,
        "mes_example": card.mes_example if full else bool(card.mes_example),
        "creator_notes": card.creator_notes,
        "lorebook_entries": card.lorebook_entries if full else len(card.lorebook_entries),
        "source": card.source,
        "spec_version": card.spec_version,
        "source_keyword": card.source_keyword,
        "source_file": card.source_file,
    }
    return d


def to_json(cards: Iterable[Card], *, full: bool = False, max_chars: int | None = None) -> str:
    del max_chars  # JSON output is governed by --full only, not truncation
    cards = list(cards)
    payload = {
        "note": _CORPUS_PREAMBLE.format(n=len(cards)),
        "count": len(cards),
        "stats": build_corpus_stats(cards),
        "cards": [card_to_dict(c, full=full) for c in cards],
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    payload["approx_tokens"] = estimate_tokens(text)
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


WRITERS = {
    "md": to_markdown,
    "compact": to_compact,
    "json": to_json,
}
