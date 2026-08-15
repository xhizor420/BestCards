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
blended into its neighbors. `compact`'s field labels are spelled-out words
(`Name:`, `Desc:`, `Personality:`, ...), not single-letter codes — it used
to use letter codes, and some models echoed that cryptic shorthand back in
their own output instead of writing a normal character, on top of it being
hard for a human to skim too. That's the intended workflow — extract a
batch (say, your top 100 cards), upload the export, and prompt something
like "use this file as reference for what makes these cards work, then
create a new character."

### Response template

The very last thing in every export — after every card, so it's the last
thing read before the model has to respond — is an explicit template for
its answer: the same six fields every card above has (Name, Description,
Personality, Scenario, First Message, Example Dialogue), with an
instruction to fill them in the way the strongest reference cards wrote
theirs, not to copy any one of them, and *not* to reuse this file's own
multi-card wrapper (`=== CARD i/N ===` headers, the stats block) for its
one new character. This exists because just telling a model "design a new
character" from a pile of 100 reference cards tends to get you either free
-form prose with no usable structure, or — the opposite failure — an echo
of the file's own internal shorthand. Giving it the exact shape to fill in,
right where it matters most in the prompt, fixes both: you get a character
back in the same six fields the whole corpus is built from, ready to turn
into an actual new card, not just a description of one.

It reads as **guidance anchored in your data, not a rulebook**. The
framing is "here's what these cards actually do — write toward it; where
they show a clear convention, follow it, where they don't, use your own
judgement." The corpus is the authority, so the template points at it
rather than issuing prohibitions, which leaves room for the model to
actually be creative instead of just compliant.

The template also says explicitly to give the character back as **one
clean block with no commentary mixed into or around the fields** (each
label written out, blank line between fields), so the response is
directly copy-paste-able rather than the fields being buried in
paragraphs of explanation — and to close by briefly **asking if any
changes are wanted**, then on a
revision request, **re-sending the whole card again** (every field, not
just the one that changed) so it stays copy-paste-ready through as many
rounds of edits as you want.

### Measured house style

"Write it the way the reference cards did" isn't actionable on its own,
and `mes_example` is where that failed hardest: its real shape is a set of
*conventions* (a `<START>` line, `{{user}}:` / `{{char}}:` turn prefixes,
`*asterisk actions*`) that a model won't reliably infer from a prose
description of what the field is for — so it would half-fill the field, or
write a one-line description of an exchange instead of an actual one.

So the tool measures what your corpus actually does and states it as
explicit rules with the real numbers behind them, right next to the
template:

```
### House style of these cards — follow it

- Use the {{char}} and {{user}} placeholder(s) rather than writing names literally (100% of these cards do).
- Begin Example Dialogue with a `<START>` line (100% of these cards do).
- Write Example Dialogue as alternating `{{user}}:` and `{{char}}:` lines, one turn per line (100% of these cards do — typically about 4 turn lines).
- Wrap actions/narration in *asterisks*, keeping speech outside them (100% of these cards do).
- First Message typically runs about 2 paragraphs in these cards, not one line.
```

The `Example Dialogue:` slot in the template is then filled with a
correctly-formatted sample built from those same detected conventions, so
the file *shows* the shape rather than describing it.

This never invents a house style: a convention is only reported when a
majority of cards that have the relevant field actually use it, and only
when at least 3 cards carry that field at all. A small or stylistically
mixed corpus simply gets no house-style section and a generic
placeholder, rather than confident-sounding claims drawn from one or two
examples.

#### Document structure, not just inline formatting

The bigger determinant of whether output looks like your corpus is the
structure *inside* a field. Real high-quality cards routinely pack an
entire structured dossier into `description` — `>Appearance`,
`>Personality`, `>Backstory` section headers with `+ ` bullet lines,
wrapped in `<Name>…</Name>` tags, with a separate `<NPC>` block for side
characters — while leaving the spec's own `personality` field empty. A
template rendering `Description: <appearance, background, key facts>` as
a one-liner teaches a model to throw all of that away.

So that structure is detected too, and the `Description:` slot in the
template is filled with a skeleton built from your corpus's *actual*
section names, in the order they typically appear:

```
Description:
<Name>
>Appearance
+ <specific, concrete detail>
+ <more detail — several bullets per section>
>Personality
+ <specific, concrete detail>
...
</Name>
```

