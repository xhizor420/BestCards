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
- **`compact`** — the same data with short plain-word labels (`Name:`,
  `Desc:`, `Personality:`, ...) and no Markdown syntax, for when every
  token counts.
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
blended into its neighbors. That note also explicitly tells the model not
to reuse this file's own labels/delimiters in its response — the `compact`
format learned that the hard way: it used to label fields with single
letters (`N:`, `D:`, `P:`...), and some models would echo that cryptic
shorthand back in their own output instead of writing a normal character,
on top of it being hard for a human to skim too. Labels are spelled-out
words now (`Name:`, `Desc:`, `Personality:`, ...) for exactly that reason.
That's the intended workflow — extract a batch (say, your top 100 cards),
upload the export, and prompt something like "use this file as reference
for what makes these cards work, then create a new character."

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

### Markup/bloat stripping

Cards pulled from web platforms often carry embedded `<img>` tags (sometimes
with a multi-KB base64 image baked right into the attribute), other HTML
formatting, HTML comments, markdown image syntax, and purely decorative
separator lines (`————————`, `★★★★★★★★`) — none of which help a model
understand personality, scenario, or voice. This is stripped unconditionally
at extraction time, before truncation, for every card — there's no flag to
turn it off, because unlike truncation it never trades away real content.
The corpus stats block reports exactly what was removed and from which
cards (`Markup/decoration already stripped: ~12,160 chars (~3,040 tokens)
... Heaviest: Zed (~12,160 chars)`), so you can see which specific PNGs
were the worst offenders. Genuine content is left alone — an elongated
word like `"aaaaaaaah"` or a `*bold action*` line is never mistaken for
decoration, and exporter conventions like `<START>` inside `mes_example`
are never mistaken for an HTML tag.

### Guarding against "averaging into a bland composite"

Handing a model 100 reference cards at once has a real failure mode: it
regresses toward a generic blend of all of them instead of drawing on what
makes individual cards distinctive. Every export's opening note says these
are curated, high-quality references — not a random or average sample —
and explicitly tells the model not to average them into a composite, but to
notice what makes individual cards effective and match that bar with
something original. The stats block backs this up with the actual spread
(`Description length: 44–2,400 chars (avg 620)`) instead of just a flat
average, since a flat average is exactly the kind of number that invites
"aim for the middle" thinking.

That spread is also explicitly framed as tracking *complexity*, not
quality or a target — a card built around one simple character can
legitimately run a couple thousand tokens while one built around several
characters or an intricate scenario runs well past that, and neither is
"more correct." The file tells the model outright not to treat any length
here (including that range) as something to hit, and to instead let its
own character concept's actual complexity decide how long it needs to be
— the goal is not constraining creativity to match a norm from the corpus.

### Token counting

There's no single universal tokenizer — GPT, Claude, GLM, DeepSeek, Llama,
etc. all split text differently, so "the" token count doesn't exist
independent of which model you're targeting. Pick one with `--tokenizer`
(CLI) or the tokenizer dropdown (UI):

| Name | What it uses | Needs |
| --- | --- | --- |
| `heuristic` (default) | word-aware estimate (~0.75 tok/word, better than flat chars/4) | nothing — instant, no download |
| `deepseek` | DeepSeek-V3's real tokenizer.json | `pip install tokenizers huggingface_hub` + one-time fetch from huggingface.co |
| `glm` | GLM-4.5's real tokenizer.json | same as above |
| `gpt` | tiktoken's `cl100k_base` (exact for GPT-4/3.5, a reasonable proxy for most other BPE tokenizers) | `pip install tiktoken` + one-time fetch from openaipublic's CDN |
| any `org/repo` | that Hugging Face model's tokenizer.json | same as deepseek/glm |

`pip install -e ".[tokens]"` installs everything needed for all of them at
once. The `deepseek`/`glm`/`gpt`/custom-repo presets each need a one-time
network fetch to cache their tokenizer data locally (a few MB) the first
time they're used — after that, counts are instant. If the package isn't
installed, or the fetch can't complete (offline, a restrictive proxy, a
gated repo), counting falls back to the heuristic automatically rather
than failing the export — and the printed/displayed method **always says
plainly which one actually produced the number, including why it fell
back if it did**, so nothing here is ever presented as more precise than
it actually is.

Note: I built and tested the `deepseek`/`glm`/`gpt` presets' fallback
behavior (missing package, blocked network) thoroughly, but the sandbox
this was developed in blocks outbound access to both huggingface.co and
openaipublic's CDN, so the actual "download succeeds, count is exact"
path couldn't be exercised there. It follows the same well-defined
`tokenizers`/`tiktoken` API either way and should just work on a normal
machine with internet access — if a default repo (`deepseek-ai/DeepSeek-V3`,
`zai-org/GLM-4.5`) turns out to be stale, pass any other `org/repo` id
directly as `--tokenizer` to point at the one you actually want.

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
counter above it. A **Tokenizer** dropdown picks which model's tokenizer
computes that count (Heuristic / DeepSeek / GLM / GPT — see "Token
counting" above); the label next to the total shows `(exact)` or
`(estimate - see title for why)`, and hovering it shows the full
explanation (which tokenizer, or why it fell back). Checkboxes let you
pick exactly which optional fields go into the export (tags, creator
notes, alt greetings, lorebook, system prompt, post-history instructions —
the six core fields are always included); toggling any of them, changing
format/tokenizer, or changing `--full`/the per-field cap re-estimates the
total and every per-card badge live, so you see the cost of each choice
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

# Exact token count for DeepSeek (needs: pip install tokenizers huggingface_hub)
python3 bestcards.py ./my_cards -o cards_export.md --tokenizer deepseek

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
| `--tokenizer NAME` | `heuristic` (default) \| `deepseek` \| `glm` \| `gpt` \| any `org/repo` — see "Token counting" above |
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
  mix, top tags if included, description length range, markup/bloat
  stripped) and ends with a labeled token count (see "Token counting"
  above), so before you paste hundreds of cards into a model you know
  what you're about to spend and what the batch looks like at a glance.

## Development

```bash
pip install -e ".[dev]"
pytest
```

Optional: `pip install -e ".[tokens]"` for exact token counts (see "Token
counting" above) instead of the heuristic fallback.
