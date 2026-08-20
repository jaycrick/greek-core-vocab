# greek-core-vocab

Pipeline. Fetch [vocab.perseus.org](https://vocab.perseus.org/)'s exact
word-count lists, one per Great Books work with a Greek-text match.
Combine into one master core-vocab freq list.

Output: `output/master_vocab.csv` (+ `.json` mirror). Checked into repo,
`make all` regenerates. One row per distinct Greek headword, sorted by
combined count, descending.

Current state: 138 `great_books.tsv` rows, 80 matched to a
vocab.perseus.org work (108 candidate URNs before sibling-edition
dedup, 96 distinct works actually fetched), 58 skipped (why, below).
27,958 headwords in `master_vocab.csv`. Top of list: ὁ, καί, δέ, εἰμί,
ὅς, ΑΒΓ, μέν, οὗτος, αὐτός, γάρ -- core Greek function words, as
expected, except `ΑΒΓ` (Euclid's own placeholder lemma for a labeled
point in a geometric figure, e.g. "triangle ΑΒΓ" -- real data, not a
bug: it's genuinely that frequent across the *Elements*' 164,768
tokens, the only geometry text in this pipeline).

## Quick start

```sh
uv sync
make all        # editions -> match -> fetch -> combine
```

`data/raw/*` and `output/master_vocab.*` checked in. Fresh clone
already has current output, no network needed. `make all` safe to
re-run: fetch skips anything already recorded as successful. Edit
`aliases.yaml`/`overrides.yaml`/`great_books.tsv`, re-run -- only
match+combine redo, not the fetches.

## The source: vocab.perseus.org

This pipeline previously drew counts from Perseus's OLD hopper vocab
tool (`www.perseus.tufts.edu/hopper/vocablist`), whose `weightedFrequency`
is a probabilistic estimate, whose lemma inventory had confirmed gaps
(no simplex `ἀφίστημι`, no `Σωκράτης` at all, across all 117 fetched
works), and which offered Plato only as multi-dialogue omnibus volumes.
Those gaps forced two external ground-truth workarounds (gold per-work
lemma tagging from `vocabulary-corpus-prep` for six works, a
hand-disambiguated WordHoard parse for Homer) plus a run-time
downweighting table for the Plato omnibus overlap.

Perseus's NEW tool at `vocab.perseus.org` fixes both defects directly:

- **Exact integer token counts**, not a probabilistic estimate.
- **Per-dialogue Plato** and **per-treatise Hippocrates** -- confirmed:
  `tlg0059.tlg001` through `tlg0059.tlg030` are individually selectable,
  and all 17 of this pipeline's Hippocrates treatises now have their
  own edition (the old hopper had two omnibus editions only).
- The specific lemma gaps above are fixed: Thucydides
  (`tlg0003.tlg001.perseus-grc2`) carries `Σωκράτης`, `σεαυτοῦ`,
  `εἴωθα`, `ἀφίστημι`, `καταλείπω`, confirmed by fetching it directly.
- The Iliad carries the proper-noun headwords that were this pipeline's
  original reason to reach for WordHoard instead: `Ἀχιλλεύς` (367),
  `Ἕκτωρ` (454), `Τρώς` (608), confirmed in the fetched data.
- Unicode lemmas directly (no beta-code conversion needed), a stable
  numeric lemma id, and two free reference figures per lemma: its
  frequency across Perseus's whole 21.4M-token corpus, and across
  Perseus's own 1.36M-token Core Reading List.
- `?page=all` returns a work's entire word list in one request, whose
  own stated lemma/token totals let `fetch_vocab.py` verify every fetch
  exactly (parsed rows == stated lemmas, summed counts == stated
  tokens) rather than relying on the old hopper's substring-sniffing
  `looks_valid()`, which the old hopper's real failure modes (504s,
  a response that starts as valid XML and turns into a raw Java stack
  trace mid-document) had already defeated once.

As a result: `vocabulary-corpus-prep` is dropped entirely (nothing left
for it to fix), and the WordHoard Homer parse is kept only as a
standing cross-check (`make report`, below), not as a count source.

### Coverage regression, accepted

vocab.perseus.org's catalog (901 editions) is NOT a superset of the old
hopper's. About three dozen works this pipeline used to fetch aren't in
the new catalog at all:

