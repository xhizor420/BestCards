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
from .conventions import analyze_conventions, build_convention_lines, build_example_dialogue_sample
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
    "This file is a REFERENCE CORPUS of {n} separate, existing character cards, "
    "curated as HIGH-QUALITY examples — not a random or average sample. It is "
    "not one character. Each numbered section below is a distinct card, "
    "included so you can compare them and identify patterns — recurring "
    "personality archetypes, what makes a first_mes hook effective, and how "
    "description/personality/scenario are typically structured. Use those "
    "patterns as inspiration to design a NEW, original character — but do NOT "
    "average these cards into a bland composite and do NOT copy any single "
    "card's text verbatim. Notice what makes individual cards distinctive and "
    "effective (a sharp hook, a specific quirk, a clear voice), and match that "
    "quality bar with something that has its own distinct identity. Card "
    "length in this corpus varies with complexity, not quality — a simple "
    "single-character card may run a couple thousand tokens while one built "
    "around several characters or an intricate scenario may run well past "
    "that. Do not treat any length here, including the range in the stats "
    "below, as a target: let your OWN character concept's actual complexity "
    "decide how long it needs to be, shorter or longer than what's typical "
    "in this corpus. Read every card below before responding — the response "
    "format you must use is given at the very end of this file, after the "
    "last card."
)

# Placed at the very end of the file (after every card), not in the
# opening preamble, so it's the last thing read before the model has to
# respond - the point in the file where format instructions have the most
# leverage. This exists because an earlier version's "don't copy this
# file's structure/labels" instruction, on its own, overcorrected: a model
# would default to unstructured prose with no fields at all instead of the
# six-field shape the whole point of this export is to teach it. This gives
# it the exact shape to fill in (explicitly NOT the multi-card "=== CARD
# i/N ===" wrapper this file uses to hold many cards) - and reminds it,
# right where it matters, to fill that shape in using what it just read,
# not fixed text.
#
# Two more things had to be spelled out, not just implied by the template
# existing: that the six fields should come back as ONE uninterrupted
# block (not prose with the fields scattered through it, and not the
# fields buried after paragraphs of commentary) so it's actually
# copy-paste-able as a finished card, and that a revision round should
# re-send the WHOLE card, not just the field that changed - otherwise
# every edit breaks the copy-paste-able property right back.
#
# Finally, the template is built PER CORPUS rather than being a fixed
# string, because "write it the way the cards above did" was still
# producing malformed output - worst of all in Example Dialogue, whose
# real shape (a <START> line, {{user}}:/{{char}}: turn prefixes, asterisk
# actions) is a *convention* a model won't reliably infer from a prose
# description of what the field is for. conventions.py measures what this
# particular corpus actually does, and that gets stated here as explicit
# rules with real percentages, plus a correctly-formatted sample - so the
# template shows the shape instead of describing it.


def _build_response_template_md(cards: list[Card]) -> str:
    conv = analyze_conventions(cards)
    convention_lines = build_convention_lines(conv)
    # Shown flush-left, exactly as the real cards write it - indenting it
    # to "nest" under the field label would teach an indentation the
    # corpus doesn't actually use.
    example_block = build_example_dialogue_sample(conv)

    house_style = ""
    if convention_lines:
        house_style = (
            "\n### House style of these cards — follow it\n\n"
            "These are measured from the cards above, not general advice. Match them:\n\n"
            + "\n".join(convention_lines)
            + "\n"
        )

    return f"""## ▼ REQUIRED RESPONSE FORMAT — follow this exactly ▼

Output the new character as ONE clean block, in exactly the field order
below, with each field's label written out and a blank line between
fields. No commentary, preamble, notes, or explanation before, between,
or after the fields — the block must be copy-paste-able as a finished
card. Do not include "## Card i/N" headers, corpus stats, or any other
part of this file's multi-card wrapper; that wrapper holds many reference
cards, it is not part of a single card.

Every one of the six fields is required. Do not skip, rename, merge, or
reorder them, and do not leave any as a one-line placeholder — Example
Dialogue in particular must be a real, fully written exchange in the
format shown below, not a description of one.
{house_style}
### The exact format to output

Name: <character name>

Description: <appearance, background, key facts>

Personality: <personality traits, quirks, how they typically act>

Scenario: <the setting or situation this character exists in>

First Message: <the character's opening message that starts the chat>

Example Dialogue:
{example_block}

### After the block

Write the whole block first, then on a new line after it, briefly ask
whether any changes are wanted. If changes are requested, output the FULL
card again in this same format — every field, not just the changed one —
so it stays copy-paste-ready after every revision.
"""


