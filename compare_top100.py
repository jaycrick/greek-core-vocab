#!/usr/bin/env python3
"""Compare the top 100 headwords of output/master_vocab.csv (this
pipeline's own combined vocabulary list, Perseus + corpus-repo) against
the top 100 lemmas of greek-learner-texts/vocabulary-corpus-prep's own
gold tagging -- but aggregated across ALL 49 of that repo's works, not
just the 6 corpus_map.yaml draws on. The question this answers: on the
corpus repo's own terms (its own lemmatization, its own much larger
Attic-prose-only sample), how does this pipeline's list compare?

Writes a single self-contained, sortable HTML report:
output/top100_compare.html. Not part of `make all` -- run explicitly
(`make report` / `uv run python3 compare_top100.py`) after `make all`
has produced output/master_vocab.csv, since it reads that file rather
than reproducing combine.py's own logic.

Ranking + percent, one list at a time:
  - master_vocab.csv: ranked by combined_weighted_frequency (already
    this pipeline's own output).
  - corpus repo: lemma-token counts summed across every
    one/<work_id>/lemma.tsv for every work_id in one/works.tsv (same
    skip-punctuation/skip-unmatched/NFC-normalize rule as
    corpus_vocab.py's count_work -- reused directly here, not
    reimplemented).
Percent for each row is against THAT list's own top-100 sum, not
either source's full vocabulary -- see the report's own methodology
note for why, and for the genre-composition explanation of most of
the disagreement (greek-core-vocab spans every genre across 121
works; vocabulary-corpus-prep is Attic prose only across 49).

The HTML/CSS/JS shell lives separately in
compare_top100_template.html (edit that for layout/copy changes) --
this script only computes the data and fills in its __DATA_JSON__
placeholder.

Usage
-----
    uv run python3 compare_top100.py
    CORPUS_REPO=/path/to/clone uv run python3 compare_top100.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from corpus_vocab import WORKS_TSV, count_work

MASTER_CSV = Path("output/master_vocab.csv")
TEMPLATE = Path("compare_top100_template.html")
OUT_HTML = Path("output/top100_compare.html")

TOP_N = 100


def load_master_top100() -> list[dict]:
    with MASTER_CSV.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return rows[:TOP_N]


def load_corpus_top100() -> tuple[list[tuple[str, int]], int, int]:
    """(top-N [(lemma, count), ...] by count desc, distinct lemma
    total, token total) aggregated across every work in
    one/works.tsv -- ALL 49, not only the 6 corpus_map.yaml uses."""
    with WORKS_TSV.open(encoding="utf-8") as f:
        work_ids = [row["work_id"] for row in csv.DictReader(f, delimiter="\t")]

    totals: dict[str, int] = {}
    for work_id in work_ids:
        rec = count_work(work_id)
        for lemma, count in rec["lemma_counts"].items():
            totals[lemma] = totals.get(lemma, 0) + count

    ranked = sorted(totals.items(), key=lambda kv: -kv[1])
    return ranked[:TOP_N], len(totals), sum(totals.values())


def build_rows(
    master_top100: list[dict], corpus_top100: list[tuple[str, int]]
) -> tuple[list[dict], float, int]:
    master_sum = sum(float(r["combined_weighted_frequency"]) for r in master_top100)
    master_info = {
        r["headword_unicode"]: {
            "rank": i + 1,
            "count": float(r["combined_weighted_frequency"]),
            "gloss": r["short_definition"],
        }
        for i, r in enumerate(master_top100)
    }
    corpus_sum = sum(c for _, c in corpus_top100)
    corpus_info = {
        lemma: {"rank": i + 1, "count": c} for i, (lemma, c) in enumerate(corpus_top100)
    }

    lemmas = list(master_info) + [lemma for lemma in corpus_info if lemma not in master_info]

    rows = []
    for lemma in lemmas:
        m = master_info.get(lemma)
        c = corpus_info.get(lemma)
        rows.append(
            {
                "lemma": lemma,
                "gloss": (m["gloss"] if m else "") or "",
                "master_rank": m["rank"] if m else None,
                "master_count": round(m["count"], 2) if m else None,
                "master_pct": round(m["count"] / master_sum * 100, 3) if m else None,
                "corpus_rank": c["rank"] if c else None,
                "corpus_count": c["count"] if c else None,
                "corpus_pct": round(c["count"] / corpus_sum * 100, 3) if c else None,
                "both": bool(m and c),
            }
        )

    ordered = sorted([r for r in rows if r["master_rank"]], key=lambda r: r["master_rank"])
    ordered += sorted([r for r in rows if not r["master_rank"]], key=lambda r: r["corpus_rank"])
    return ordered, master_sum, corpus_sum


def main() -> int:
    master_top100 = load_master_top100()
    corpus_top100, corpus_total_lemmas, corpus_total_tokens = load_corpus_top100()
    rows, master_sum, corpus_sum = build_rows(master_top100, corpus_top100)

    payload = {
        "rows": rows,
        "master_sum100": round(master_sum, 2),
        "corpus_sum100": corpus_sum,
        "corpus_total_lemmas": corpus_total_lemmas,
        "corpus_total_tokens": corpus_total_tokens,
    }

    template = TEMPLATE.read_text(encoding="utf-8")
    html = template.replace("__DATA_JSON__", json.dumps(payload, ensure_ascii=False))

    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(html, encoding="utf-8")

    both = sum(1 for r in rows if r["both"])
    print(f"{len(rows)} union rows ({both}/100 lemmas on both top-100 lists)")
    print(
        f"corpus repo: {corpus_total_lemmas:,} distinct lemmas, "
        f"{corpus_total_tokens:,} tokens across all 49 works"
    )
    print(f"-> {OUT_HTML}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
