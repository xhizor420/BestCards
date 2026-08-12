"""Dependency-free PNG text-chunk reader.

Character cards (JanitorAI, Chub, SillyTavern, Agnai, ...) embed their JSON
payload inside a PNG ancillary text chunk (tEXt / zTXt / iTXt). This module
only needs the standard library (struct + zlib) to walk the chunk stream and
pull those out, so the tool has no install step.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class NotAPngError(ValueError):
    pass


@dataclass
class TextChunk:
    keyword: str
    text: str
    chunk_type: str  # "tEXt" | "zTXt" | "iTXt"


def _read_chunks(data: bytes):
    if data[:8] != PNG_SIGNATURE:
        raise NotAPngError("not a PNG file (bad signature)")
    pos = 8
    length_of = len(data)
    while pos + 8 <= length_of:
        (chunk_len,) = struct.unpack(">I", data[pos : pos + 4])
        chunk_type = data[pos + 4 : pos + 8].decode("ascii", errors="replace")
        data_start = pos + 8
        data_end = data_start + chunk_len
        if data_end + 4 > length_of:
            break  # truncated file, stop reading rather than raising
        chunk_data = data[data_start:data_end]
        yield chunk_type, chunk_data
        if chunk_type == "IEND":
            return
        pos = data_end + 4  # skip CRC


def _split_keyword(payload: bytes) -> tuple[bytes, bytes]:
    idx = payload.find(b"\x00")
    if idx == -1:
        raise ValueError("text chunk missing null-terminated keyword")
    return payload[:idx], payload[idx + 1 :]


def _parse_text(payload: bytes) -> TextChunk:
    keyword, rest = _split_keyword(payload)
    text = rest.decode("latin-1")
    return TextChunk(keyword=keyword.decode("latin-1"), text=text, chunk_type="tEXt")


def _parse_ztxt(payload: bytes) -> TextChunk:
    keyword, rest = _split_keyword(payload)
    if not rest:
        raise ValueError("zTXt chunk missing compression method")
    compression_method, compressed = rest[0], rest[1:]
    if compression_method != 0:
        raise ValueError(f"unsupported zTXt compression method {compression_method}")
    text = zlib.decompress(compressed).decode("latin-1")
    return TextChunk(keyword=keyword.decode("latin-1"), text=text, chunk_type="zTXt")


def _parse_itxt(payload: bytes) -> TextChunk:
    keyword, rest = _split_keyword(payload)
    if len(rest) < 2:
        raise ValueError("iTXt chunk too short")
    compression_flag, compression_method = rest[0], rest[1]
    rest = rest[2:]
    lang_tag, rest = _split_keyword(rest)
    translated_keyword, rest = _split_keyword(rest)
    del lang_tag, translated_keyword  # not needed for card extraction
    if compression_flag == 1:
        if compression_method != 0:
            raise ValueError(f"unsupported iTXt compression method {compression_method}")
        text = zlib.decompress(rest).decode("utf-8", errors="replace")
    else:
        text = rest.decode("utf-8", errors="replace")
    return TextChunk(keyword=keyword.decode("utf-8", errors="replace"), text=text, chunk_type="iTXt")


_PARSERS = {"tEXt": _parse_text, "zTXt": _parse_ztxt, "iTXt": _parse_itxt}


def read_text_chunks(data: bytes) -> list[TextChunk]:
    """Return every tEXt/zTXt/iTXt chunk found in a PNG byte string.

    Malformed individual chunks are skipped rather than aborting the whole
    read, since a bad ancillary chunk elsewhere in the file shouldn't stop
    us from reaching the one that actually holds card data.
    """
    chunks: list[TextChunk] = []
    for chunk_type, chunk_data in _read_chunks(data):
        parser = _PARSERS.get(chunk_type)
        if parser is None:
            continue
        try:
            chunks.append(parser(chunk_data))
        except (ValueError, zlib.error, UnicodeDecodeError):
            continue
    return chunks


def read_text_chunks_from_file(path: str | Path) -> list[TextChunk]:
    with open(path, "rb") as f:
        data = f.read()
    return read_text_chunks(data)
