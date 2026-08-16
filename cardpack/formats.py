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
from .conventions import (
    analyze_conventions,
    build_cast_note,
    build_convention_lines,
    build_coverage_notes,
    build_description_skeleton,
    build_example_dialogue_sample,
    build_field_guidance,
    build_style_sections,
)
from .selection import exemplar_names
from .stats import (
    DEFAULT_TOKENIZER,
    build_corpus_stats,
    context_warning_ui,
    count_tokens,
    format_stats_block,
)

# Fields whose text can be huge relative to how useful they are for
# cross-card pattern analysis. In digest (non --full) mode we cap them.
_DEFAULT_MAX_CHARS = 600

# How many of the best-ranked cards are shown COMPLETE before the rest are
# trimmed to `max_chars`.
#
# A flat cap across a whole corpus forces a false choice. On a real 57-card
# corpus with ~8,400-char structured descriptions, a 600-char cap showed a
# model 7% of each card and only 17 of 125 `>Section` headers - it was
# being told to build a six-section dossier it had never seen completed.
# But dropping to a handful of full cards throws away the breadth that
# makes the corpus a useful database of what these characters look like.
#
# Both matter, and they want different things: STRUCTURE is learned from a
# few complete examples, BREADTH from many partial ones. So the top-ranked
# cards are rendered whole and everything after them is trimmed, which
# keeps a 100+ card corpus affordable while still showing real, finished
# structure. Corpus stats and detected conventions are always computed
# over every card, not just the untrimmed ones.
_DEFAULT_FULL_TOP = 10

# Optional fields beyond the always-present core six. "tags" is on by
# default since it's a single cheap line with real archetype signal;
# everything else (including creator_notes) is opt-in.
ALL_EXTRA_FIELDS = ("tags", "creator_notes", "system_prompt", "post_history_instructions", "alt_greetings", "lorebook")
DEFAULT_EXTRA_FIELDS = frozenset({"tags"})

# Shown in the stats block so it's immediately visible which fields the
# corpus actually populates - a corpus with mes_example 0/10 cannot teach
# a model to write one, and that's worth knowing before wondering why the
# generated card's example dialogue is weak.
_COVERAGE_LABELS = (
    ("description", "description"),
    ("personality", "personality"),
    ("scenario", "scenario"),
    ("first_mes", "first_mes"),
    ("mes_example", "mes_example"),
    ("tags", "tags"),
)

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
    "format you must use appears both immediately below and again at the very "
    "end of this file; the two copies are identical."
)

