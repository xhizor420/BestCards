from __future__ import annotations

import base64
import json
import struct
import zlib

import pytest

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(chunk_type: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)


def build_png(text_chunks: list[tuple[str, str, str]]) -> bytes:
    """Build a minimal (fake but structurally valid) PNG with given text
    chunks. Each entry is (kind, keyword, text) where kind is
    'tEXt' | 'zTXt' | 'iTXt'. Image data itself is a dummy IHDR; nothing
    reads pixel data so it doesn't need to decode as a real image.
    """
    out = bytearray(PNG_SIGNATURE)
    # width=1 height=1 bitdepth=8 colortype=2 compression=0 filter=0 interlace=0
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    out += _chunk(b"IHDR", ihdr)

    for kind, keyword, text in text_chunks:
        kw = keyword.encode("latin-1")
        if kind == "tEXt":
            data = kw + b"\x00" + text.encode("latin-1")
            out += _chunk(b"tEXt", data)
        elif kind == "zTXt":
            compressed = zlib.compress(text.encode("latin-1"))
            data = kw + b"\x00" + b"\x00" + compressed
            out += _chunk(b"zTXt", data)
        elif kind == "iTXt":
            payload = text.encode("utf-8")
            data = kw + b"\x00" + b"\x00" + b"\x00" + b"\x00" + b"\x00" + payload
            out += _chunk(b"iTXt", data)
        else:
            raise ValueError(f"unknown chunk kind {kind}")

    out += _chunk(b"IEND", b"")
    return bytes(out)


def card_v2_payload(**overrides) -> dict:
    data = {
        "name": "Aria",
        "description": "A wandering elf ranger.",
        "personality": "Curious, guarded, loyal once trust is earned.",
        "scenario": "Meeting the party at a rain-soaked tavern.",
        "first_mes": "Aria glances up from her drink. \"You're late.\"",
        "mes_example": "<START>\n{{user}}: Hi\n{{char}}: Hello.",
        "tags": ["fantasy", "adventure"],
        "creator": "someuser",
        "character_version": "1.0",
        "alternate_greetings": ["Alt greeting one.", "Alt greeting two."],
        "extensions": {"talkativeness": 0.5},
    }
    data.update(overrides)
    return {"spec": "chara_card_v2", "spec_version": "2.0", "data": data}


def b64_json(obj: dict) -> str:
    return base64.b64encode(json.dumps(obj).encode("utf-8")).decode("ascii")


@pytest.fixture
def v2_png_bytes() -> bytes:
    payload = b64_json(card_v2_payload())
    return build_png([("tEXt", "chara", payload)])
