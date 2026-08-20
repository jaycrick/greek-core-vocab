# Sources

## Word-frequency data

All counts, headwords, and short definitions in `output/master_vocab.*`
come from the [Perseus Digital Library](https://www.perseus.tufts.edu/)
(Tufts University)'s **Greek Vocabulary Tool**:
<https://vocab.perseus.org/>.

Each work's word list gives, per lemma: an exact token count within
that work, a short gloss, and two reference figures -- the lemma's own
frequency across Perseus's entire corpus (21,441,714 tokens, all 901
editions) and across Perseus's own Core Reading List (1,355,159
tokens, 42 editions). The short gloss's own underlying lexicon isn't
stated per-entry on this newer tool the way the old hopper's
`lexiconQueries` cross-references were; treat it as Perseus's own
editorial pick.

This pipeline previously drew from the OLD Perseus hopper tool
(`www.perseus.tufts.edu/hopper/vocablist`), whose `weightedFrequency`
was a probabilistic estimate rather than an exact count, and whose
Greek Vocabulary Tool has since been superseded by vocab.perseus.org --
see README.md for the specific gaps that motivated switching (and for
why two external ground-truth sources that gap once required,
`vocabulary-corpus-prep` and `ag-cloze-cards`'s WordHoard parse, are no
longer needed for `master_vocab.csv` itself).

## The works fetched from vocab.perseus.org

Every text is Perseus's own digitization/edition of the Greek original,
one CTS URN per row of `data/matches.yaml`'s `matched_urns` (after
`fetch_vocab.py`'s sibling-edition dedup picks one edition per work);
the exact per-work URN list, and whether each fetch's counts represent
the full lemma inventory, is `data/fetch_manifest.json`. The raw
fetched HTML itself is cached verbatim in `data/raw/`.

| author | works fetched |
|---|---|
| Homer | 2 (Iliad, Odyssey) |
| Aeschylus | 7 |
| Sophocles | 8 |
| Euripides | 2 (only *Heracles* and *Bacchae* remain in this catalog) |
| Aristophanes | 5 |
| Herodotus | 1 |
| Thucydides | 1 |
| Plato | 16 individual dialogues (no longer omnibus volumes) |
| Aristotle | 19 |
| Hippocrates | 17 (each its own treatise, no longer one shared omnibus) |
| Galen | 1 |
| Euclid | 1 |
| Plutarch | 16 individual *Lives* (see README.md's "Rows needing special handling") |

(Epictetus and Marcus Aurelius have no edition in this catalog at all;
Archimedes, Apollonius of Perga, and Nicomachus of Gerasa never did.
See README.md's coverage-regression table for the full accounting of
what this pipeline's move to vocab.perseus.org gained and lost
relative to the old hopper.)

## The Iliad and Odyssey, cross-checked against ag-cloze-cards

[`jaycrick/ag-cloze-cards`](https://github.com/jaycrick/ag-cloze-cards)
is a sibling repo (this pipeline is itself one of its dependencies, as
a definition-fallback source) whose Homer Anki deck is built on
Northwestern University's **WordHoard**/Chicago Homer project: a
hand-disambiguated morphological tagging of early Greek epic (Martin
Mueller). `homer_vocab.py` reads it by calling that repo's own
`ag_cloze_cards.corpus.WordHoardHomerAdapter` (via `uv run` inside
`$AG_CLOZE_CARDS_REPO`), not a local reimplementation of WordHoard's
XML format.

This is no longer a count source for `master_vocab.csv` -- vocab.perseus.org's
own Iliad/Odyssey word lists now carry the proper-noun headwords
(Ἀχιλλεύς, Ἕκτωρ, Ὀδυσσεύς, ...) that were this pipeline's original
reason to reach for WordHoard instead. It remains a standing
cross-check (`make report` / `compare_homer.py`,
`output/homer_compare.html`): how close does an automatic parse come
to a hand-disambiguated one, for the two texts most likely to trip one
up.

| author | work | work id |
|---|---|---|
| Homer | The Iliad | `homer:IL` |
| Homer | The Odyssey | `homer:OD` |

## The input list

`great_books.tsv` (title/author/group/year/sequence) is copied from a
table of the *Great Books of the Western World* set (Robert Maynard
Hutchins, ed.; Encyclopædia Britannica, Inc., 1952 and later printings)
supplied by this repo's author, restricted to authors who wrote in
Greek (see `README.md` for why the Latin-writing authors originally in
that table -- Lucretius, Virgil -- were removed rather than left to
show up as an unmatched skip).

## Software

- [`requests`](https://requests.readthedocs.io/),
  [`PyYAML`](https://pyyaml.org/) -- HTTP + the `aliases.yaml`/
  `overrides.yaml`/`data/matches.yaml` file format.
- [`uv`](https://docs.astral.sh/uv/), [`ruff`](https://docs.astral.sh/ruff/)
  -- dependency management, lint/format.
