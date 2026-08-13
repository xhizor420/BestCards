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

Two independent knobs control cost, on top of format choice:

- `extra_fields`: which optional fields appear at all. The six core
  fields (name, description, personality, scenario, first_mes,
  mes_example) are the reason this tool exists and are always present.
  Everything else — tags, creator_notes, system_prompt,
  post_history_instructions, alt_greetings, lorebook — costs real tokens
  for content that's often not needed, so each is opt-in via
  `extra_fields`. Default is just `{"tags"}` (cheap, one line, useful
  archetype signal); creator_notes and the rest are off unless asked for.
- `full`: whether included prose is truncated to `max_chars`, and
  whether list fields (alt_greetings, lorebook) show their full text vs.
  just a count. This is orthogonal to which fields are included — you
  can include creator_notes and still have it truncated, or include
  nothing extra and still get untruncated core fields with --full.

Each writer builds its body from a per-card line-renderer
(_markdown_card_lines / _compact_card_lines) rather than inlining the
loop, so the web UI's per-card token estimate (estimate_export, below)
renders exactly the same text a real export would contain for that card —
no second implementation to drift out of sync.
"""

from __future__ import annotations

import json
import os
from typing import Iterable

from .cardspec import Card
from .stats import DEFAULT_TOKENIZER, build_corpus_stats, count_tokens, format_stats_block

# Fields whose text can be huge relative to how useful they are for
# cross-card pattern analysis. In digest (non --full) mode we cap them.
_DEFAULT_MAX_CHARS = 600

# Optional fields beyond the always-present core six. "tags" is on by
# default since it's a single cheap line with real archetype signal;
# everything else (including creator_notes) is opt-in.
ALL_EXTRA_FIELDS = ("tags", "creator_notes", "system_prompt", "post_history_instructions", "alt_greetings", "lorebook")
DEFAULT_EXTRA_FIELDS = frozenset({"tags"})

_CORPUS_PREAMBLE = (
    "This file is a REFERENCE CORPUS of {n} separate, existing character cards. "
    "It is not one character. Each numbered section below is a distinct card, "
    "included so you can compare them and identify patterns — recurring "
    "personality archetypes, what makes a first_mes hook effective, and how "
    "description/personality/scenario are typically structured. Use those "
    "patterns as inspiration to design a NEW, original character. Do not copy "
    "any single card's text verbatim."
)


def normalize_extra_fields(value) -> frozenset[str]:
    """Accepts an iterable of field names, or the strings "all"/"none",
    and returns a validated frozenset. Unknown field names are ignored
    rather than raising, since this is fed by both CLI text and UI
    checkboxes and a stray typo shouldn't abort a batch."""
    if value is None:
        return DEFAULT_EXTRA_FIELDS
    if isinstance(value, str):
        value = [v.strip() for v in value.split(",") if v.strip()]
    fields = {v.strip().lower() for v in value}
    if "all" in fields:
        return frozenset(ALL_EXTRA_FIELDS)
    if not fields or fields == {"none"}:
        return frozenset()
    return frozenset(f for f in fields if f in ALL_EXTRA_FIELDS)


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


def _markdown_card_lines(
    i: int, total: int, card: Card, cap: int | None, *, full: bool, extra_fields: frozenset[str]
) -> list[str]:
    title = card.name or card.nickname or "(unnamed)"
    lines = [f"## Card {i}/{total}: {title}", f"- (file: {_basename(card.source_file)})"]
    if "tags" in extra_fields and card.tags:
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
    if "creator_notes" in extra_fields and card.creator_notes:
        lines.append(f"- Creator notes: {_truncate(_clean(card.creator_notes), cap)}")
    if "alt_greetings" in extra_fields and card.alternate_greetings:
        if full:
            lines.append(f"- Alt greetings ({len(card.alternate_greetings)}):")
            for g in card.alternate_greetings:
                lines.append(f"  - {_truncate(_clean(g), cap)}")
        else:
            lines.append(f"- Alt greetings: {len(card.alternate_greetings)} (use --full to include text)")
    if "system_prompt" in extra_fields and card.system_prompt:
        lines.append(f"- System prompt: {_truncate(_clean(card.system_prompt), cap)}")
    if "post_history_instructions" in extra_fields and card.post_history_instructions:
        lines.append(f"- Post-history instructions: {_truncate(_clean(card.post_history_instructions), cap)}")
    if "lorebook" in extra_fields and card.lorebook_entries:
        if full:
            lines.append(f"- Lorebook ({len(card.lorebook_entries)} entries):")
            for entry in card.lorebook_entries:
                keys = ", ".join(entry.get("keys") or [])
                content = _truncate(_clean(entry.get("content", "")), cap)
                lines.append(f"  - [{keys}] {content}")
        else:
            lines.append(f"- Lorebook: {len(card.lorebook_entries)} entries (use --full to include text)")
    lines.append("")
    return lines