The house-style block also states the median description length outright
("about 9,157 characters — a few short paragraphs is nowhere near it"),
because matching the corpus's *depth* is most of what separates a card
that feels like the references from a thin sketch.

#### Four groups, because they're four different kinds of guidance

Observed conventions are split rather than dumped into one list, since
"follow this" and "pick one of these" are not the same instruction:

| Group | What it holds | How it reads |
| --- | --- | --- |
| **Shared** (≥80% of cards) | `*asterisk actions*`, `"quoted speech"`, `{{user}}` placeholders | Not really a choice — just how cards here are written. Follow them. |
| **Approaches** | Structured dossier, bulleted facts, tagged blocks, directive scenario | Mutually comparable ways of *organising* a card. Most-organised first; default to the first. |
| **Touches** | Backtick thoughts, status lines, example-dialogue turn format | Independent flourishes. Take any, or none. |
| **Scale** | Median description length, first-message paragraph count | Plain observations about how much these cards carry. |

The split matters: presenting a backtick-thoughts habit as an
*alternative* to a dossier structure — under a "default to the first
one" instruction — would be nonsense, and burying a 100%-universal
convention in the same list as a 9% flourish loses the distinction
between a convention and an option.

**Share is not a quality signal here.** The corpus is already curated —
every card in it was picked as a good one — so a structure appearing in
11 of 57 cards means eleven cards that cleared your bar chose it, not
that it's a fringe habit. The export says this outright to the reading
model, and leads with the most organised approach on that basis rather
than deferring to raw frequency:

> Every card above was picked as a good one, so the counts below tell you
> how COMMON an approach is, never how good it is — an approach used by a
> handful of these cards is still an approach that worked in cards worth
> keeping. The list runs most-organised first; **default to the first
> one** unless the character you're building genuinely calls for
> something looser.

A structure also survives corpus growth: it qualifies on absolute count
(≥5 cards) as well as share, so a coherent style held by a fixed set of
cards isn't discarded just because you added unrelated cards around it.

#### Solo cards and group cards, side by side

Most corpora hold both — on a real 57-card one, 45 are built around a
single character and 12 around a cast (`Kate & Andrew`, `Hero Family`,
`Lindsay, Tori, Jazmine & Sabrina`). Left unsaid, a model averages them:
it writes a solo card when you asked for a group, or bolts a stray
sidekick onto a solo request.

So the export names the split, in the stats block and again in the
template:

> This corpus demonstrates both shapes: 45 cards built around a single
> character, and 12 built around a cast. Follow whichever matches what's
> being asked for — write a solo card for a solo request, a group card
> for a group one — rather than splitting the difference.
>
> Group cards run longer than solo ones here, and that's the format
> working: more characters means more to describe. Length follows the
> cast and the concept, so don't pad a solo card toward the group ones
> or trim a group card toward the solo ones.

Detection is deliberately conservative — an explicit `<NPC>` block, or a
name joining several characters — so a group card written as prose under
one name reads as solo rather than the other way round. It is only ever
used to *report* the mix; neither shape is filtered, trimmed, or
down-ranked for being what it is. Where the corpus does use `<NPC>`
blocks for side characters, the template points at that as the pattern
to follow for a group.

### Depth *and* breadth — how a 100+ card corpus stays usable

A flat truncation cap forces a false choice. Measured on a real 57-card
corpus whose median description is ~8,400 characters:

| Export | Section headers the model can see | Tokens |
| --- | --- | --- |
| Every card capped at 600 chars | **17 of 125** | 28.9k |
| Top 10 complete + rest capped (**default**) | **97** | 55.8k |
| Every card in full | 125 | 170.2k |

Capping everything showed a model roughly **7% of each card**, then asked
it to build a six-section dossier it had never seen completed. But
keeping only a handful of full cards throws away the breadth that makes
the corpus a *database* of what your characters look like.

They want different things: **structure** is learned from a few COMPLETE
examples, **breadth** from many partial ones. So by default the
top-ranked cards are rendered whole and everything after them is trimmed
— upload all 100+ cards and you get both, at a fraction of the full cost.
The export says so itself, so the reader knows why later entries are
short:

> The first 10 cards below are shown COMPLETE — study those for structure
> and depth. The remaining 47 are trimmed to ~600 characters per field to
> keep this file affordable; they are here for breadth (range of
> archetypes, tags and openings), not as full examples. The stats and
> conventions below are measured across all 57 cards.

