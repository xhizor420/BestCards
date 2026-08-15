from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .cardspec import Card, CardExtractionError, parse_card_payload
from .formats import ALL_EXTRA_FIELDS, DEFAULT_EXTRA_FIELDS, WRITERS, normalize_extra_fields
from .png_chunks import NotAPngError, read_text_chunks_from_file
from .selection import rank_cards, select_best
from .stats import TOKENIZER_PRESETS, count_tokens


def _gather_png_paths(inputs: list[str], recursive: bool) -> list[Path]:
    seen: set[Path] = set()
    paths: list[Path] = []
    for raw in inputs:
        p = Path(raw)
        if p.is_dir():
            pattern = "**/*.png" if recursive else "*.png"
            found = sorted(p.glob(pattern))
        elif p.is_file():
            found = [p]
        else:
            print(f"warning: path not found, skipping: {p}", file=sys.stderr)
            continue
        for f in found:
            resolved = f.resolve()
            if resolved not in seen:
                seen.add(resolved)
                paths.append(f)
    return paths


def extract_card_from_png(path: Path) -> Card:
    chunks = read_text_chunks_from_file(path)
    card = parse_card_payload(chunks)
    card.source_file = str(path)
    return card


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bestcards",
        description=(
            "Batch-extract embedded character card data (V1/V2/V3 spec) from a folder "
            "of PNG character cards (JanitorAI, Chub, SillyTavern, etc.) and combine "
            "them into one compact, model-friendly export file."
        ),
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="PNG files and/or folders to scan (folders are scanned recursively by default).",
    )
    parser.add_argument(
        "-o", "--output", default="cards_export.md", help="Output file path (default: cards_export.md)."
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=sorted(WRITERS),
        default="md",
        help="Output format: 'md' (readable digest, default), 'compact' (minimal tokens), "
        "'json' (full fidelity for programmatic use).",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Don't truncate included prose fields, and show full text for included list "
        "fields (alt_greetings, lorebook) instead of just a count. Independent of --fields "
        "below - it controls how much of what's included is shown, not what's included.",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=600,
        help="Per-field character cap when not using --full (default: 600).",
    )
    parser.add_argument(
        "--fields",
        default=",".join(sorted(DEFAULT_EXTRA_FIELDS)),
        metavar="LIST",
        help="Comma-separated optional fields to include beyond the always-present core six "
        f"(name, description, personality, scenario, first_mes, mes_example): "
        f"{','.join(ALL_EXTRA_FIELDS)}. Also accepts 'all' or 'none'. Default: 'tags'. "
        "(creator_notes and the others cost tokens with no content-pattern payoff unless you "
        "specifically want them - opt in here.)",
    )
    parser.add_argument(
        "--tokenizer",
        default="heuristic",
        metavar="NAME",
        help="Tokenizer used for the token count printed/written with the export: "
        f"{', '.join(TOKENIZER_PRESETS)}, 'heuristic' (default, no download), or any "
        "Hugging Face 'org/repo' id (its tokenizer.json is used). Presets need one-time "
        "network access on first use (tiktoken -> openaipublic's CDN, deepseek/glm -> "
        "huggingface.co) and, for deepseek/glm, `pip install tokenizers huggingface_hub`. "
        "Falls back to the heuristic (labeled as such) if unavailable.",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Only scan the top level of given folders instead of recursing into subfolders.",
    )
    parser.add_argument(
        "--sort",
        choices=["best", "file", "name"],
        default="best",
        help="Order cards in the output. 'best' (default) puts the most instructive cards "
        "first - most >Section structure, most substance - so a reader anchors on the "
        "strongest examples and, if anything gets cut, the weakest go. 'file' and 'name' "
        "sort by source filename or card name.",
    )
    parser.add_argument(
        "--full-top",
        type=int,
        default=10,
        metavar="N",
        help="Show the N most instructive cards COMPLETE (untrimmed) and trim the rest to "
        "--max-chars (default: 10). This is what lets a 100+ card corpus stay affordable "
        "without hiding the structure: structure is learned from a few whole cards, breadth "
        "from many partial ones. Stats and detected conventions always cover every card. "
        "Use 0 to trim everything evenly.",
    )
    parser.add_argument(
        "--best",
        type=int,
        metavar="N",
        help="Keep only the N most instructive cards (see --sort best). Pair with --full: "
        "for richly-structured cards, N complete examples teach far more than every card "
        "truncated to --max-chars, which can hide most of the structure you want mirrored.",
    )
    parser.add_argument(
        "--report-failures",
        metavar="PATH",
        help="Also write a text file listing PNGs that had no usable card data.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    png_paths = _gather_png_paths(args.inputs, recursive=not args.no_recursive)
    if not png_paths:
        print("No PNG files found for the given inputs.", file=sys.stderr)
        return 1

    cards: list[Card] = []
    failures: list[tuple[Path, str]] = []
    for path in png_paths:
        try:
            cards.append(extract_card_from_png(path))
        except NotAPngError as e:
            failures.append((path, str(e)))
        except CardExtractionError as e:
            failures.append((path, str(e)))
        except Exception as e:  # noqa: BLE001 - keep batch processing resilient
            failures.append((path, f"unexpected error: {e}"))

    if args.sort == "best":
        cards = rank_cards(cards)
    elif args.sort == "name":
        cards.sort(key=lambda c: (c.name or c.nickname or "").lower())
    else:
        cards.sort(key=lambda c: c.source_file)

    total_extracted = len(cards)
    # Spec mix describes everything extracted, so it stays consistent with
    # the "Extracted N card(s)" line even when --best narrows the export.
    spec_counts: dict[str, int] = {}
    for c in cards:
        spec_counts[c.spec_version] = spec_counts.get(c.spec_version, 0) + 1

    if args.best:
        cards = select_best(cards, args.best)

    extra_fields = normalize_extra_fields(args.fields)
    writer = WRITERS[args.format]
    output_text = writer(
        cards,
        full=args.full,
        max_chars=args.max_chars,
        extra_fields=extra_fields,
        tokenizer=args.tokenizer,
        full_top=args.full_top,
    )
    Path(args.output).write_text(output_text, encoding="utf-8")

    spec_summary = ", ".join(f"v{v}: {n}" for v, n in sorted(spec_counts.items()))

    tc = count_tokens(output_text, args.tokenizer)

    print(f"Scanned {len(png_paths)} PNG file(s).")
    print(f"Extracted {total_extracted} card(s) ({spec_summary}).")
    if args.best and len(cards) < total_extracted:
        print(f"Kept the {len(cards)} most instructive for the export (--best).")
    if failures:
        print(f"Skipped {len(failures)} file(s) with no usable card data.")
    print(f"Wrote {args.format} export to {args.output}")
    print(f"{tc.count:,} tokens ({tc.method})")
    if not tc.exact and args.tokenizer != "heuristic":
        print("  (fell back to the heuristic - see the message above for why)")
    elif not tc.exact:
        print("  (pass --tokenizer deepseek|glm|gpt for an exact count; see --help for details)")

    # Truncation is silent by default, and on a corpus of long structured
    # cards it can hide most of what the export is trying to teach - a
    # 600-char cap over ~8,000-char dossiers shows a reader roughly 7% of
    # each card. Say so rather than letting it pass unnoticed.
    if not args.full and cards and args.full_top <= 0:
        shown = sum(min(len(c.description), args.max_chars) for c in cards)
        actual = sum(len(c.description) for c in cards)
        if actual and shown / actual < 0.5:
            print(
                f"\nNOTE: --max-chars {args.max_chars} is showing only "
                f"{shown / actual:.0%} of the description text "
                f"({shown:,} of {actual:,} chars)."
            )
            print(
                "  These cards are long and structured, so most of that structure is being "
                "cut.\n  For a reference corpus, prefer fewer COMPLETE cards over many "
                "fragments, e.g.:"
            )
            print("    --full-top 10           (show the 10 best cards complete, trim the rest)")

    if args.report_failures and failures:
        report_lines = [f"{path}: {reason}" for path, reason in failures]
        Path(args.report_failures).write_text("\n".join(report_lines) + "\n", encoding="utf-8")
        print(f"Wrote failure report to {args.report_failures}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