def to_markdown(
    cards: Iterable[Card],
    *,
    full: bool = False,
    max_chars: int | None = _DEFAULT_MAX_CHARS,
    extra_fields=DEFAULT_EXTRA_FIELDS,
    tokenizer: str = DEFAULT_TOKENIZER,
) -> str:
    cards = list(cards)
    cap = None if full else max_chars
    extra_fields = normalize_extra_fields(extra_fields)
    lines: list[str] = []
    lines.append(f"# Character Reference Corpus ({len(cards)} cards)")
    lines.append("")
    lines.append(_CORPUS_PREAMBLE.format(n=len(cards)))
    lines.append("")
    lines.append("## Corpus Stats")
    lines.append(format_stats_block(build_corpus_stats(cards, include_tags="tags" in extra_fields)))
    lines.append("")
    for i, card in enumerate(cards, 1):
        lines.extend(_markdown_card_lines(i, len(cards), card, cap, full=full, extra_fields=extra_fields))
    body = "\n".join(lines).rstrip() + "\n"
    tc = count_tokens(body, tokenizer)
    return body + f"\n---\n{tc.count:,} tokens ({tc.method})\n"


# Abbreviated field labels for the compact format, documented in a header
# block so both humans and the receiving model can decode them.
_COMPACT_LEGEND = (
    "N=name T=tags D=description P=personality S=scenario G=first_mes "
    "EX=example-dialogue CN=creator-notes AG=alt-greeting-count "
    "LB=lorebook-entry-count"
)


def _compact_card_lines(
    i: int, total: int, card: Card, cap: int | None, *, full: bool, extra_fields: frozenset[str]
) -> list[str]:
    title = card.name or card.nickname or "(unnamed)"
    lines = [f"=== CARD {i}/{total} ===", f"N: {title}"]
    if "tags" in extra_fields and card.tags:
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
    if "creator_notes" in extra_fields and card.creator_notes:
        lines.append(f"CN: {_truncate(_clean(card.creator_notes), cap)}")
    if "alt_greetings" in extra_fields and card.alternate_greetings:
        lines.append(f"AG: {len(card.alternate_greetings)}")
    if "lorebook" in extra_fields and card.lorebook_entries:
        lines.append(f"LB: {len(card.lorebook_entries)}")
    if "system_prompt" in extra_fields and full and card.system_prompt:
        lines.append(f"SYS: {_truncate(_clean(card.system_prompt), cap)}")
    if "post_history_instructions" in extra_fields and full and card.post_history_instructions:
        lines.append(f"PHI: {_truncate(_clean(card.post_history_instructions), cap)}")
    lines.append("")
    return lines


def to_compact(
    cards: Iterable[Card],
    *,
    full: bool = False,
    max_chars: int | None = _DEFAULT_MAX_CHARS,
    extra_fields=DEFAULT_EXTRA_FIELDS,
    tokenizer: str = DEFAULT_TOKENIZER,
) -> str:
    cards = list(cards)
    cap = None if full else max_chars
    extra_fields = normalize_extra_fields(extra_fields)
    stats_line = format_stats_block(build_corpus_stats(cards, include_tags="tags" in extra_fields), compact=True)
    lines: list[str] = [
        _CORPUS_PREAMBLE.format(n=len(cards)),
        f"Fields: {_COMPACT_LEGEND}",
        f"Stats: {stats_line}",
        "",
    ]
    for i, card in enumerate(cards, 1):
        lines.extend(_compact_card_lines(i, len(cards), card, cap, full=full, extra_fields=extra_fields))
    body = "\n".join(lines).rstrip() + "\n"
    tc = count_tokens(body, tokenizer)
    return body + f"\n# {tc.count:,} tokens ({tc.method})\n"


