"""Writers that turn a list of Card objects into one combined export file.

Why not just dump JSON? Two reasons the user called out: some places you'd
paste this (chat uploads, other tools) don't take .json, and even when they
do, JSON's braces/quotes/escaped-newlines burn a lot of tokens for what is
mostly prose fields. So the default formats here are plain text, and the
"compact" one in particular optimizes hard for token count while staying
unambiguous enough for a model to parse back out.
"""

from __future__ import annotations

import json
from typing import Iterable

from .cardspec import Card

# Fields whose text can be huge relative to how useful they are for
# cross-card pattern analysis. In "digest" (non --full) mode we cap them.
_DEFAULT_MAX_CHARS = 600


def _truncate(text: str, max_chars: int | None) -> str:
    if not text:
        return ""
    if max_chars is None or len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + " …[truncated]"


def _clean(text: str) -> str:
    return (text or "").strip()


def to_markdown(cards: Iterable[Card], *, full: bool = False, max_chars: int | None = _DEFAULT_MAX_CHARS) -> str:
    cards = list(cards)
    cap = None if full else max_chars
    lines: list[str] = []
    lines.append(f"# Character Card Digest ({len(cards)} cards)")
    lines.append("")
    lines.append(
        "Combined, de-duplicated export of embedded character-card metadata "
        "from a batch of PNG cards (SillyTavern/JanitorAI/Chub V1-V3 format)."
    )
    lines.append("")
    for i, card in enumerate(cards, 1):
        title = card.name or card.nickname or "(unnamed)"
        lines.append(f"## {i}. {title}")
        lines.append(f"- Source: `{card.source_file}` (spec v{card.spec_version}, chunk `{card.source_keyword}`)")
        if card.creator:
            lines.append(f"- Creator: {card.creator}")
        if card.character_version:
            lines.append(f"- Version: {card.character_version}")
        if card.tags:
            lines.append(f"- Tags: {', '.join(card.tags)}")
        if card.description:
            lines.append(f"- Description: {_truncate(_clean(card.description), cap)}")
        if card.personality:
            lines.append(f"- Personality: {_truncate(_clean(card.personality), cap)}")
        if card.scenario:
            lines.append(f"- Scenario: {_truncate(_clean(card.scenario), cap)}")
        if card.first_mes:
            lines.append(f"- Greeting: {_truncate(_clean(card.first_mes), cap)}")
        if full and card.alternate_greetings:
            lines.append(f"- Alt greetings ({len(card.alternate_greetings)}):")
            for g in card.alternate_greetings:
                lines.append(f"  - {_truncate(_clean(g), cap)}")
        elif card.alternate_greetings:
            lines.append(f"- Alt greetings: {len(card.alternate_greetings)} (use --full to include)")
        if card.system_prompt:
            lines.append(f"- System prompt: {_truncate(_clean(card.system_prompt), cap)}")
        if card.mes_example:
            lines.append(f"- Example dialogue: {_truncate(_clean(card.mes_example), cap)}")
        if card.lorebook_entries:
            if full:
                lines.append(f"- Lorebook ({len(card.lorebook_entries)} entries):")
                for entry in card.lorebook_entries:
                    keys = ", ".join(entry.get("keys") or [])
                    content = _truncate(_clean(entry.get("content", "")), cap)
                    lines.append(f"  - [{keys}] {content}")
            else:
                lines.append(f"- Lorebook: {len(card.lorebook_entries)} entries (use --full to include)")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# Abbreviated field labels for the compact format, documented in a header
# block so both humans and the receiving model can decode them.
_COMPACT_LEGEND = (
    "N=name T=tags C=creator D=description P=personality S=scenario "
    "G=greeting AG=alt-greeting-count SYS=system-prompt EX=example-dialogue "
    "LB=lorebook-entry-count"
)


def to_compact(cards: Iterable[Card], *, full: bool = False, max_chars: int | None = _DEFAULT_MAX_CHARS) -> str:
    cards = list(cards)
    cap = None if full else max_chars
    lines: list[str] = [f"# {len(cards)} cards | fields: {_COMPACT_LEGEND}", ""]
    for i, card in enumerate(cards, 1):
        lines.append(f"#{i}")
        title = card.name or card.nickname or "(unnamed)"
        lines.append(f"N: {title}")
        if card.tags:
            lines.append(f"T: {', '.join(card.tags)}")
        if card.creator:
            lines.append(f"C: {card.creator}")
        if card.description:
            lines.append(f"D: {_truncate(_clean(card.description), cap)}")
        if card.personality:
            lines.append(f"P: {_truncate(_clean(card.personality), cap)}")
        if card.scenario:
            lines.append(f"S: {_truncate(_clean(card.scenario), cap)}")
        if card.first_mes:
            lines.append(f"G: {_truncate(_clean(card.first_mes), cap)}")
        if card.alternate_greetings:
            lines.append(f"AG: {len(card.alternate_greetings)}")
        if card.system_prompt:
            lines.append(f"SYS: {_truncate(_clean(card.system_prompt), cap)}")
        if full and card.mes_example:
            lines.append(f"EX: {_truncate(_clean(card.mes_example), cap)}")
        if card.lorebook_entries:
            lines.append(f"LB: {len(card.lorebook_entries)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _card_to_dict(card: Card, *, full: bool = True) -> dict:
    d = {
        "name": card.name,
        "nickname": card.nickname,
        "creator": card.creator,
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
    payload = {"count": len(cards), "cards": [_card_to_dict(c, full=full) for c in cards]}
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


WRITERS = {
    "md": to_markdown,
    "compact": to_compact,
    "json": to_json,
}
