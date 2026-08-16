from cardpack.cleaning import strip_bloat


def test_strips_embedded_base64_image():
    huge_b64 = "A" * 5000
    text = f'Aria is a ranger. <img src="data:image/png;base64,{huge_b64}"> She is brave.'
    cleaned, removed = strip_bloat(text)
    assert "base64" not in cleaned
    assert "A" * 100 not in cleaned  # the huge blob itself is gone
    assert "Aria is a ranger." in cleaned
    assert "She is brave." in cleaned
    assert removed > 4000


def test_strips_common_html_tags_but_keeps_inner_text():
    text = "<b>Aria</b> is <i>very</i> brave.<br>She fights well."
    cleaned, removed = strip_bloat(text)
    assert cleaned == "Aria is very brave.\nShe fights well." or "Aria is very brave." in cleaned
    assert "<b>" not in cleaned
    assert "<br>" not in cleaned
    assert removed > 0


def test_strips_html_comments():
    text = "Aria is a ranger. <!-- internal note, ignore --> She lives in the woods."
    cleaned, _ = strip_bloat(text)
    assert "internal note" not in cleaned
    assert "Aria is a ranger." in cleaned
    assert "She lives in the woods." in cleaned


def test_strips_markdown_images():
    text = "Aria's portrait: ![portrait](https://example.com/aria.png) is shown above."
    cleaned, removed = strip_bloat(text)
    assert "![portrait]" not in cleaned
    assert "example.com" not in cleaned
    assert removed > 0


def test_strips_decorative_separator_lines():
    text = "Aria is a ranger.\n————————————\nShe lives in the woods.\n★★★★★★★★★★"
    cleaned, removed = strip_bloat(text)
    assert "————" not in cleaned
    assert "★★★" not in cleaned
    assert "Aria is a ranger." in cleaned
    assert "She lives in the woods." in cleaned
    assert removed > 0


def test_does_not_touch_start_convention_marker():
    # <START> is a real convention used by some exporters inside
    # mes_example to mark the beginning of an example exchange - it is
    # NOT a real HTML tag and must survive untouched.
    text = "<START>\n{{user}}: Hi\n{{char}}: Hello there."
    cleaned, removed = strip_bloat(text)
    assert cleaned == text
    assert removed == 0


def test_does_not_touch_repeated_letters_as_decoration():
    # A run of the same LETTER (elongated word, a scream, "xxxxx" as a
    # placeholder/censor) is real content, not a decorative divider -
    # only repeated punctuation/symbol characters count as decoration.
    text = "aaaaaaaaaah!\nxxxxxxxxxxxxxxxxxxxx"
    cleaned, removed = strip_bloat(text)
    assert cleaned == text
    assert removed == 0


def test_does_not_touch_markdown_bold_emphasis():
    # A real markdown-style action/emphasis line - not decoration -
    # must not be mistaken for a decorative separator line.
    text = "*She draws her sword and smiles.*"
    cleaned, removed = strip_bloat(text)
    assert cleaned == text
    assert removed == 0


def test_collapses_excess_whitespace():
    text = "Aria   is\t\ta ranger.\n\n\n\n\nShe lives in the woods."
    cleaned, removed = strip_bloat(text)
    assert "   " not in cleaned
    assert "\n\n\n" not in cleaned
    assert removed > 0


def test_empty_and_none_safe():
    assert strip_bloat("") == ("", 0)
    assert strip_bloat(None) == (None, 0)


def test_plain_prose_is_left_alone():
    text = "A wandering elf ranger, curious and guarded, loyal once trust is earned."
    cleaned, removed = strip_bloat(text)
    assert cleaned == text
    assert removed == 0


# --- line endings ---------------------------------------------------------
# Cards arrive from every platform, and a trailing "\r" silently defeats
# every end-of-line anchor downstream (section headers, decorative lines).


def test_crlf_and_bare_cr_become_lf():
    cleaned, _ = strip_bloat("one\r\ntwo\rthree\nfour")
    assert cleaned == "one\ntwo\nthree\nfour"
    assert "\r" not in cleaned


def test_normalised_line_endings_are_not_counted_as_stripped_bloat():
    # Dropping a "\r" is an encoding fix, not markup removal - counting it
    # would inflate the "markup removed" figure the export reports.
    _cleaned, removed = strip_bloat("a\r\nb\r\nc")
    assert removed == 0


def test_decorative_lines_are_stripped_even_with_crlf_endings():
    cleaned, _ = strip_bloat("Intro\r\n--------\r\nOutro")
    assert "--------" not in cleaned


def test_section_headers_survive_crlf_input():
    # The regression this guards: ">Appearance\r" stops matching a
    # `^>...$` anchor, which hid 74 of 188 headers in a real corpus.
    from cardpack.conventions import _section_headers

    cleaned, _ = strip_bloat(">Appearance\r\n+ tall\r\n>Personality\r\n+ warm")
    assert [n for _m, n in _section_headers(cleaned)] == ["Appearance", "Personality"]