def card_to_dict(card: Card, *, full: bool = True, extra_fields=ALL_EXTRA_FIELDS) -> dict:
    extra_fields = normalize_extra_fields(extra_fields)
    d = {
        "name": card.name,
        "nickname": card.nickname,
        "character_version": card.character_version,
        "description": card.description,
        "personality": card.personality,
        "scenario": card.scenario,
        "first_mes": card.first_mes,
        "mes_example": card.mes_example if full else bool(card.mes_example),
        "source": card.source,
        "spec_version": card.spec_version,
        "source_keyword": card.source_keyword,
        "source_file": card.source_file,
    }
    if "tags" in extra_fields:
        d["tags"] = card.tags
    if "creator_notes" in extra_fields:
        d["creator_notes"] = card.creator_notes
    if "system_prompt" in extra_fields:
        d["system_prompt"] = card.system_prompt
    if "post_history_instructions" in extra_fields:
        d["post_history_instructions"] = card.post_history_instructions
    if "alt_greetings" in extra_fields:
        d["alternate_greetings"] = card.alternate_greetings if full else len(card.alternate_greetings)
    if "lorebook" in extra_fields:
        d["lorebook_entries"] = card.lorebook_entries if full else len(card.lorebook_entries)
    return d


def to_json(
    cards: Iterable[Card],
    *,
    full: bool = False,
    max_chars: int | None = None,
    extra_fields=DEFAULT_EXTRA_FIELDS,
    tokenizer: str = DEFAULT_TOKENIZER,
) -> str:
    del max_chars  # JSON output is governed by --full only, not truncation
    cards = list(cards)
    extra_fields = normalize_extra_fields(extra_fields)
    payload = {
        "note": _CORPUS_PREAMBLE.format(n=len(cards)),
        "count": len(cards),
        "stats": build_corpus_stats(cards, include_tags="tags" in extra_fields),
        "cards": [card_to_dict(c, full=full, extra_fields=extra_fields) for c in cards],
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    tc = count_tokens(text, tokenizer)
    payload["tokens"] = tc.count
    payload["token_method"] = tc.method
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


WRITERS = {
    "md": to_markdown,
    "compact": to_compact,
    "json": to_json,
}


def estimate_export(
    cards: list[Card],
    *,
    format: str,
    full: bool = False,
    max_chars: int | None = _DEFAULT_MAX_CHARS,
    extra_fields=DEFAULT_EXTRA_FIELDS,
    tokenizer: str = DEFAULT_TOKENIZER,
) -> dict:
    """Token estimate for the whole export plus each card's own marginal
    contribution (the size of just its section, not shared preamble/stats),
    so a UI can show "this card costs ~N tokens" and let someone drop the
    expensive/low-value ones before exporting."""
    if format not in WRITERS:
        raise ValueError(f"unknown format {format!r}")

    extra_fields = normalize_extra_fields(extra_fields)
    total_text = WRITERS[format](cards, full=full, max_chars=max_chars, extra_fields=extra_fields, tokenizer=tokenizer)
    total_tc = count_tokens(total_text, tokenizer)
    cap = None if full else max_chars

    per_card = []
    for i, card in enumerate(cards, 1):
        if format == "compact":
            block = "\n".join(_compact_card_lines(i, len(cards), card, cap, full=full, extra_fields=extra_fields))
        elif format == "md":
            block = "\n".join(_markdown_card_lines(i, len(cards), card, cap, full=full, extra_fields=extra_fields))
        else:  # json
            block = json.dumps(card_to_dict(card, full=full, extra_fields=extra_fields), ensure_ascii=False)
        card_tc = count_tokens(block, tokenizer)
        per_card.append({"index": i, "name": card.name or card.nickname or "(unnamed)", "tokens": card_tc.count})

    return {"total_tokens": total_tc.count, "method": total_tc.method, "cards": per_card}
