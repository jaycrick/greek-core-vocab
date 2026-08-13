#!/usr/bin/env python3
"""Count lemma frequencies for every great_books.tsv row that
data/matches.yaml resolved to a corpus_work_id (see corpus_map.yaml) --
the local counterpart of fetch_vocab.py, reading
greek-learner-texts/vocabulary-corpus-prep's gold per-work lemma
tagging instead of hitting Perseus over the network.

Source layout (cloned locally, see CORPUS_REPO below):
    one/works.tsv              -- work_id, author, title, genre
    one/<work_id>/lemma.tsv    -- token_ref, lemma, postag, oga_lemma,
                                   glaux_lemma, oga_postag, glaux_postag,
                                   notes

Counting rule, verified against Crito (tlg0059.tlg003): of 4,925
lemma.tsv rows, 685 are punctuation (`postag` starts with "u"), 21
have a blank `lemma` (`notes: unmatched` -- no tagging source could
agree), leaving 4,219 counted tokens over 668 distinct lemmas. Lemma
strings are NFC-normalized before counting (the corpus repo and
Perseus's beta-code conversion don't always agree on precomposed vs.
combining-mark accent order).

Output: data/corpus_counts.json, a list of per-work records:
    {work_id, author, title, token_count, distinct_lemmas,
     notes_histogram: {DISAGREE, glaux_only, oga_only, unmatched, ...},
     lemma_counts: {lemma: count}}

`notes_histogram` is this step's equivalent of fetch_manifest.json's
`method`/`filt` -- the transparency trail for how much of a work's
tagging required tie-breaking or was left unmatched.

Usage
-----
    uv run python3 corpus_vocab.py
    CORPUS_REPO=/path/to/clone uv run python3 corpus_vocab.py
"""

from __future__ import annotations

import csv
import json
import os
import unicodedata
from collections import Counter
from pathlib import Path

import yaml

MATCHES = Path("data/matches.yaml")
OUT = Path("data/corpus_counts.json")

CORPUS_REPO = Path(
    os.environ.get("CORPUS_REPO", "~/git_repos/vocabulary-corpus-prep")
).expanduser()
WORKS_TSV = CORPUS_REPO / "one" / "works.tsv"


def load_work_ids() -> list[str]:
    doc = yaml.safe_load(MATCHES.read_text(encoding="utf-8"))
    return sorted({r["corpus_work_id"] for r in doc["matches"] if r.get("corpus_work_id")})


def load_works_meta() -> dict[str, dict[str, str]]:
    with WORKS_TSV.open(encoding="utf-8") as f:
        return {row["work_id"]: row for row in csv.DictReader(f, delimiter="\t")}


def count_work(work_id: str) -> dict:
    lemma_path = CORPUS_REPO / "one" / work_id / "lemma.tsv"
    with lemma_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))

    counts: Counter[str] = Counter()
    notes_hist: Counter[str] = Counter()
    for row in rows:
        note = row.get("notes", "").strip()
        if note:
            notes_hist[note] += 1
        lemma = row["lemma"].strip()
        postag = row["postag"].strip()
        if not lemma or postag.startswith("u"):
            continue
        counts[unicodedata.normalize("NFC", lemma)] += 1

    return {
        "work_id": work_id,
        "token_count": sum(counts.values()),
        "distinct_lemmas": len(counts),
        "notes_histogram": dict(notes_hist),
        "lemma_counts": dict(counts),
    }


def main() -> int:
    if not WORKS_TSV.is_file():
        raise SystemExit(
            f"corpus repo not found at {CORPUS_REPO} (set CORPUS_REPO or clone "
            "https://github.com/greek-learner-texts/vocabulary-corpus-prep)"
        )

    work_ids = load_work_ids()
    works_meta = load_works_meta()

    results = []
    for work_id in work_ids:
        meta = works_meta.get(work_id, {})
        rec = count_work(work_id)
        rec["author"] = meta.get("author", "")
        rec["title"] = meta.get("title", "")
        results.append(rec)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"{len(results)} corpus work(s) counted -> {OUT}")
    for rec in results:
        print(
            f"  {rec['work_id']:16s} {rec['author']:12s} {rec['title']:30s} "
            f"{rec['token_count']:>7,} tokens  {rec['distinct_lemmas']:>5,} distinct"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
