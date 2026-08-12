from cardpack.png_chunks import read_text_chunks
from tests.conftest import build_png


def test_reads_text_chunk():
    png = build_png([("tEXt", "chara", "hello world")])
    chunks = read_text_chunks(png)
    assert len(chunks) == 1
    assert chunks[0].keyword == "chara"
    assert chunks[0].text == "hello world"
    assert chunks[0].chunk_type == "tEXt"


def test_reads_ztxt_chunk_compressed():
    png = build_png([("zTXt", "chara", "compressed payload " * 20)])
    chunks = read_text_chunks(png)
    assert len(chunks) == 1
    assert chunks[0].text == "compressed payload " * 20


def test_reads_itxt_chunk_utf8():
    png = build_png([("iTXt", "ccv3", "unicode ☃ snowman")])
    chunks = read_text_chunks(png)
    assert len(chunks) == 1
    assert chunks[0].text == "unicode ☃ snowman"


def test_reads_multiple_text_chunks_v2_and_v3():
    png = build_png([("tEXt", "chara", "v2 payload"), ("iTXt", "ccv3", "v3 payload")])
    chunks = read_text_chunks(png)
    by_kw = {c.keyword: c.text for c in chunks}
    assert by_kw["chara"] == "v2 payload"
    assert by_kw["ccv3"] == "v3 payload"


def test_ignores_non_text_ancillary_chunks():
    png = build_png([("tEXt", "chara", "payload")])
    # Should not raise even though IHDR/IEND are present and not text chunks.
    chunks = read_text_chunks(png)
    assert [c.keyword for c in chunks] == ["chara"]
