#!/usr/bin/env python3
"""Count lemma frequencies for Homer's Iliad and Odyssey from
~/git_repos/ag-cloze-cards's own WordHoard/Chicago Homer parser
(`ag_cloze_cards.corpus.WordHoardHomerAdapter`) -- Northwestern's
hand-disambiguated tagging of early Greek epic, the same tokenization
that repo's own Homer Anki deck is built from.

This no longer feeds combine.py -- vocab.perseus.org's own Iliad/
Odyssey word lists are the master_vocab.csv source for Homer now (see
README.md's coverage table: the old hopper's automatic parse missed
proper nouns and dialect forms WordHoard catches, but vocab.perseus.org
carries them directly, e.g. Ἀχιλλεύς: 367, Ἕκτωρ: 454). This script's
output instead feeds compare_homer.py, a standing cross-check: how
close does vocab.perseus.org's own count come to a hand-disambiguated
one, for the two texts most likely to trip up an automatic parser.

Why shell out rather than import `ag_cloze_cards` directly: that
package depends on `readerforge` (a private git dependency) and lives
in its own uv-managed venv at AG_CLOZE_CARDS_REPO. Running
`uv run python3 -c ...` inside that project's directory reuses its
already-resolved environment (and, critically, ITS parsing code
verbatim -- elision, movable-nu, WordHoard's `lemma|word_class`
encoding, trailing-punctuation handling, all already solved there) --
see ag_cloze_cards/src/ag_cloze_cards/corpus.py's own docstring --
without adding those dependencies to this pipeline's pyproject.toml or
reimplementing WordHoard's XML format ourselves, which would risk
silently drifting from that repo's own parsing decisions.

Output: data/homer_counts.json, the same record shape as
data/corpus_counts.json (work_id, author, title, token_count,
distinct_lemmas, lemma_counts) so combine.py folds both sources
identically. `notes_histogram` is always `{}` here -- WordHoard is one
hand-disambiguated tagging, not corpus_vocab.py's multi-tagger
(OGA/GLAUX/Gorman/Scaife) reconciliation, so there's no per-lemma
agreement/disagreement to report.

Usage
-----
    uv run python3 homer_vocab.py
    AG_CLOZE_CARDS_REPO=/path/to/clone uv run python3 homer_vocab.py
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

OUT = Path("data/homer_counts.json")

AG_CLOZE_CARDS_REPO = Path(
    os.environ.get("AG_CLOZE_CARDS_REPO", "~/git_repos/ag-cloze-cards")
).expanduser()

# work_id -> the WordHoard work abbreviation
# ag_cloze_cards.corpus.WordHoardHomerAdapter expects (see its
# data/homer_books.tsv).
_WORDHOARD_ABBREV = {"homer:IL": "IL", "homer:OD": "OD"}

_COUNT_SCRIPT = """
import collections, json, sys, unicodedata
from ag_cloze_cards.corpus import WordHoardHomerAdapter

abbrev = sys.argv[1]
counts = collections.Counter()
for tok in WordHoardHomerAdapter(works=(abbrev,)).tokens():
    counts[unicodedata.normalize("NFC", tok.lemma)] += 1
print(json.dumps(dict(counts), ensure_ascii=False))
"""


def count_work(work_id: str) -> dict:
    abbrev = _WORDHOARD_ABBREV[work_id]
    result = subprocess.run(
        ["uv", "run", "python3", "-c", _COUNT_SCRIPT, abbrev],
        cwd=AG_CLOZE_CARDS_REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ag-cloze-cards WordHoard parse failed for {abbrev!r}:\n{result.stderr}"
        )
    lemma_counts: dict[str, int] = json.loads(result.stdout)
    return {
        "work_id": work_id,
        "token_count": sum(lemma_counts.values()),
        "distinct_lemmas": len(lemma_counts),
        "notes_histogram": {},
        "lemma_counts": lemma_counts,
    }


def main() -> int:
    if not (AG_CLOZE_CARDS_REPO / "pyproject.toml").is_file():
        raise SystemExit(
            f"ag-cloze-cards repo not found at {AG_CLOZE_CARDS_REPO} (set "
            "AG_CLOZE_CARDS_REPO or clone https://github.com/jaycrick/ag-cloze-cards)"
        )

    titles = {"homer:IL": ("Homer", "The Iliad"), "homer:OD": ("Homer", "The Odyssey")}

    results = []
    for work_id in sorted(_WORDHOARD_ABBREV):
        author, title = titles[work_id]
        rec = count_work(work_id)
        rec["author"] = author
        rec["title"] = title
        results.append(rec)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"{len(results)} Homer work(s) counted -> {OUT}")
    for rec in results:
        print(
            f"  {rec['work_id']:10s} {rec['author']:6s} {rec['title']:12s} "
            f"{rec['token_count']:>7,} tokens  {rec['distinct_lemmas']:>5,} distinct"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