def _build_response_template_compact(cards: list[Card]) -> str:
    conv = analyze_conventions(cards)
    convention_lines = build_convention_lines(conv)
    example_sample = build_example_dialogue_sample(conv)

    parts = [
        "=== REQUIRED RESPONSE FORMAT — follow this exactly ===",
        "Output the new character as ONE clean block, exactly these six fields "
        "in this order, each label written out, a blank line between fields, and "
        "NO commentary before/between/after them, so it is copy-paste-able as a "
        'finished card. Do not include "=== CARD i/N ===" markers or a stats line '
        "— that wrapper holds many reference cards, it is not part of a single card. "
        "All six fields are required: do not skip, rename, merge, or reorder them, "
        "and do not leave any as a one-line placeholder — Example Dialogue must be "
        "a real, fully written exchange in the format shown, not a description of one.",
    ]
    if convention_lines:
        parts.append(
            "House style measured from the cards above — match it:\n" + "\n".join(convention_lines)
        )
    parts.append(
        "Format to output:\n\n"
        "Name: <character name>\n\n"
        "Description: <appearance, background, key facts>\n\n"
        "Personality: <traits, quirks, how they act>\n\n"
        "Scenario: <the setting or situation>\n\n"
        "First Message: <the character's opening message>\n\n"
        f"Example Dialogue:\n{example_sample}"
    )
    parts.append(
        "After the block, on a new line, briefly ask whether any changes are wanted. "
        "If changes are requested, output the FULL card again in this same format — "
        "every field, not just the changed one."
    )
    return "\n\n".join(parts)


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
    template_block = f"\n\n---\n\n{_build_response_template_md(cards)}"
    # Counted over body + template together so this number matches what
    # estimate_export()/the UI report for the same file - both cover the
    # complete file, not just the reference-data portion.
    tc = count_tokens(body + template_block, tokenizer)
    return body + f"\n---\n{tc.count:,} tokens ({tc.method})" + template_block


def _compact_card_lines(
    i: int, total: int, card: Card, cap: int | None, *, full: bool, extra_fields: frozenset[str]
) -> list[str]:
    """Labels here are short but spelled out (Name/Desc/Personality/...),
    not single-letter codes (N/D/P/...). The letter codes this format used
    to use turned out to be a real problem, not just an aesthetic one: a
    model reading a file full of "N: ... D: ... P: ..." would sometimes
    treat that as a template and echo the same cryptic labels back in its
    own response instead of writing a normal character description - and
    a human skimming the file couldn't tell what half the labels meant
    either. Spelled-out words read as plain labels, not a format to copy,
    while still costing only a few characters more than the letter codes
    did."""
    title = card.name or card.nickname or "(unnamed)"
    lines = [f"=== CARD {i}/{total} ===", f"Name: {title}"]
    if "tags" in extra_fields and card.tags:
        lines.append(f"Tags: {', '.join(card.tags)}")
    if card.description:
        lines.append(f"Desc: {_truncate(_clean(card.description), cap)}")
    if card.personality:
        lines.append(f"Personality: {_truncate(_clean(card.personality), cap)}")
    if card.scenario:
        lines.append(f"Scenario: {_truncate(_clean(card.scenario), cap)}")
    if card.first_mes:
        lines.append(f"Greeting: {_truncate(_clean(card.first_mes), cap)}")
    if card.mes_example:
        lines.append(f"Example: {_truncate(_clean(card.mes_example), cap)}")
    if "creator_notes" in extra_fields and card.creator_notes:
        lines.append(f"Notes: {_truncate(_clean(card.creator_notes), cap)}")
    if "alt_greetings" in extra_fields and card.alternate_greetings:
        lines.append(f"AltGreetings: {len(card.alternate_greetings)}")
    if "lorebook" in extra_fields and card.lorebook_entries:
        lines.append(f"Lorebook: {len(card.lorebook_entries)}")
    if "system_prompt" in extra_fields and full and card.system_prompt:
        lines.append(f"System: {_truncate(_clean(card.system_prompt), cap)}")
    if "post_history_instructions" in extra_fields and full and card.post_history_instructions:
        lines.append(f"PostHistory: {_truncate(_clean(card.post_history_instructions), cap)}")
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
        f"Stats: {stats_line}",
        "",
    ]
    for i, card in enumerate(cards, 1):
        lines.extend(_compact_card_lines(i, len(cards), card, cap, full=full, extra_fields=extra_fields))
    body = "\n".join(lines).rstrip() + "\n"
    template_block = f"\n\n{_build_response_template_compact(cards)}\n"
    tc = count_tokens(body + template_block, tokenizer)
    return body + f"\n# {tc.count:,} tokens ({tc.method})" + template_block


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
        "bloat_chars_removed": card.bloat_chars_removed,
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
        # Placed after "cards" (not in "note") so it's the last thing read
        # before responding - see _build_response_template_md's comment above.
        "response_template": {
            "instruction": (
                "When you respond, give back the character as ONE clean block using "
                "exactly these fields - the same six every card above has - with each "
                "label written out, a blank line between fields, and no commentary "
                "before/between/after them, so it can be copied and pasted as-is. All "
                "six are required: do not skip, rename, merge, or reorder them, and do "
                "not leave any as a one-line placeholder - mes_example in particular "
                "must be a real, fully written exchange following house_style below, "
                "not a description of one. Fill in your own content based on the idea "
                "you were given, not copied from any single card. After the block, "
                "briefly ask if any changes are wanted; if changes are requested, give "
                "back the FULL card again in that same clean block form - every field, "
                "not just the one that changed."
            ),
            "fields": ["name", "description", "personality", "scenario", "first_mes", "mes_example"],
            # Measured from these cards (see conventions.py), so the model
            # can match the corpus's real formatting instead of guessing.
            "house_style": build_convention_lines(analyze_conventions(cards)),
            "mes_example_format": build_example_dialogue_sample(analyze_conventions(cards)),
        },
    }
    # Counted over the whole payload including response_template, so this
    # matches what estimate_export()/the UI report for the same file.
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
