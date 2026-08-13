# Sources

## Word-frequency data

All weighted-frequency data, headwords, and short definitions in
`output/master_vocab.*` come from the [Perseus Digital
Library](https://www.perseus.tufts.edu/hopper/)'s **Greek Vocabulary
Tool** (Tufts University):
<https://www.perseus.tufts.edu/hopper/vocablist?lang=greek>.

Per that tool's own [help
page](https://www.perseus.tufts.edu/hopper/help/vocab): each word's
short definition is "automatically extracted from various lexica in
the Perseus collections... the one listed first in the dictionary
entry for each word." Every fetched entry's own `lexiconQueries`
cross-reference one or more of: **LSJ** (Liddell-Scott-Jones, *A
Greek-English Lexicon*), the **Middle Liddell** (*An Intermediate
Greek-English Lexicon*), **Autenrieth** (a Homeric-specific lexicon),
and **Slater** (a Pindar-specific lexicon) -- which of these a given
entry draws its short definition from depends on the word and the
lexica that happen to cover it.

Beta-code-to-Unicode conversion (`headword_unicode` in the output) uses
[`beta-code-py`](https://github.com/perseids-tools/beta-code-py)
(the `beta-code` package on PyPI).

## The 115 individual texts fetched from Perseus

Every text is Perseus's own digitization/edition of the Greek original,
one Perseus URN (`Perseus:text:...`) per row of `data/matches.yaml`'s
`matched_urns`; the editor credited below is Perseus's own, not this
repo's:

| author | works fetched | editor(s), per Perseus |
|---|---|---|
| Homer | 2 (Iliad, Odyssey) | -- |
| Aeschylus | 7 | Herbert Weir Smyth |
| Sophocles | 7 | Francis Storr |
| Euripides | 18 | David Kovacs; Gilbert Murray |
| Aristophanes | 11 | F. W. Hall and W. M. Geldart |
| Herodotus | 1 | -- |
| Plato | 6 (grouped multi-dialogue texts; 2 more displaced entirely by the corpus repo, below) | -- |
| Aristotle | 6 | J. Bywater; Kenyon; W. D. Ross |
| Hippocrates | 1 (omnibus) | W. H. S. Jones |
| Galen | 1 | A. J. Brock |
| Euclid | 1 | J. L. Heiberg |
| Epictetus | 1 | -- |
| Marcus Aurelius | 1 | Jan Hendrik Leopold |
| Plutarch | 50 (individual *Lives*) | Bernadotte Perrin |

(115 total -- Thucydides' *History* and Plato's *Republic* are no
longer fetched from Perseus at all, superseded by the corpus repo
below. The exact per-work URN list is `data/matches.yaml`'s
`matched_urns` fields; the raw fetched data itself is cached verbatim
in `data/raw/`.)

## The 6 works counted from vocabulary-corpus-prep instead

[`greek-learner-texts/vocabulary-corpus-prep`](https://github.com/greek-learner-texts/vocabulary-corpus-prep)
publishes gold per-work lemma tagging for a balanced Attic prose
corpus, reconciled across four independent tagging sources. See
README.md's "Ground truth from vocabulary-corpus-prep" section for why
these 6 `great_books.tsv` rows use it instead of (or, for two Plato
volumes, alongside a downweighted) Perseus:

| author | work | corpus work id |
|---|---|---|
| Thucydides | *History* (Books 1-5 only) | `tlg0003.tlg001` |
| Plato | Euthyphro | `tlg0059.tlg001` |
| Plato | Apology | `tlg0059.tlg002` |
| Plato | Crito | `tlg0059.tlg003` |
| Plato | Symposium | `tlg0059.tlg011` |
| Plato | Republic | `tlg0059.tlg030` |

Its own lemma tagging (`one/<work_id>/lemma.tsv`, read by
`corpus_vocab.py`) is itself built by reconciling:

- [Opera Graeca Adnotata (OGA)](https://github.com/OperaGraecaAdnotata/OGA)
- [Greek Dependency Treebanks (Gorman)](https://github.com/vgorman1/Greek-Dependency-Trees)
- [Scaife Viewer Tagging Pipeline](https://github.com/scaife-viewer/tagging-pipeline)
- [GLAUx (Keersmaekers)](https://github.com/alekkeersmaekers/glaux)

Its base texts are extracted from Perseus's canonical-greekLit TEI
XML, except Euthyphro, which uses the higher-quality text from
[plato-texts](https://github.com/jtauber/plato-texts) (jtauber) --
Perseus's own `grc1` Euthyphro edition has encoding/accentuation
issues the corpus repo's own validation caught. Base-text quality is
itself validated with [greek-check](https://github.com/jtauber/greek-check).

## The input list

`great_books.tsv` (title/author/group/year/sequence) is copied from a
table of the *Great Books of the Western World* set (Robert Maynard
Hutchins, ed.; Encyclopædia Britannica, Inc., 1952 and later printings)
supplied by this repo's author, restricted to authors who wrote in
Greek (see `README.md` for why the Latin-writing authors originally in
that table -- Lucretius, Virgil -- were removed rather than left to
show up as an unmatched skip).

## Software

- [`beta-code-py`](https://github.com/perseids-tools/beta-code-py) --
  beta-code/Unicode Greek conversion.
- [`requests`](https://requests.readthedocs.io/),
  [`PyYAML`](https://pyyaml.org/) -- HTTP + the `aliases.yaml`/
  `overrides.yaml`/`corpus_map.yaml`/`data/matches.yaml` file format.
- [`uv`](https://docs.astral.sh/uv/), [`ruff`](https://docs.astral.sh/ruff/)
  -- dependency management, lint/format.
