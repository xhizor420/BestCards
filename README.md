# BestCards

Batch-extract the character-card data embedded in a folder of PNG "character
cards" (from JanitorAI, Chub.ai, SillyTavern, Agnai, etc.) and combine
hundreds of them into a single compact, plain-text export you can hand to an
AI model as reference material — no JSON bloat, no per-card copy/paste.

## Why

Those PNGs aren't just images: exporters embed the actual character JSON
(name, personality, scenario, greeting, lorebook, ...) inside a PNG text
chunk (`tEXt`/`zTXt`/`iTXt`, keyword `chara` for the V1/V2 spec or `ccv3` for
V3). This tool reads that metadata directly out of the PNG — no image
viewer, no manual export — and merges however many cards you throw at it
into one file, in a format built for pasting into an LLM's context rather
than for machine round-tripping:

- **`md`** (default) — a readable Markdown digest, one section per card.
- **`compact`** — the same data with abbreviated field labels and no
  Markdown syntax, for when every token counts.
- **`json`** — full-fidelity structured output, if you want to feed it into
  another script instead of a model.

Plain text/Markdown is accepted everywhere JSON sometimes isn't, and it's
meaningfully cheaper in tokens than JSON's braces/quotes/escaped newlines
for what is mostly prose fields.

The export is written as a **reference corpus**, not a data dump: every
format opens with an explicit note telling the reading model "these are N
separate existing characters — compare them for patterns, then design a
new one, don't copy any single card verbatim," and every card gets an
unambiguous `=== CARD i/N ===` (or `## Card i/N`) section so it can't get
blended into its neighbors. That's the intended workflow — extract a batch
(say, your top 100 cards), upload the export, and prompt something like
"use this file as reference for what makes these cards work, then create a
new character."

Six fields are always present for every card (truncated per `--max-chars`,
never dropped, unless `--full`): **name, description, personality,
scenario, first_mes, mes_example**. `tags` and `creator_notes` are also
included by default — tags are the closest thing to a genre/archetype
label, and creator notes are often where a creator explains what a card is
for, which is exactly the "why do people use this" signal a reference
corpus needs. Everything else (system prompt, post-history instructions,
full alternate greetings, full lorebook text) is more runtime
configuration than content signal, so by default it's summarized to a
count and only spelled out with `--full`.

Attribution (who made the card, `creator`) is intentionally left out of
every export — it's not a content pattern a model can learn from, just
token cost with no analytical payoff for this use case.

## Requirements

Python 3.10+, standard library only — nothing to `pip install` to run it.

## Browser UI

```bash
python3 ui.py
# -> opens http://127.0.0.1:8765/ in your browser
```

Drag a folder (or a pile of PNGs) onto the page, or use "Choose PNG files" /
"Choose a folder" to browse. Each file is uploaded to a small local server
(nothing leaves your machine) and a progress bar tracks how many of the
batch have been processed so far.

Once extraction finishes you get a grid of every card — thumbnail, name,
and its own token cost (`~113 tok`) — plus a running **total tokens**
counter above it. Change format / `--full` / per-field cap and the counter
and every per-card badge re-estimate live, so you can see exactly what a
setting costs before exporting. Click the **×** on any tile to drop that
card from the export entirely (it's removed from the total instantly, and
won't be in the downloaded file) — useful for trimming a batch down to
your actual token budget without re-uploading. Pick a format (Markdown /
compact / JSON) and click **Generate & download export** to save the
combined file. This is the same extraction and export logic as the CLI
below, just with drag-and-drop and live per-card visibility instead of
flags.

Options: `python3 ui.py --port 9000`, `--no-browser` to skip auto-opening a
tab, `--host 0.0.0.0` to allow other devices on your LAN to reach it (only
do this on a network you trust — the server has no auth).

## CLI Usage

```bash
# Scan a folder of PNGs (recursively) and write a Markdown digest
python3 bestcards.py ./my_cards -o cards_export.md

# Minimal-token plain text, good for pasting into a chat with a big batch
python3 bestcards.py ./my_cards -o cards_export.txt --format compact

# Full fidelity JSON (all alt greetings, full lorebook, untruncated text)
python3 bestcards.py ./my_cards -o cards_export.json --format json --full

# Mix explicit files and folders
python3 bestcards.py card1.png card2.png ./more_cards/

# See which PNGs had no usable card data
python3 bestcards.py ./my_cards -o out.md --report-failures failures.txt
```

Or install it as a console command:

```bash
pip install -e .
bestcards ./my_cards -o cards_export.md
```

### Options

| Flag | Purpose |
| --- | --- |
| `-o, --output` | Output file path (default `cards_export.md`) |
| `-f, --format` | `md` \| `compact` \| `json` |
| `--full` | Include full example dialogue, all alt greetings, full lorebook (otherwise trimmed to `--max-chars` per field) |
| `--max-chars` | Per-field truncation cap in non-`--full` mode (default 600) |
| `--no-recursive` | Only scan the top level of given folders |
| `--sort` | Order cards by `name` (default) or `file` |
| `--report-failures PATH` | Write a list of PNGs that had no card data |

## How extraction works

- Reads PNG chunks directly (`tEXt`/`zTXt`/`iTXt`), no image-decoding
  dependency required.
- Looks for keyword `ccv3` (Character Card **V3**) first, falling back to
  `chara` (V2, or unwrapped **V1** for older exports) — matching how real
  exporters lay out multi-spec cards.
- Normalizes whichever spec version it finds into one common set of fields
  (name, description, personality, scenario, greeting(s), example dialogue,
  creator notes, system prompt, lorebook entries, tags, ...), so the rest
  of the pipeline never has to special-case spec version.
- Cards with no recognizable payload are skipped and reported, not fatal to
  the batch.
- Every export starts with a corpus-stats block (card count, spec-version
  mix, top tags, average description length) and ends with a
  rough token-count estimate, so before you paste hundreds of cards into a
  model you know roughly what you're about to spend and what the batch
  looks like at a glance.

## Development

```bash
pip install -e ".[dev]"
pytest
```
