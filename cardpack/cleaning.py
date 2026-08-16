"""Strip low-value markup/decoration out of card text.

Character cards pasted from web platforms routinely carry along things
that cost tokens but carry zero character-design signal: embedded
`<img>` tags (sometimes with a multi-KB base64 image baked right into the
attribute), other HTML formatting tags, HTML comments, markdown image
syntax, Discord custom-emoji codes, and purely decorative separator lines
("————————", "★★★★★★"). None of that helps a model understand personality,
scenario, or voice - it's pure overhead, unlike truncation, which trades
away real content for size. So this is applied unconditionally at
extraction time (see cardspec.normalize_card_data), not gated behind a
flag: there's no version of "keep this" that makes an export better.

`<START>`-style all-caps convention markers used by some exporters inside
mes_example are deliberately NOT touched - the HTML-tag regex only matches
a whitelist of real HTML tag names, so "<START>" (not a real tag) survives
untouched while "<img src=...>" or "<b>" do not.
"""

from __future__ import annotations

import re

_DATA_URI_RE = re.compile(r"data:[a-zA-Z0-9/+.\-]+;base64,[A-Za-z0-9+/=]{20,}")

_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")

_DISCORD_EMOJI_RE = re.compile(r"<a?:\w+:\d+>")

# Only real HTML tag names - a whitelist, not "anything in angle brackets" -
# so exporter conventions like <START>, <END>, <FIRST_MES> are left alone.
_HTML_TAG_NAMES = (
    "img|br|hr|div|span|p|b|i|u|s|strong|em|a|ul|ol|li|table|thead|tbody|tr|td|th|"
    "blockquote|code|pre|sup|sub|font|center|h[1-6]|small|big|mark|details|summary|"
    "figure|figcaption|iframe|video|audio|source|button|input|style|script|svg|"
    "path|g|defs|use"
)
_HTML_TAG_RE = re.compile(rf"</?(?:{_HTML_TAG_NAMES})\b[^<>]*/?>", re.IGNORECASE)

# A line that's ONLY a repeated punctuation/symbol character (plus
# whitespace) is decoration, e.g. "————————" or "★★★★★★★★". Restricted to
# non-word characters specifically (not \S, which would also match a run
# of a repeated LETTER like "aaaaaaaah" or "xxxxxxxx" - those are real
# content - elongated words, screams - not decoration). Requires the whole
# line to match so "**bold text**" (real content between the asterisks)
# is never touched either.
_DECORATIVE_LINE_RE = re.compile(r"^[ \t]*([^\w\s])\1{3,}[ \t]*$", re.MULTILINE)

_EXCESS_SPACES_RE = re.compile(r"[ \t]{2,}")
_EXCESS_BLANK_LINES_RE = re.compile(r"\n{3,}")

# Cards come from every platform and OS, so some arrive with CRLF (or bare
# CR) line endings. Left in, a stray "\r" sits at the end of every line and
# silently defeats every end-of-line anchor downstream: a ">Appearance\r"
# header stops matching `^>...[ \t]*$`, and so does a decorative separator
# line. On a real 113-card corpus that hid 74 of 188 section headers - the
# single most important structural signal in the file - so normalising is
# a correctness fix, not tidying. It also drops thousands of invisible
# bytes from the export the user actually uploads.
_LINE_ENDING_RE = re.compile(r"\r\n?")


def normalize_newlines(text: str) -> str:
    """CRLF and bare CR -> LF. Idempotent, and safe on empty text."""
    return _LINE_ENDING_RE.sub("\n", text) if text else text


def strip_bloat(text: str) -> tuple[str, int]:
    """Returns (cleaned_text, chars_removed).

    Line endings are normalised first and NOT counted as removed: dropping
    a "\\r" is an encoding fix, and reporting it as stripped bloat would
    inflate the "markup removed" figure with characters that were never
    markup.
    """
    if not text:
        return text, 0
    cleaned = normalize_newlines(text)
    original_len = len(cleaned)
    cleaned = _DATA_URI_RE.sub("", cleaned)  # biggest single offender: embedded base64 images
    cleaned = _HTML_COMMENT_RE.sub("", cleaned)
    cleaned = _MD_IMAGE_RE.sub("", cleaned)
    cleaned = _DISCORD_EMOJI_RE.sub("", cleaned)
    cleaned = _HTML_TAG_RE.sub("", cleaned)
    cleaned = _DECORATIVE_LINE_RE.sub("", cleaned)
    cleaned = _EXCESS_SPACES_RE.sub(" ", cleaned)
    cleaned = _EXCESS_BLANK_LINES_RE.sub("\n\n", cleaned)
    cleaned = cleaned.strip()

    return cleaned, max(0, original_len - len(cleaned))
