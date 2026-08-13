# greek-core-vocab

Pipeline. Fetch Perseus Greek Vocabulary Tool word-freq lists, one per
Great Books work with Greek-text match. For a handful of works,
substitute gold per-work lemma counts from
[`greek-learner-texts/vocabulary-corpus-prep`](https://github.com/greek-learner-texts/vocabulary-corpus-prep)
(see "Ground truth from vocabulary-corpus-prep", below) or from
[`jaycrick/ag-cloze-cards`](https://github.com/jaycrick/ag-cloze-cards)'s
own WordHoard-tagged Homer parse (see "Ground truth for Homer from
ag-cloze-cards", below) instead. Combine into one master core-vocab
freq list.

Output: `output/master_vocab.csv` (+ `.json` mirror), plus
`output/lemma_join_report.tsv` (how each external-source lemma joined
onto the Perseus-derived vocabulary). Checked into repo, `make all`
regenerates. One row per distinct Greek headword, sorted combined
weighted freq, descending.

Current state: 138 `great_books.tsv` rows, 92 matched to Perseus (113
unique Perseus URNs, all fetched OK), 8 matched to an external
gold-tagged source instead (6 vocabulary-corpus-prep, 2 Homer/
ag-cloze-cards), 38 skipped (why, below). 36,240 headwords in
`master_vocab.csv`. Top of list: ὁ, καί, δέ, εἰμί, ὅς, τις, οὗτος,
αὐτός, οὐ, μέν -- core Greek function words, as expected.

## Quick start

```sh
uv sync
make corpus-clone                        # once, or point CORPUS_REPO at an existing clone
make homer-clone                         # once, or point AG_CLOZE_CARDS_REPO at an existing clone
make all        # work-list -> match -> fetch -> corpus -> homer -> combine
```

`data/raw/*` and `output/master_vocab.*` checked in. Fresh clone
already has current output, no network needed (beyond
`corpus-clone`'s one-time ~50 MB git clone and `homer-clone` + that
repo's own `fetch`, which caches its own WordHoard download). `make
all` safe to re-run: fetch skips cached URNs. Edit `aliases.yaml`/
`overrides.yaml`/`corpus_map.yaml`/`great_books.tsv`, re-run -- only
match+corpus+homer+combine redo, not Perseus fetches.

## Ground truth from vocabulary-corpus-prep

Perseus's Greek Vocabulary Tool has two real limitations, confirmed
against the raw fetched data:

- **Lemma-inventory gaps.** `data/raw/1999.01.0199.xml` (Thucydides)
  has `e)fi/sthmi`, `sunafi/sthmi`, `prosafi/sthmi` but no simplex
  `a)fi/sthmi`; it has `e)gkatalei/pw`, `proskatalei/pw` but no
  `katalei/pw`. `Σωκράτης`, `σεαυτοῦ`, `ἐπειδή`, `εἴωθα` are absent
  from Perseus's entire fetched vocabulary, all 117 works.
- **No per-dialogue Plato.** Perseus's vocab tool offers Plato only as
  multi-dialogue omnibus volumes -- probing individual-dialogue URNs
  (e.g. `1999.01.0170`) returns an HTML error page or a
  `perseus.util.DatabaseException`, not a real per-work selection.

`vocabulary-corpus-prep` publishes gold per-work lemma tagging
(reconciled across OGA/GLAUX/Gorman/Scaife -- see its own `CORPUS.md`)
for 49 Attic prose works. Six overlap `great_books.tsv`, resolved via
`corpus_map.yaml` ahead of the normal Perseus matching:
Thucydides *History* (Books 1-5 only -- Perseus's 8-book
`1999.01.0199` is dropped outright, so **Books 6-8 vocabulary,
including the Sicilian Expedition, is not represented anywhere in the
master list**), and Plato's Euthyphro, Apology, Crito, Symposium,
Republic.

**Scale compatibility.** Perseus's `weightedFrequency` summed over a
whole work recovers that work's token count: Perseus's Republic volume
`1999.01.0167` sums to 87,466; the corpus repo's own Republic token
count is 87,070 -- 0.5% apart. Corpus lemma counts and Perseus weighted
frequencies are added directly, on the same scale.

### Plato overlap, explicit double-counting accounted for

Perseus has no way to select a single dialogue -- each dialogue's
row instead matches a whole omnibus volume, several of which pair a
corpus-covered dialogue with one that isn't in the corpus at all. Where
that happens, the *volume is kept* (for the dialogue(s) with no other
source) but *downweighted* by the proportion of it the corpus already
covers, computed at run time (`combine.py`) from this run's own data,
not hardcoded:

| Perseus URN | Volume contents | Corpus-covered | Dup tokens | Volume Σwf | Scale applied |
|---|---|---|---|---|---|
| `1999.01.0169` | Euthyphro, Apology, Crito, **Phaedo** | Euthyphro, Apology, Crito | 17,982 | 39,527 | **×0.545** |
| `1999.01.0173` | **Parmenides, Philebus**, Symposium, **Phaedrus** | Symposium | 17,181 | 65,716 | **×0.739** |
| `1999.01.0167` | Republic | Republic | 87,070 | 87,466 | dropped (99.5% duplicated) |

`1999.01.0167` and `1999.01.0199` (Thucydides) are removed from
`data/matches.yaml` entirely -- displaced, not merely scaled, since
every dialogue/book they'd otherwise contribute is fully covered by a
corpus work. `1999.01.0169`/`1999.01.0173` stay, scaled, because
Phaedo/Parmenides/Philebus/Phaedrus have no other source. The other 6
Plato volumes (Laws, Cratylus group, Charmides group, Euthydemus
group, Ion/Timaeus group, Epistles) have no corpus overlap and keep
scale 1.0.

### GBWW Vol. 7 (Plato) audit

Checked against the actual *Great Books of the Western World* Plato
volume table of contents: 25 works (24 dialogues + The Seventh
Letter). All 25 are already rows in `great_books.tsv` (seq 63-87) --
nothing was missing, nothing added. The bare `Dialogues` row (seq 62)
stays a documented category-header skip.

### Lemma join

The two lemma inventories don't fully agree. Most corpus lemmas match
an existing Perseus Unicode headword exactly. The rest split two ways,
both recorded in `output/lemma_join_report.tsv` per (work, lemma):

- **orthographic variants** (e.g. `σῴζω`/`σώζω`, `πρωΐ`/`πρωί`) --
  joined via an accent-blind fallback key (NFD, strip combining marks,
  casefold) against Perseus's own headword set, used only when
  unambiguous.
- **genuine gaps** -- new rows, `perseus_weighted_frequency: 0`. On
  the current data this is dominated by Thucydides' proper-noun-heavy
  vocabulary (ethnonyms, place names, personal names throughout the
  Peloponnesian War narrative) plus the confirmed Perseus lemma gaps
  above (`Σωκράτης`, `καταλείπω`, `ἀφίστημι`, ...).

### Top-100 comparison report

`make report` (`compare_top100.py`) is a sanity check, not part of the
core pipeline (not in `make all`): it ranks `master_vocab.csv`'s top
100 headwords against vocabulary-corpus-prep's own top 100 -- but on
the corpus repo's own terms, aggregated across *all* 49 of its works,
not just the 6 this pipeline draws on. Writes a single self-contained,
sortable `output/top100_compare.html` (layout/copy lives in
`compare_top100_template.html`, filled in at run time -- don't hand-edit
the generated HTML). 78 of the top 100 agree; most of the other 44
trace to genre -- this pipeline spans 121 works across every genre
(epic, tragedy, comedy, history, oratory, philosophy), the corpus repo
is Attic prose only. See the report itself for the full breakdown.

## Ground truth for Homer from ag-cloze-cards

Perseus's Iliad/Odyssey vocab-tool output is an automatic parse, and
it misses genuine Homeric vocabulary that a hand-checked tagging
catches. `homer_vocab.py` (`make homer`) replaces both instead: it
shells out to `jaycrick/ag-cloze-cards`'s own `uv` environment (cloned
locally to `$AG_CLOZE_CARDS_REPO`, default `~/git_repos/ag-cloze-cards`)
and calls that repo's `ag_cloze_cards.corpus.WordHoardHomerAdapter`
directly -- Northwestern's hand-disambiguated WordHoard/Chicago Homer
tagging, the same tokenization that repo's own Homer Anki deck is
built from -- rather than reimplementing WordHoard's XML parsing here
and risking it drifting from that repo's own parsing decisions (see
`homer_vocab.py`'s docstring). `corpus_map.yaml` resolves the Iliad and
Odyssey rows to `homer:IL`/`homer:OD` and fully displaces Perseus's
`1999.01.0133`/`1999.01.0135` -- unlike the Plato omnibus volumes,
WordHoard's Homer corpus covers each epic completely, so there is no
partial-overlap case to downweight.

**Scale check.** Perseus's Iliad volume sums to a `weightedFrequency`
of 102,658; WordHoard counts 111,710 actual tokens for the same text
(8.8% apart). Odyssey: Perseus 83,072 vs. WordHoard 87,084 (4.8%
apart) -- the same order of magnitude as the Republic calibration
above, looser because WordHoard's count is exact where Perseus's is a
probabilistic estimate over ambiguous morphology, but still close
enough to combine directly.

**What WordHoard adds.** The join report's corpus-only rows for
`homer:IL`/`homer:OD` are dominated by exactly what a hand-tagged
epic parse should catch and an automatic one might not: major
character/place names as their own high-frequency headwords
(Ἀχιλλεύς, Ἕκτωρ, Ὀδυσσεύς, Ἀγαμέμνων, Πρίαμος, Ἀθήνη, Τρώς, Ἀχαιός)
and genuine Ionic/epic dialect forms (`ξεῖνος` for Attic ξένος,
`θύρη` for θύρα, `ἐύς` "noble, good") that Perseus's Iliad/Odyssey
headword list doesn't carry as distinct entries.

## How it works

1. `fetch_work_list.py` scrapes Perseus's vocablist page, full catalog
   of selectable Greek works -> `data/perseus_works.json` (urn,
   author, title, edition per work).
2. `great_books.tsv`: input list. title/author/group/year/seq rows,
   Greek-writing authors only (see `SOURCES.md`).
3. `match_books.py` resolves each row to zero or more Perseus URNs, or
   a corpus work id -> `data/matches.yaml`. Order:
   - `corpus_map.yaml` (`corpus_works`: exact author+title -> a
     work id in one of two external gold-tagged sources, `source:`
     tagged) -- resolves that row to gold local lemma tagging instead
     of Perseus; see "Ground truth from vocabulary-corpus-prep" and
     "Ground truth for Homer from ag-cloze-cards" above.
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
   - Displacement pass: any Perseus URN a `corpus_works` entry's
     `displaces_urns` names is removed from every other row's
     `matched_urns` (recorded as `displaced_urns`, not silently
     dropped) -- this is what removes `1999.01.0167`/`1999.01.0199`
     from the Perseus fetch list entirely.
4. `fetch_vocab.py` fetches every unique matched URN's vocab (dedup
   here stops Plato's ~25 rows / Hippocrates' 17 rows from double-
   counting) -> `data/raw/<urn>.xml`, fallback ladder below ->
   `data/fetch_manifest.json`, records what happened per URN.
5. `corpus_vocab.py` counts lemma frequencies for every
   `vocabulary-corpus-prep`-sourced row from
   `$CORPUS_REPO/one/<work_id>/lemma.tsv` -> `data/corpus_counts.json`.
   Local, no network (beyond cloning `$CORPUS_REPO` once).
6. `homer_vocab.py` counts lemma frequencies for the two Homer rows by
   calling `$AG_CLOZE_CARDS_REPO`'s own WordHoard parser (via
   `uv run` inside that project) -> `data/homer_counts.json`. Local, no
   network beyond that repo's own one-time `fetch`.
7. `combine.py` parses every cached Perseus file, downweights the
   Plato volumes `corpus_map.yaml`'s `overlaps` names (see the table
   above), groups entries by NFC Unicode headword/lemma across every
   source (the "collapse identical forms" step), sums frequencies per
   group, writes `output/master_vocab.csv`/`.json` +
   `output/lemma_join_report.tsv`.

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
data: 504s near-instant for the Iliad some runs, back when it was
still fetched from Perseus (looks like cached negative response, not
real per-request timeout -- now moot, the Iliad is Homer/ag-cloze-cards-
sourced, see above, but the fallback ladder this motivated stays);
one work (Aristophanes' *Peace*) reliably returns HTTP 200, starts as
valid XML, turns into raw Java stack trace mid-document (server-side
Hibernate lazy-init exception hit rendering one lemma). `looks_valid()`
actually parses every XML response with ElementTree, not
substring-sniffs -- a substring check let that broken response through
once. `output=table` at the same `filt=100` hits neither failure mode
(same data, HTML not XML); dropping to `filt=75`/`50` (still XML) also
works reliably. `fetch_vocab.py` tries per URN in order till one
works: `xml,100` -> `table,100` -> `xml,75` -> `xml,50`. Whichever
succeeds recorded per-URN in `data/fetch_manifest.json` -- check it to
know whether a work's contribution is full vocab or a percentile
subset. This repo's own data (113 fetched URNs, after the corpus/Homer
displacements above removed 4): 110 works via `xml,100`, 2 via
`table,100` (Herodotus's *Histories*; Aristophanes' *Peace*), 1 via
`xml,75` (Aristotle's *Athenian Constitution*).

## Collapsing and combining

Perseus's tool already aggregates by lemma within one work --
`headword` is a beta-code lemma, not a raw inflected surface form.
Doesn't fully disambiguate homographs though (two distinct LSJ senses
can share one `headword` string, split apart only in that entry's
lexicon-query refs) -- "for forms that are identical, collapse them
into one reading" read here as: group by headword/lemma, full stop,
within a single work and across every matched work -- Perseus and
corpus alike. Since Perseus's own identifier is beta-code and the
corpus repo's is Unicode, the actual join key is NFC-normalized
Unicode (`beta_code.beta_code_to_greek` converts the Perseus side).
Each group's Perseus `weightedFrequency` (scaled per the overlap table
above where applicable) and corpus lemma count are **summed** across
every work it appears in -- a word both locally frequent in one work
and used across many works ranks highest. Direct reading of "combine
into one master list of frequencies," standard way to merge freq
lists.

## Output columns (`output/master_vocab.csv`)

- `headword_unicode` -- lemma, Unicode Greek, NFC-normalized (the
  actual join key).
- `headword_betacode` -- the same lemma's Perseus beta-code form(s),
  semicolon-joined (usually one; more than one iff two distinct
  beta-code spellings converge on the same Unicode form -- happens
  once in the current data, `Ὀλυμπιάς`). Blank for a headword that
  only ever came from the corpus repo.
- `combined_weighted_frequency` -- `perseus_weighted_frequency +
  corpus_count`.
- `perseus_weighted_frequency` -- summed (and, where a volume is
  scaled, downweighted) Perseus `weightedFrequency` across every
  matched work containing this headword. `0` for a corpus-only row.
- `corpus_count` -- summed lemma-token count from every
  `vocabulary-corpus-prep` work containing this lemma. `0` for a
  Perseus-only row.
- `works_count` -- distinct works (Perseus URNs + corpus work ids) it
  appeared in.
- `short_definition` -- Perseus's own short gloss (first non-empty one
  seen); corpus-only rows have none, the corpus repo carries no
  glosses.
- `source_urns` -- semicolon-separated Perseus URN ids (short form)
  and/or corpus work ids, where it came from.

Full source list, every text/dictionary/tool credited: `SOURCES.md`.

## Re-running / extending

- Add rows to `great_books.tsv` (same 5 tab-separated columns), `make
  all` -- new titles matched automatic. Add an `aliases.yaml`/
  `overrides.yaml`/`corpus_map.yaml` entry only if a title needs one
  (the scripts' own module docstrings explain the schema of each).
- `make fetch REDO=1` re-fetches every matched URN, ignores cache
  (e.g. Perseus's own data changed since).
- `uv run python3 fetch_vocab.py --redo` -- same, direct.
- `$CORPUS_REPO` defaults to `~/git_repos/vocabulary-corpus-prep`;
  override with the `CORPUS_REPO` env var (`make corpus`/`corpus-clone`
  read it too) if cloned elsewhere. Pull that repo and re-run `make
  corpus combine` to pick up any upstream tagging changes.
- `$AG_CLOZE_CARDS_REPO` defaults to `~/git_repos/ag-cloze-cards`;
  override with the `AG_CLOZE_CARDS_REPO` env var (`make homer`/
  `homer-clone` read it too) if cloned elsewhere. Pull that repo (and
  re-run its own `fetch` if WordHoard's data changed) then `make homer
  combine` to pick up changes to its Homer parsing.
- Lint: `uv run ruff check .`.