#### Choosing which cards get full depth

Group cards carry more characters, so they run longer with more sections
and tend to lead the ranking — on a real 57-card corpus 5 of the top 10
were multi-character. That's the format working, not a flaw: a group card
is long because it holds a group. Both kinds stay in the export, and the
template says so explicitly, so the model has a solo pattern to follow for
a solo request and a group pattern for a group one.

What the score can't know is which of the two *you're* about to write. You
curated the corpus, so you overrule it: click the **☆** on any card
in the UI to pin it. Pinned cards lead the export and fill the
full-depth tier first. Each tile shows whether it's currently **shown in
full** or **trimmed**, so the tier is never a guess.

**Corpus stats and detected conventions always cover every card**, not
just the untrimmed ones — trimming affects display only, never the
analysis.

Controls:

| Setting | CLI | UI |
| --- | --- | --- |
| How many cards shown complete | `--full-top N` (default 10) | "Show best N cards in full" |
| Cap for the rest | `--max-chars` (default 600) | "Per-field cap (chars)" |
| Everything complete | `--full` | "No truncation" |
| Keep only the N best cards | `--best N` | remove cards with **×** |

Which cards get the full treatment is decided by `--sort best` (the
default everywhere): cards are ranked by how much they *demonstrate*,
with `>Section` structure weighted well above raw length — a
12,020-char unstructured card scores 41 where a 6,743-char structured one
scores 69. The export also names its own clearest worked examples:

> **Clearest worked examples** — if you only study a few closely, study
> these: **Hero Family**, **Mary Jane**, **Susan & Sera**.

### Field coverage — what your corpus can't teach

Every export reports which fields your cards actually populate:

```
- Field coverage: description 10/10, personality 0/10, scenario 9/10,
  first_mes 10/10, mes_example 0/10, tags 0/10
```

This matters a lot. A corpus where **no** card fills `mes_example` cannot
teach a model to write one — so if generated example dialogue comes back
weak, that line tells you why immediately.

Rather than demanding a field it never demonstrates, the export lets the
data lead. A field no card fills usually isn't missing — the corpus is
deliberately keeping that content somewhere else, and the export says
where:

```
### How these cards use the fields

Let the corpus lead here rather than filling every slot for its own sake:

- **Personality** — no card fills this separate field — these cards put it in
  the `>Personality` section inside Description instead. Following the corpus
  means doing the same; fill this field too only if it helps.
- **Scenario** — used by 9 of 10 cards — include it when it fits.
- **Example Dialogue** — no card here uses this field, so there's no house style
  to follow for it. Optional — include it only if it genuinely adds something.
```

Those fields are then marked `<optional — see the note above>` in the
shape rather than presented as mandatory slots. It's also the signal you
need to decide whether to add cards that *do* carry that field — the
guidance gets sharper as the corpus grows.

Six fields are always present for every card (truncated per `--max-chars`,
never dropped, unless `--full`): **name, description, personality,
scenario, first_mes, mes_example**. Everything else is opt-in and off by
default except `tags` (see `--fields` below) — each one costs real tokens
for content that's often not needed, so you choose what's worth it rather
than the tool deciding for you. `--full` is a separate, independent knob:
it only controls whether *included* fields are truncated, not which
fields appear.

Opting a field in always gets you its **actual content**, truncated per
`--max-chars` like everything else — `lorebook`, `alt_greetings`,
`system_prompt`, and `post_history_instructions` included. (Before, those
four either printed a bare count instead of their text, or — for the two
prompt fields in `compact` — were dropped entirely unless `--full` was
*also* set, so ticking their boxes in the UI appeared to do nothing.)

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
| `--full` | Don't truncate any included field to `--max-chars`. Strictly independent of `--fields`: it controls *how much* of what's included is shown, never *what's* included — any field you opt into always appears with its real content either way |
| `--max-chars` | Per-field truncation cap in non-`--full` mode (default 600) |
| `--tokenizer NAME` | `heuristic` (default) \| `deepseek` \| `glm` \| `gpt` \| any `org/repo` — see "Token counting" above |
| `--no-recursive` | Only scan the top level of given folders |
| `--full-top N` | Show the N most instructive cards complete, trim the rest (default 10) |
| `--best N` | Keep only the N most instructive cards |
| `--sort` | `best` (default, most instructive first) \| `name` \| `file` |
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