| author | lost | detail |
|---|---|---|
| Euripides | 16 of 18 | only *Heracles* and *Bacchae* remain |
| Aristophanes | 6 of 11 | only Clouds/Birds/Lysistrata/Frogs/Ecclesiazusae remain |
| Plato | 9 dialogues | Protagoras, Euthydemus, Ion, Meno, Gorgias, Timaeus, Critias, Laws, Seventh Letter |
| Aristotle | 11 works | Posterior Analytics, On the Heavens, On Generation and Corruption, Metaphysics, Minor biological works, On the Motion/Gait/Generation of Animals, **Nicomachean Ethics, Politics, Rhetoric** |
| Epictetus | all | *The Discourses* has no edition at all |
| Marcus Aurelius | all | *The Meditations* has no edition at all |
| Plutarch | 34 of ~50 | only 16 *Lives* have an edition (see below) |

Meanwhile vocab.perseus.org ADDS coverage the old hopper never had:
Aristotle's *Categories*, *De anima*, *Physica*, the *Organon*, and
several biological/psychological works now have real editions (19
Aristotle works fetched here, vs. 6 before), and every one of
Hippocrates' 17 treatises is now its own text rather than one shared
omnibus.

This trade is accepted, not worked around: `master_vocab.csv` is a
clean break to the new source, nothing patched back in from the old
one. `match_books.py`'s own printed summary lists the current skip set
exactly; see "Rows needing special handling" below for the two
structurally special cases (Plutarch, and one split-edition Aristotle
row).

## How it works

1. `fetch_editions.py` scrapes vocab.perseus.org's `/editions/` page,
   the full catalog of selectable Greek editions -> one record per
   edition (urn, author, title, whether it's on Perseus's own Core
   Reading List) -> `data/perseus_editions.json`.
2. `great_books.tsv`: input list. title/author/group/year/seq rows,
   Greek-writing authors only (see `SOURCES.md`).
3. `match_books.py` resolves each row to zero or more CTS URNs ->
   `data/matches.yaml`. Order:
   - `overrides.yaml` (exact author+title) -- rows a human had to pin
     explicitly; see that file's own header.
   - `aliases.yaml` -- title pairs sharing no usable normalized-equal
     string (different English rendering, or an English GBWW title
     against vocab.perseus.org's Latin one -- most of Hippocrates and
     about half of Aristotle are catalogued in Latin). Alias-driven
     matches require EXACT equality, not containment -- see
     `aliases.yaml`'s own header for why that matters here.
   - General matching otherwise: normalize both titles (lowercase,
     drop leading "the"/"a"/"an", strip punctuation), match on
     equality, word-level containment either direction, or exact
     match against one comma-separated component of a Perseus title
     that groups several works under one selectable title.
   - Zero match -> `matched_urns: []` + `skip_reason`. Always
     recorded, never silent drop.
   A matched row's `matched_urns` may hold more than one URN for the
   SAME work -- 36 works site-wide have multiple editions (e.g. every
   Aeschylus play has an `opp-grc3` and a `perseus-grc2` edition,
   genuinely different texts). `match_books.py` doesn't resolve that;
   `fetch_vocab.py` does, next.
4. `fetch_vocab.py` resolves sibling editions (probes each candidate's
   token count, keeps the Core-Reading-List-marked edition if there is
   one, else the one with more tokens, else the lower URN string --
   losers recorded as `alternate_urns`, never silently dropped), then
   fetches each winner's full word list (`?page=all`, one request) ->
   `data/raw/<urn-id>.html`, verified against the page's own stated
   lemma/token totals -> `data/fetch_manifest.json`.
5. `combine.py` parses every cached file, groups entries by NFC
   Unicode headword across every fetched work, sums each headword's
   exact `count`, writes `output/master_vocab.csv`/`.json`.

## Rows needing special handling

**Plutarch.** One row in `great_books.tsv`: "The Lives of the Noble
Grecians and Romans". vocab.perseus.org's Plutarch catalog (`tlg0007`)
has only 22 editions total: 16 individual *Lives* and 6 of Plutarch's
own "Comparison of X and Y" essays (excluded -- not part of the Lives
themselves). 13 of those 22 editions carry no title metadata at all --
the site itself renders them as "unknown," confirmed live, not a
scraping gap -- so title matching can't reach them at all.
`overrides.yaml` pins the row to an explicit list of 16 URNs, each
identified by fetching its Scaife reader page (`/rr/<urn>/`), whose
`<title>` gives the work's real Greek name (e.g. `tlg0007.tlg002` ->
Ῥωμύλος, Romulus). This is a real drop from the old hopper's ~50
individually-fetchable Lives to 16.

**Aristotle, "On Youth and Old Age, On Life and Death, On Breathing."**
One GBWW row combines three short treatises. vocab.perseus.org
catalogs the first two together as one edition (`tlg0086.tlg018`) but
"On Breathing" (*De respiratione*) as a separate one (`tlg0086.tlg037`)
-- no single alias target can match both, so `overrides.yaml` pins both
URNs directly.