# The template is emitted TWICE - once before the cards, once after them -
# and the duplication is deliberate.
#
# End position is where format instructions have the most leverage: it's
# the last thing read before responding. But a real corpus runs to
# hundreds of thousands of tokens, and files that size rarely reach a
# model whole. Chat UIs truncate them, attachment pipelines chunk and
# retrieve only some passages, and long-context attention thins out in
# the middle. In every one of those failure modes, instructions that
# exist ONLY after the last card are the first thing lost - and losing
# them looks exactly like a model ignoring the format, which is the
# complaint that motivated the template in the first place.
#
# So it opens the file too. The cost is a fraction of a percent of a
# large export, and it means no single truncation point can strip the
# instructions.
_TEMPLATE_REPEAT_NOTE = (
    "The same instructions are repeated verbatim at the end of this file, after the last "
    "card. Read the cards in between before you use them."
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
    description_block = build_description_skeleton(conv)
    guidance = build_field_guidance(conv)

    style = build_style_sections(conv)
    house_style = ""
    if style["shared"]:
        house_style += (
            "\n### How these cards are written — shared by nearly all of them\n\n"
            "Measured from the corpus above, not imposed from outside. These are simply the "
            "local conventions; follow them:\n\n" + "\n".join(style["shared"]) + "\n"
        )
    if style["approaches"]:
        house_style += (
            "\n### How these cards are organised — approaches available to you\n\n"
            "Every card above was picked as a good one, so the counts below tell you how "
            "COMMON an approach is, never how good it is — an approach used by a handful of "
            "these cards is still an approach that worked in cards worth keeping. The list "
            "runs most-organised first; **default to the first one** unless the character "
            "you're building genuinely calls for something looser.\n\n"
            + "\n".join(style["approaches"])
            + "\n"
        )
    if style["touches"]:
        house_style += (
            "\n### Optional touches some of these cards use\n\n"
            "Independent of the structure you pick — take any that suit the character, "
            "or none:\n\n" + "\n".join(style["touches"]) + "\n"
        )
    if style["scale"]:
        house_style += (
            "\n### The scale these cards work at\n\n" + "\n".join(style["scale"]) + "\n"
        )
    cast_note = build_cast_note(conv)
    if cast_note:
        house_style += (
            "\n### Solo cards and group cards\n\n" + "\n".join(cast_note) + "\n"
        )
    # Point at the clearest worked examples rather than leaving a reader to
    # rank 50+ cards itself - the top-scoring cards are the ones that show
    # the recommended structure most completely.
    exemplars = exemplar_names(cards)
    if len(exemplars) >= 2:
        listed = ", ".join(f"**{n}**" for n in exemplars)
        house_style += (
            f"\n### Clearest worked examples\n\n"
            f"If you only study a few closely, study these — they demonstrate the structure "
            f"and depth above most completely: {listed}.\n"
        )

    field_notes = "\n".join(
        f"- **{g['label']}** — {g['note']}" for g in guidance if g["note"]
    )
    if field_notes:
        field_notes = (
            "\n### How these cards use the fields\n\n"
            "Let the corpus lead here rather than filling every slot for its own sake:\n\n"
            + field_notes
            + "\n"
        )

    # Only pre-fill placeholders for fields the corpus actually demonstrates;
    # ones it never uses are shown as optional so the writer isn't pushed into
    # inventing a shape the reference material never showed.
    def _slot(field: str, label: str, placeholder: str) -> str:
        entry = next((g for g in guidance if g["field"] == field), None)
        if entry is not None and not entry["used"] and entry["total"] >= 3:
            return f"{label}: <optional — see the note above>"
        return f"{label}: {placeholder}"

    return f"""## ▼ WRITING THE NEW CHARACTER — guided by the cards above ▼

Use the corpus above as your reference for voice, structure, and depth.
Where those cards show a clear convention, follow it; where they don't,
use your own judgement and keep everything consistent with the rest.

Present the finished character as ONE clean block, each field's label
written out, a blank line between fields, and no commentary or
explanation mixed in around them — that keeps it copy-paste-able as a
finished card. Leave out "## Card i/N" headers and the corpus stats;
that wrapper exists to hold many reference cards and isn't part of a
single one.

Aim for the same depth as the cards above — they're detailed and
specific, and that's most of what makes them good. Where a field calls
for real content (an actual example exchange, an actual opening message),
write the real thing rather than a description of it.
{house_style}{field_notes}
### Shape to follow

Name: <character name>

Description:
{description_block}

{_slot("personality", "Personality", "<personality traits, quirks, how they typically act>")}

{_slot("scenario", "Scenario", "<the setting or situation this character exists in>")}

{_slot("first_mes", "First Message", "<the character's opening message that starts the chat>")}

Example Dialogue:
{example_block}

### After the block

Write the whole block first, then on a new line after it, briefly ask
whether any changes are wanted. If changes are requested, give back the
FULL card again in this same shape — every field, not just the changed
one — so it stays copy-paste-ready after every revision.
"""


def _build_response_template_compact(cards: list[Card]) -> str:
    conv = analyze_conventions(cards)
    convention_lines = build_convention_lines(conv)
    example_sample = build_example_dialogue_sample(conv)
    description_block = build_description_skeleton(conv)
    guidance = build_field_guidance(conv)

    parts = [
        "=== WRITING THE NEW CHARACTER — guided by the cards above ===",
        "Use the corpus above as your reference for voice, structure and depth. Where "
        "those cards show a clear convention, follow it; where they don't, use your own "
        "judgement and stay consistent with the rest. Present the finished character as "
        "ONE clean block, each label written out, a blank line between fields, and no "
        "commentary mixed in around them, so it stays copy-paste-able as a finished card. "
        'Leave out "=== CARD i/N ===" markers and the stats line — that wrapper holds many '
        "reference cards and isn't part of a single one. Aim for the same depth as the "
        "cards above, and where a field calls for real content (an actual example exchange, "
        "an actual opening message), write the real thing rather than a description of it.",
    ]
    style = build_style_sections(conv)
    if style["shared"]:
        parts.append(
            "How these cards are written — shared by nearly all of them, so follow them:\n"
            + "\n".join(style["shared"])
        )
    if style["approaches"]:
        parts.append(
            "How these cards are organised — approaches available to you. Every card above was "
            "picked as a good one, so the counts tell you how COMMON an approach is, never how "
            "good it is. Most-organised first; default to the first one unless the character "
            "genuinely calls for something looser:\n" + "\n".join(style["approaches"])
        )
    if style["touches"]:
        parts.append(
            "Optional touches some of these cards use — independent of the structure you pick, "
            "take any that suit the character or none:\n" + "\n".join(style["touches"])
        )
    if style["scale"]:
        parts.append("The scale these cards work at:\n" + "\n".join(style["scale"]))
    _cast_note = build_cast_note(conv)
    if _cast_note:
        parts.append("Solo cards and group cards:\n" + "\n".join(_cast_note))
    _exemplars = exemplar_names(cards)
    if len(_exemplars) >= 2:
        parts.append(
            "Clearest worked examples — if you only study a few closely, study these: "
            + ", ".join(_exemplars)
            + "."
        )
    field_notes = "\n".join(f"- {g['label']}: {g['note']}" for g in guidance if g["note"])
    if field_notes:
        parts.append(
            "How these cards use the fields (let the corpus lead rather than filling "
            "every slot for its own sake):\n" + field_notes
        )

    def _slot(field: str, label: str, placeholder: str) -> str:
        entry = next((g for g in guidance if g["field"] == field), None)
        if entry is not None and not entry["used"] and entry["total"] >= 3:
            return f"{label}: <optional — see the note above>"
        return f"{label}: {placeholder}"

    parts.append(
        "Shape to follow:\n\n"
        "Name: <character name>\n\n"
        f"Description:\n{description_block}\n\n"
        f"{_slot('personality', 'Personality', '<traits, quirks, how they act>')}\n\n"
        f"{_slot('scenario', 'Scenario', '<the setting or situation>')}\n\n"
        f"{_slot('first_mes', 'First Message', '<the character opening message>')}\n\n"
        f"Example Dialogue:\n{example_sample}"
    )
    parts.append(
        "After the block, on a new line, briefly ask whether any changes are wanted. "
        "If changes are requested, give back the FULL card again in this same shape — "
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


def _cap_for_rank(index: int, cap: int | None, full_top: int) -> int | None:
    """None (untrimmed) for the first `full_top` cards, else `cap`.

    `index` is 1-based, matching the card numbering in the output.
    """
    if cap is None or full_top <= 0:
        return cap
    return None if index <= full_top else cap


def _markdown_card_lines(
    i: int, total: int, card: Card, cap: int | None, *, extra_fields: frozenset[str]
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
    # Opting a field in always yields its CONTENT (truncated per `cap`).
    # These list/extra fields used to collapse to a bare count unless
    # `full` was also set, which made checking e.g. "Lorebook" in the UI
    # look like it did nothing - see _content_for_opted_in_fields note in
    # the module docstring.
    if "alt_greetings" in extra_fields and card.alternate_greetings:
        lines.append(f"- Alt greetings ({len(card.alternate_greetings)}):")
        for g in card.alternate_greetings:
            lines.append(f"  - {_truncate(_clean(g), cap)}")
    if "system_prompt" in extra_fields and card.system_prompt:
        lines.append(f"- System prompt: {_truncate(_clean(card.system_prompt), cap)}")
    if "post_history_instructions" in extra_fields and card.post_history_instructions:
        lines.append(f"- Post-history instructions: {_truncate(_clean(card.post_history_instructions), cap)}")
    if "lorebook" in extra_fields and card.lorebook_entries:
        lines.append(f"- Lorebook ({len(card.lorebook_entries)} entries):")
        for entry in card.lorebook_entries:
            keys = ", ".join(entry.get("keys") or [])
            content = _truncate(_clean(entry.get("content", "")), cap)
            lines.append(f"  - [{keys}] {content}")
    lines.append("")
    return lines


def to_markdown(
    cards: Iterable[Card],
    *,
    full: bool = False,
    max_chars: int | None = _DEFAULT_MAX_CHARS,
    extra_fields=DEFAULT_EXTRA_FIELDS,
    tokenizer: str = DEFAULT_TOKENIZER,
    full_top: int = _DEFAULT_FULL_TOP,
) -> str:
    cards = list(cards)
    cap = None if full else max_chars
    extra_fields = normalize_extra_fields(extra_fields)
    lines: list[str] = []
    lines.append(f"# Character Reference Corpus ({len(cards)} cards)")
    lines.append("")
    lines.append(_CORPUS_PREAMBLE.format(n=len(cards)))
    lines.append("")
    trimmed = 0 if (full or cap is None) else max(0, len(cards) - max(full_top, 0))
    if trimmed:
        shown = len(cards) - trimmed
        lines.append(
            f"The first {shown} cards below are shown COMPLETE — study those for structure "
            f"and depth. The remaining {trimmed} are trimmed to ~{cap:,} characters per field "
            f"to keep this file affordable; they are here for breadth (range of archetypes, "
            f"tags and openings), not as full examples. The stats and conventions below are "
            f"measured across all {len(cards)} cards."
        )
        lines.append("")
    lines.append("## Corpus Stats")
    lines.append(format_stats_block(build_corpus_stats(cards, include_tags="tags" in extra_fields)))
    coverage = analyze_conventions(cards)["field_coverage"]
    if cards:
        filled = ", ".join(f"{name} {coverage.get(key, 0)}/{len(cards)}" for key, name in _COVERAGE_LABELS)
        lines.append(f"- Field coverage: {filled}")
    lines.append("")
    template = _build_response_template_md(cards)
    if cards:
        lines.append("---")
        lines.append("")
        lines.append(template)
        lines.append(f"*{_TEMPLATE_REPEAT_NOTE}*")
        lines.append("")
        lines.append("---")
        lines.append("")
    for i, card in enumerate(cards, 1):
        lines.extend(
            _markdown_card_lines(
                i, len(cards), card, _cap_for_rank(i, cap, full_top), extra_fields=extra_fields
            )
        )
    body = "\n".join(lines).rstrip() + "\n"
    template_block = f"\n\n---\n\n{template}"
    # Counted over body + template together so this number matches what
    # estimate_export()/the UI report for the same file - both cover the
    # complete file, not just the reference-data portion.
    tc = count_tokens(body + template_block, tokenizer)
    return body + f"\n---\n{tc.count:,} tokens ({tc.method})" + template_block


def _compact_card_lines(
    i: int, total: int, card: Card, cap: int | None, *, extra_fields: frozenset[str]
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
    # As in _markdown_card_lines: an opted-in field always yields its
    # content. Previously alt_greetings/lorebook printed only a bare count
    # here (never their text, even with `full`), and system_prompt /
    # post_history_instructions were silently dropped entirely unless
    # `full` was set - so ticking those boxes in the UI appeared to do
    # nothing at all.
    if "alt_greetings" in extra_fields and card.alternate_greetings:
        lines.append(f"AltGreetings ({len(card.alternate_greetings)}):")
        for g in card.alternate_greetings:
            lines.append(f"- {_truncate(_clean(g), cap)}")
    if "lorebook" in extra_fields and card.lorebook_entries:
        lines.append(f"Lorebook ({len(card.lorebook_entries)}):")
        for entry in card.lorebook_entries:
            keys = ", ".join(entry.get("keys") or [])
            content = _truncate(_clean(entry.get("content", "")), cap)
            lines.append(f"- [{keys}] {content}")
    if "system_prompt" in extra_fields and card.system_prompt:
        lines.append(f"System: {_truncate(_clean(card.system_prompt), cap)}")
    if "post_history_instructions" in extra_fields and card.post_history_instructions:
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
    full_top: int = _DEFAULT_FULL_TOP,
) -> str:
    cards = list(cards)
    cap = None if full else max_chars
    extra_fields = normalize_extra_fields(extra_fields)
    stats_line = format_stats_block(build_corpus_stats(cards, include_tags="tags" in extra_fields), compact=True)
    _trimmed = 0 if (full or cap is None) else max(0, len(cards) - max(full_top, 0))
    lines: list[str] = [_CORPUS_PREAMBLE.format(n=len(cards))]
    if _trimmed:
        lines.append(
            f"NOTE: the first {len(cards) - _trimmed} cards are COMPLETE (study those for "
            f"structure); the remaining {_trimmed} are trimmed to ~{cap:,} chars/field for "
            f"breadth only. Stats and conventions cover all {len(cards)}."
        )
    lines += [f"Stats: {stats_line}", ""]
    template = _build_response_template_compact(cards)
    if cards:
        lines += [template, f"({_TEMPLATE_REPEAT_NOTE})", ""]
    for i, card in enumerate(cards, 1):
        lines.extend(
            _compact_card_lines(
                i, len(cards), card, _cap_for_rank(i, cap, full_top), extra_fields=extra_fields
            )
        )
    body = "\n".join(lines).rstrip() + "\n"
    template_block = f"\n\n{template}\n"
    tc = count_tokens(body + template_block, tokenizer)
    return body + f"\n# {tc.count:,} tokens ({tc.method})" + template_block


def card_to_dict(
    card: Card, *, full: bool = True, max_chars: int | None = None, extra_fields=ALL_EXTRA_FIELDS
) -> dict:
    """Serialize a Card. Every key keeps a STABLE type regardless of
    `full` - strings stay strings, lists stay lists - because this is also
    the web UI's wire format, and Card.from_dict() reads it straight back.
    An earlier version collapsed mes_example to a bool and
    alternate_greetings/lorebook_entries to ints when full=False, which
    silently corrupted any round-trip through those values. `full` (and
    `max_chars`) now only control truncation, never shape.
    """
    extra_fields = normalize_extra_fields(extra_fields)
    cap = None if full else max_chars

    def _t(text: str) -> str:
        return _truncate(_clean(text), cap)

    d = {
        "name": card.name,
        "nickname": card.nickname,
        "character_version": card.character_version,
        "description": _t(card.description),
        "personality": _t(card.personality),
        "scenario": _t(card.scenario),
        "first_mes": _t(card.first_mes),
        "mes_example": _t(card.mes_example),
        "source": card.source,
        "spec_version": card.spec_version,
        "source_keyword": card.source_keyword,
        "source_file": card.source_file,
        "bloat_chars_removed": card.bloat_chars_removed,
    }
    if "tags" in extra_fields:
        d["tags"] = card.tags
    if "creator_notes" in extra_fields:
        d["creator_notes"] = _t(card.creator_notes)
    if "system_prompt" in extra_fields:
        d["system_prompt"] = _t(card.system_prompt)
    if "post_history_instructions" in extra_fields:
        d["post_history_instructions"] = _t(card.post_history_instructions)
    if "alt_greetings" in extra_fields:
        d["alternate_greetings"] = [_t(g) for g in card.alternate_greetings]
    if "lorebook" in extra_fields:
        d["lorebook_entries"] = [{**e, "content": _t(e.get("content", ""))} for e in card.lorebook_entries]
    return d


def to_json(
    cards: Iterable[Card],
    *,
    full: bool = False,
    max_chars: int | None = _DEFAULT_MAX_CHARS,
    extra_fields=DEFAULT_EXTRA_FIELDS,
    tokenizer: str = DEFAULT_TOKENIZER,
    full_top: int = _DEFAULT_FULL_TOP,
) -> str:
    cards = list(cards)
    extra_fields = normalize_extra_fields(extra_fields)
    _analysis = analyze_conventions(cards)
    _conv = {
        "house_style": build_convention_lines(_analysis),
        "description_format": build_description_skeleton(_analysis),
        "mes_example_format": build_example_dialogue_sample(_analysis),
        "coverage_notes": build_coverage_notes(_analysis),
    }
    payload = {
        "note": _CORPUS_PREAMBLE.format(n=len(cards)),
        "count": len(cards),
        "stats": build_corpus_stats(cards, include_tags="tags" in extra_fields),
        "field_coverage": _analysis["field_coverage"],
        "cards": [
            card_to_dict(
                c,
                full=full or i <= full_top,
                max_chars=max_chars,
                extra_fields=extra_fields,
            )
            for i, c in enumerate(cards, 1)
        ],
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
            "house_style": _conv["house_style"],
            "description_format": _conv["description_format"],
            "mes_example_format": _conv["mes_example_format"],
            "not_demonstrated_by_this_corpus": _conv["coverage_notes"],
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
    full_top: int = _DEFAULT_FULL_TOP,
) -> dict:
    """Token estimate for the whole export plus each card's own marginal
    contribution (the size of just its section, not shared preamble/stats),
    so a UI can show "this card costs ~N tokens" and let someone drop the
    expensive/low-value ones before exporting."""
    if format not in WRITERS:
        raise ValueError(f"unknown format {format!r}")

    extra_fields = normalize_extra_fields(extra_fields)
    total_text = WRITERS[format](
        cards, full=full, max_chars=max_chars, extra_fields=extra_fields, tokenizer=tokenizer, full_top=full_top
    )
    total_tc = count_tokens(total_text, tokenizer)
    cap = None if full else max_chars

    per_card = []
    for i, card in enumerate(cards, 1):
        rank_cap = _cap_for_rank(i, cap, full_top)
        if format == "compact":
            block = "\n".join(_compact_card_lines(i, len(cards), card, rank_cap, extra_fields=extra_fields))
        elif format == "md":
            block = "\n".join(_markdown_card_lines(i, len(cards), card, rank_cap, extra_fields=extra_fields))
        else:  # json
            block = json.dumps(
                card_to_dict(
                    card, full=full or i <= full_top, max_chars=max_chars, extra_fields=extra_fields
                ),
                ensure_ascii=False,
            )
        card_tc = count_tokens(block, tokenizer)
        per_card.append({"index": i, "name": card.name or card.nickname or "(unnamed)", "tokens": card_tc.count})

    return {
        "total_tokens": total_tc.count,
        "method": total_tc.method,
        "cards": per_card,
        # Empty unless the export outgrows a single prompt. Phrased for the
        # UI's controls rather than the CLI's flags, since that's where the
        # reader is when they see it.
        "context_warning": context_warning_ui(total_tc.count, card_count=len(cards)),
    }
