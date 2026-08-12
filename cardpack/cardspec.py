"""Parse and normalize Character Card V1 / V2 / V3 payloads.

Background (for anyone maintaining this later):

- V1 (old TavernAI): the PNG text chunk keyword "chara" holds base64 JSON
  that IS the character object directly (no wrapper): name, description,
  personality, scenario, first_mes, mes_example, ...
- V2 (chara_card_v2, used by SillyTavern/Chub/JanitorAI exports): keyword
  "chara" holds base64 JSON shaped like
  {"spec": "chara_card_v2", "spec_version": "2.0", "data": {...}}
- V3 (chara_card_v3): adds a *second* chunk, keyword "ccv3", with the same
  wrapper shape but spec_version "3.0" and extra fields (assets, nickname,
  source, group_only_greetings, creation_date, ...). Well-behaved V3
  exporters still include a V2-compatible "chara" chunk as a fallback, so
  when both are present we prefer "ccv3".

This module turns whichever of those we find into one flat, canonical
dict so the rest of the tool never has to think about spec version again.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass, field
from typing import Any

from .png_chunks import TextChunk

# Keys that legitimately hold card JSON, in preference order.
CARD_KEYWORDS = ("ccv3", "chara")

# Field name -> list of source aliases seen across exporters/spec versions.
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("name",),
    "nickname": ("nickname",),
    "description": ("description",),
    "personality": ("personality",),
    "scenario": ("scenario",),
    "first_mes": ("first_mes", "greeting"),
    "mes_example": ("mes_example", "example_dialogue"),
    "system_prompt": ("system_prompt",),
    "post_history_instructions": ("post_history_instructions",),
    "creator_notes": ("creator_notes", "creatorcomment"),
    "creator": ("creator",),
    "character_version": ("character_version",),
    "tags": ("tags",),
    "alternate_greetings": ("alternate_greetings",),
    "group_only_greetings": ("group_only_greetings",),
    "source": ("source",),
}


@dataclass
class Card:
    """Canonical, spec-version-agnostic view of a character card."""

    name: str = ""
    nickname: str = ""
    description: str = ""
    personality: str = ""
    scenario: str = ""
    first_mes: str = ""
    mes_example: str = ""
    system_prompt: str = ""
    post_history_instructions: str = ""
    creator_notes: str = ""
    creator: str = ""
    character_version: str = ""
    tags: list[str] = field(default_factory=list)
    alternate_greetings: list[str] = field(default_factory=list)
    group_only_greetings: list[str] = field(default_factory=list)
    lorebook_entries: list[dict[str, Any]] = field(default_factory=list)
    source: list[str] = field(default_factory=list)

    spec_version: str = "unknown"  # "1.0" | "2.0" | "3.0"
    source_keyword: str = ""  # which PNG chunk keyword the data came from
    source_file: str = ""

    def is_empty(self) -> bool:
        return not (self.name or self.description or self.personality or self.first_mes)


class CardExtractionError(ValueError):
    """Raised when a PNG has no usable character-card payload."""


def _decode_payload(raw_text: str) -> Any:
    """A card chunk's text is normally base64 JSON, but be forgiving:
    some tools have shipped raw JSON (no base64) in the wild."""
    stripped = raw_text.strip()
    try:
        decoded_bytes = base64.b64decode(stripped, validate=False)
        return json.loads(decoded_bytes.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        pass
    # Fall back to treating the chunk text as literal JSON.
    return json.loads(stripped)


def _coerce_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    return []


def _extract_lorebook_entries(data: dict[str, Any]) -> list[dict[str, Any]]:
    book = data.get("character_book")
    if not isinstance(book, dict):
        return []
    entries = book.get("entries")
    if not isinstance(entries, list):
        return []
    out = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        out.append(
            {
                "keys": entry.get("keys") or entry.get("key") or [],
                "content": entry.get("content", ""),
                "comment": entry.get("comment", ""),
            }
        )
    return out


def _first_present(data: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for key in aliases:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def normalize_card_data(data: dict[str, Any], spec_version: str, source_keyword: str) -> Card:
    kwargs: dict[str, Any] = {"spec_version": spec_version, "source_keyword": source_keyword}
    for field_name, aliases in _FIELD_ALIASES.items():
        value = _first_present(data, aliases)
        if field_name in ("tags", "alternate_greetings", "group_only_greetings", "source"):
            kwargs[field_name] = _coerce_str_list(value)
        elif value is not None:
            kwargs[field_name] = str(value)
    kwargs["lorebook_entries"] = _extract_lorebook_entries(data)
    return Card(**kwargs)


def parse_card_payload(text_chunks: list[TextChunk]) -> Card:
    """Pick the best available card chunk (preferring V3's "ccv3" over the
    V2/V1 "chara" fallback) and normalize it into a Card."""
    by_keyword = {c.keyword: c.text for c in text_chunks}

    for keyword in CARD_KEYWORDS:
        raw_text = by_keyword.get(keyword)
        if not raw_text:
            continue
        try:
            payload = _decode_payload(raw_text)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue

        spec = payload.get("spec", "")
        if isinstance(spec, str) and spec.startswith("chara_card"):
            data = payload.get("data")
            if not isinstance(data, dict):
                continue
            spec_version = str(payload.get("spec_version") or ("3.0" if "v3" in spec else "2.0"))
        else:
            # Unwrapped V1-style payload: the object itself is the card.
            data = payload
            spec_version = "1.0"

        card = normalize_card_data(data, spec_version, keyword)
        if not card.is_empty():
            return card

    raise CardExtractionError(
        f"no usable character card data found (looked for keywords: {', '.join(CARD_KEYWORDS)})"
    )