**Everything else skipped**: real absence in the new catalog, not
matching failure -- see the coverage-regression table above.
`match_books.py`'s own printed summary lists every skip.

## Sibling-edition dedup

36 CTS works site-wide have more than one edition. In this pipeline's
subset that's every Aeschylus play (`opp-grc3` vs. `perseus-grc2`),
Euripides' *Heracles*, and four Aristotle works (duplicate `1st1K-grc1`/
`grc2` editions, or an alternate-recension text like *Physica (textus
alter)*). These are genuinely different texts -- confirmed: Aeschylus's
*Persians* is 5,081 tokens in `opp-grc3`, 5,665 in `perseus-grc2` --
so counting both would double-count the work. `fetch_vocab.py` groups
candidate URNs by CTS `<textgroup>.<work>`, probes each sibling's own
token count, and fetches only the winner: the Core-Reading-List-marked
edition if one is marked, else the edition with the most tokens, else
the lexicographically lower URN. The losing sibling(s) are recorded in
`data/fetch_manifest.json`'s `alternate_urns` field, not silently
dropped.

`match_books.py`'s alias matching also guards against a related risk at
the title level: vocab.perseus.org's many short Latin titles collide
under substring containment alone (Hippocrates' alias target "De
diaeta in morbis acutis" word-subsequence-contains the separate,
unrelated work "De diaeta"; Aristotle's "Physica" would otherwise also
catch "Physica (textus alter)"). Alias-driven searches require exact
normalized equality for this reason -- see `aliases.yaml`'s header.

## Collapsing and combining

vocab.perseus.org's own headword is already an NFC Unicode string
(no beta-code conversion needed, unlike the old hopper). It doesn't
fully disambiguate homographs either -- two distinct LSJ senses can in
principle share one headword string -- so grouping on the headword
alone is still the direct reading of "collapse identical forms into
one reading," and the natural join key across every fetched work.
Each group's exact `count` is **summed** across every work it appears
in -- a word both locally frequent in one work and used across many
works ranks highest. Direct reading of "combine into one master list of
frequencies," standard way to merge freq lists.

## Output columns (`output/master_vocab.csv`)

- `headword_unicode` -- lemma, Unicode Greek, NFC-normalized (the
  actual join key).
- `lemma_id` -- vocab.perseus.org's own stable numeric lemma id.
- `count` -- summed exact token count across every matched work.
- `works_count` -- distinct works it appeared in.
- `short_definition` -- vocab.perseus.org's own short gloss (first
  non-empty one seen).
- `corpus_freq_per_10k` -- this lemma's frequency across
  vocab.perseus.org's ENTIRE corpus (21,441,714 tokens, all 901
  editions) -- a reference figure, not summed, since it's the same
  number regardless of which fetched work reports it.
- `core_freq_per_10k` -- same, but across Perseus's own Core Reading
  List (1,355,159 tokens, 42 editions) instead.
- `source_urns` -- semicolon-separated CTS URNs it was counted from.

Full source list, every text/tool credited: `SOURCES.md`.

## Homer comparison report (`make report`)

Not part of `make all`. Runs `homer_vocab.py` (WordHoard's
hand-disambiguated Iliad/Odyssey tagging, via
`jaycrick/ag-cloze-cards`'s own parser) and `compare_homer.py`, which
compares it against vocab.perseus.org's own Iliad/Odyssey counts --
the standing cross-check for whether an automatic parse still misses
anything a hand-checked one catches, now that vocab.perseus.org (not
WordHoard) is what `master_vocab.csv` actually counts Homer from.
Writes a single self-contained, sortable `output/homer_compare.html`
(layout/copy lives in `compare_homer_template.html`, filled in at run
time -- don't hand-edit the generated HTML). Needs
`$AG_CLOZE_CARDS_REPO` (`make homer-clone`).

## Re-running / extending

- Add rows to `great_books.tsv` (same 5 tab-separated columns), `make
  all` -- new titles matched automatic. Add an `aliases.yaml`/
  `overrides.yaml` entry only if a title needs one (the scripts' own
  module docstrings explain the schema of each).
- `make fetch REDO=1` re-fetches every matched work, ignores cache
  (e.g. vocab.perseus.org's own data changed since).
- `uv run python3 fetch_vocab.py --redo` -- same, direct.
- `$AG_CLOZE_CARDS_REPO` defaults to `~/git_repos/ag-cloze-cards`;
  override with the `AG_CLOZE_CARDS_REPO` env var (`make homer`/
  `homer-clone` read it too) if cloned elsewhere. Only needed for
  `make report`.
- Lint: `uv run ruff check .`.
