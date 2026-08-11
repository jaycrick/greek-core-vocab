# greek-core-vocab

Pipeline. Fetch Perseus Greek Vocabulary Tool word-freq lists, one per
Great Books work with Greek-text match. Combine into one master
core-vocab freq list.

Output: `output/master_vocab.csv` (+ `.json` mirror). Checked into
repo, `make all` regenerates. One row per distinct Greek headword,
sorted combined weighted freq, descending.

Current state: 138 `great_books.tsv` rows, 100 matched (117 unique
Perseus URNs, all fetched OK), 38 skipped (why, below). 34,484
headwords in `master_vocab.csv`. Top of list: ὁ, καί, δέ, εἰμί, ὅς,
τις, οὗτος, αὐτός, μέν, οὐ -- core Greek function words, as expected.

## Quick start

```sh
uv sync
make all        # work-list -> match -> fetch -> combine
```

`data/raw/*` and `output/master_vocab.*` checked in. Fresh clone
already has current output, no network needed. `make all` safe to
re-run: fetch skips cached URNs. Edit `aliases.yaml`/`overrides.yaml`/
`great_books.tsv`, re-run -- only match+combine redo, not fetches.

## How it works

1. `fetch_work_list.py` scrapes Perseus's vocablist page, full catalog
   of selectable Greek works -> `data/perseus_works.json` (urn,
   author, title, edition per work).
2. `great_books.tsv`: input list. title/author/group/year/seq rows,
   Greek-writing authors only (see `SOURCES.md`).
3. `match_books.py` resolves each row to zero or more Perseus URNs ->
   `data/matches.yaml`. Order:
   - `overrides.yaml` (exact author+title, or every row by one
     author) -- two rows needed human judgment call, see below.
   - `aliases.yaml` -- title pairs sharing no usable substring
     (different English rendering, transliteration vs translation,
     Latin editorial title, etc).
   - General matching otherwise: normalize both titles (lowercase,
     drop leading "the"/"a"/"an", strip punctuation), match on
     equality, word-level containment either direction, or exact
     match against one comma-separated component of Perseus title
     (Perseus groups several works -- mostly Plato dialogues -- under
     one selectable comma-joined title; resolves e.g. Cratylus/
     Theaetetus/Sophist/Statesman onto shared URN, no hardcoding).
   - Zero match -> `matched_urns: []` + `skip_reason`. Always
     recorded, never silent drop.
4. `fetch_vocab.py` fetches every unique matched URN's vocab (dedup
   here stops Plato's ~25 rows / Hippocrates' 17 rows from double-
   counting) -> `data/raw/<urn>.xml`, fallback ladder below ->
   `data/fetch_manifest.json`, records what happened per URN.
5. `combine.py` parses every cached file, groups entries by raw
   headword (the "collapse identical forms" step), sums
   weightedFrequency per group across every work, converts beta-code
   headword to Unicode, writes `output/master_vocab.csv`/`.json`.

## Rows needing special handling

**Plutarch.** One row in `great_books.tsv`: "The Lives of the Noble
Grecians and Romans" -- Perseus has no single text by that name. Lists
each of ~50 biographies as own work (translator Bernadotte Perrin),
plus ~18 "Comparison of X and Y" essays, plus dozens unrelated Moralia
essays (Latin titles, different translators). `overrides.yaml` expands
that one row to every Perrin-translated, non-"Comparison of ..." work
-- Lives only, nothing else.

**Hippocrates.** 17 separate treatise titles in `great_books.tsv`
(Oath, On Ancient Medicine, Aphorisms, ...). Perseus offers two
omnibus editions only, no per-treatise pick, no literal title match
for any of the 17. `overrides.yaml` points all 17 at the single
English-edition omnibus (`Perseus:text:1999.01.0249`, ed. W. H. S.
Jones), fetched + counted once, not 17 times.

**Everything else skipped**: real absence, not matching failure.
Archimedes, Apollonius of Perga, Nicomachus of Gerasa: not in
Perseus's Greek catalog at all. Most Aristotle *Organon*/*Physics*/
biological-psych works: same. "Dialogues" (Plato), "The Oresteia"
(Aeschylus): category-header rows, not real texts. `match_books.py`'s
own printed summary lists every skip.

## Fetch fallback ladder

`output=xml&filt=100` (every word, not just a percentile) unreliable
for big/heavy texts. Two failure modes hit fetching this repo's own
data: 504s near-instant for the Iliad some runs (looks like cached
negative response, not real per-request timeout); one work
(Aristophanes' *Peace*) reliably returns HTTP 200, starts as valid
XML, turns into raw Java stack trace mid-document (server-side
Hibernate lazy-init exception hit rendering one lemma). `looks_valid()`
actually parses every XML response with ElementTree, not
substring-sniffs -- a substring check let that broken response through
once. `output=table` at the same `filt=100` hits neither failure mode
(same data, HTML not XML); dropping to `filt=75`/`50` (still XML) also
works reliably. `fetch_vocab.py` tries per URN in order till one
works: `xml,100` -> `table,100` -> `xml,75` -> `xml,50`. Whichever
succeeds recorded per-URN in `data/fetch_manifest.json` -- check it to
know whether a work's contribution is full vocab or a percentile
subset. This repo's own data: 114 works via `xml,100`, 2 via
`table,100` (Herodotus's *Histories*; Aristophanes' *Peace*), 1 via
`xml,75` (Aristotle's *Athenian Constitution*).

## Collapsing and combining

Perseus's tool already aggregates by lemma within one work --
`headword` is a beta-code lemma, not a raw inflected surface form.
Doesn't fully disambiguate homographs though (two distinct LSJ senses
can share one `headword` string, split apart only in that entry's
lexicon-query refs) -- "for forms that are identical, collapse them
into one reading" read here as: group by raw headword string, full
stop, within a single work and across every matched work. Each group's
`weightedFrequency` values **summed** across every work it appears in
-- a word both locally frequent in one work and used across many works
ranks highest. Direct reading of "combine into one master list of
frequencies," standard way to merge freq lists.

## Output columns (`output/master_vocab.csv`)

- `headword_unicode` -- lemma, Unicode Greek.
- `headword_betacode` -- same lemma, Perseus's own beta-code (the
  actual join key).
- `combined_weighted_frequency` -- summed `weightedFrequency` across
  every matched work containing this headword.
- `works_count` -- distinct fetched works (URNs) it appeared in.
- `short_definition` -- Perseus's own short gloss (first non-empty one
  seen).
- `source_urns` -- semicolon-separated Perseus URN ids (short form),
  where it came from.

Full source list, every text/dictionary/tool credited: `SOURCES.md`.

## Re-running / extending

- Add rows to `great_books.tsv` (same 5 tab-separated columns), `make
  all` -- new titles matched automatic. Add an `aliases.yaml`/
  `overrides.yaml` entry only if a title needs one (the scripts' own
  module docstrings explain the schema of each).
- `make fetch REDO=1` re-fetches every matched URN, ignores cache
  (e.g. Perseus's own data changed since).
- `uv run python3 fetch_vocab.py --redo` -- same, direct.
- Lint: `uv run ruff check .`.
