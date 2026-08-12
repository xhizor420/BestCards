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
scenario, first_mes, mes_example**. Everything else is opt-in and off by
default except `tags` (see `--fields` below) — each one costs real tokens
for content that's often not needed, so you choose what's worth it rather
than the tool deciding for you. `--full` is a separate, independent knob:
it only controls whether *included* fields are truncated, not which
fields appear.

Attribution (who made the card, `creator`) is left out of every export
entirely, with no toggle to bring it back — it's not a content pattern a
model can learn from, just token cost with no analytical payoff for this
use case.

### Token counting

Every export ends with a token count and, honestly, a label saying how it
was computed — there's no single universal tokenizer (GPT, Claude, Llama,
etc. all split text differently), so nothing here claims false precision:

- If [`tiktoken`](https://github.com/openai/tiktoken) is installed
  (`pip install tiktoken`) and can reach its one-time encoding-data
  download, counts are **exact** for GPT-4/3.5's tokenizer (`cl100k_base`)
  and a close proxy for most other modern BPE tokenizers, including
  Claude's. Output is labeled `tiktoken/cl100k_base`.
- Otherwise it falls back to a word-aware heuristic (~0.75 tokens/word,
  better than a flat chars/4), labeled `heuristic` so you always know
  which one produced the number in front of you.

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
and its own token cost (`113 tok`) — plus a running **total tokens**
counter above it, labeled `(exact, tiktoken)` or `(estimate)` depending on
whether `tiktoken` is installed on the machine running the server. Checkboxes
let you pick exactly which optional fields go into the export (tags,
creator notes, alt greetings, lorebook, system prompt, post-history
instructions — the six core fields are always included); toggling any of
them, changing format, or changing `--full`/the per-field cap re-estimates
the total and every per-card badge live, so you see the cost of each choice
before exporting. Click the **×** on any tile to drop that card from the
export entirely (it's removed from the total instantly, and won't be in
the downloaded file) — useful for trimming a batch down to your actual
token budget without re-uploading. Pick a format (Markdown / compact /
JSON) and click **Generate & download export** to save the combined file.
This is the same extraction and export logic as the CLI below, just with
drag-and-drop and live per-card/per-field visibility instead of flags.

Options: `python3 ui.py --port 9000`, `--no-browser` to skip auto-opening a
tab, `--host 0.0.0.0` to allow other devices on your LAN to reach it (only
do this on a network you trust — the server has no auth).

## CLI Usage

```bash
# Scan a folder of PNGs (recursively) and write a Markdown digest
python3 bestcards.py ./my_cards -o cards_export.md

# Minimal-token plain text, good for pasting into a chat with a big batch
python3 bestcards.py ./my_cards -o cards_export.txt --format compact

# Full fidelity JSON, every optional field, untruncated text
python3 bestcards.py ./my_cards -o cards_export.json --format json --full --fields all

# Bring creator notes back in alongside tags (both off-by-default fields are opt-in)
python3 bestcards.py ./my_cards -o cards_export.md --fields tags,creator_notes

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
| `--fields LIST` | Comma-separated optional fields to include: `tags`, `creator_notes`, `system_prompt`, `post_history_instructions`, `alt_greetings`, `lorebook`. Also accepts `all` or `none`. Default: `tags`. (The six core fields are always included and aren't part of this list.) |
| `--full` | Don't truncate included prose, and show full text for included list fields (alt_greetings, lorebook) instead of just a count. Independent of `--fields` — controls *how much* of what's included is shown, not *what's* included |
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
  mix, top tags if included, average description length) and ends with a
  labeled token count (see "Token counting" above), so before you paste
  hundreds of cards into a model you know what you're about to spend and
  what the batch looks like at a glance.

## Development

```bash
pip install -e ".[dev]"
pytest
```

Optional: `pip install -e ".[tokens]"` (or just `pip install tiktoken`) to
get exact token counts instead of the heuristic fallback.
