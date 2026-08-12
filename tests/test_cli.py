from pathlib import Path

from cardpack.cli import main
from tests.conftest import b64_json, build_png, card_v2_payload


def _write_card_png(path: Path, **overrides):
    payload = b64_json(card_v2_payload(**overrides))
    path.write_bytes(build_png([("tEXt", "chara", payload)]))


def test_cli_scans_folder_recursively_and_writes_markdown(tmp_path):
    nested = tmp_path / "sub"
    nested.mkdir()
    _write_card_png(tmp_path / "aria.png", name="Aria")
    _write_card_png(nested / "zed.png", name="Zed")

    out_path = tmp_path / "out.md"
    rc = main([str(tmp_path), "-o", str(out_path)])
    assert rc == 0

    text = out_path.read_text(encoding="utf-8")
    assert "Aria" in text
    assert "Zed" in text
    # default sort is by name, so Aria should come before Zed
    assert text.index("Aria") < text.index("Zed")


def test_cli_reports_failures_for_non_card_pngs(tmp_path):
    good = tmp_path / "good.png"
    bad = tmp_path / "bad.png"
    _write_card_png(good, name="GoodCard")
    bad.write_bytes(build_png([("tEXt", "Software", "unrelated metadata")]))

    out_path = tmp_path / "out.md"
    report_path = tmp_path / "failures.txt"
    rc = main([str(tmp_path), "-o", str(out_path), "--report-failures", str(report_path)])
    assert rc == 0
    assert "GoodCard" in out_path.read_text(encoding="utf-8")
    assert "bad.png" in report_path.read_text(encoding="utf-8")


def test_cli_compact_format(tmp_path):
    _write_card_png(tmp_path / "aria.png", name="Aria")
    out_path = tmp_path / "out.txt"
    rc = main([str(tmp_path), "-o", str(out_path), "--format", "compact"])
    assert rc == 0
    text = out_path.read_text(encoding="utf-8")
    assert "N: Aria" in text


def test_cli_no_inputs_found_returns_error(tmp_path, capsys):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    rc = main([str(empty_dir)])
    assert rc == 1
    captured = capsys.readouterr()
    assert "No PNG files found" in captured.err
