#!/usr/bin/env python3
"""Compare vocab.perseus.org's own Iliad/Odyssey word lists against
jaycrick/ag-cloze-cards's hand-disambiguated WordHoard/Chicago Homer
tagging of the same two texts -- a standing cross-check on how close an
automatic parse comes to a hand-checked one, now that vocab.perseus.org
(not WordHoard) is master_vocab.csv's actual source for Homer (see
README.md).

Writes a single self-contained, sortable HTML report:
output/homer_compare.html. Not part of `make all` -- run explicitly
(`make report` / `uv run python3 compare_homer.py`) after `make all`
has produced data/fetch_manifest.json + data/raw/ (re-parsed here,
reusing combine.py's own parse_wordlist) and `make homer` has produced
data/homer_counts.json (WordHoard's own counts, via homer_vocab.py).

Ranking, one list at a time, top 100 lemmas each:
  - Perseus: data/raw/<Iliad|Odyssey>.html, parsed directly and summed
    per lemma across just those two files -- NOT master_vocab.csv's
    `count` column, which is summed across all 96 fetched works and so
    isn't an Iliad+Odyssey-only figure (this is a same-text comparison,
    it needs the same-text count).
  - WordHoard: data/homer_counts.json's lemma_counts for homer:IL/
    homer:OD, summed per lemma across both epics to match.

The HTML/CSS/JS shell lives separately in compare_homer_template.html
(edit that for layout/copy changes) -- this script only computes the
data and fills in its __DATA_JSON__ placeholder.

Usage
-----
    uv run python3 compare_homer.py
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

from combine import parse_wordlist

MANIFEST = Path("data/fetch_manifest.json")
HOMER_COUNTS = Path("data/homer_counts.json")
TEMPLATE = Path("compare_homer_template.html")
OUT_HTML = Path("output/homer_compare.html")

TOP_N = 100
HOMER_URNS = {
    "urn:cts:greekLit:tlg0012.tlg001.perseus-grc2",  # Iliad
    "urn:cts:greekLit:tlg0012.tlg002.perseus-grc2",  # Odyssey
}


def load_perseus_homer_top100() -> tuple[list[tuple[str, int, str]], int]:
    """(top-N [(headword, count, gloss), ...] summed across just the
    Iliad + Odyssey's own cached word lists, count total)."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    totals: dict[str, tuple[int, str]] = {}  # headword -> (count, gloss)
    for entry in manifest:
        if entry["urn"] not in HOMER_URNS or not entry["success"]:
            continue
        text = Path(entry["cache_file"]).read_text(encoding="utf-8")
        for e in parse_wordlist(text):
            headword = unicodedata.normalize("NFC", e.headword)
            count, gloss = totals.get(headword, (0, ""))
            totals[headword] = (count + e.count, gloss or e.short_definition)
    ranked = sorted(totals.items(), key=lambda kv: -kv[1][0])
    total = sum(c for c, _ in totals.values())
    top = [(lemma, c, gloss) for lemma, (c, gloss) in ranked[:TOP_N]]
    return top, total


def load_wordhoard_top100() -> tuple[list[tuple[str, int]], int, int]:
    """(top-N [(lemma, count), ...] by count desc, distinct lemma
    total, token total) summed across both homer:IL and homer:OD."""
    records = json.loads(HOMER_COUNTS.read_text(encoding="utf-8"))
    totals: dict[str, int] = {}
    for rec in records:
        for lemma, count in rec["lemma_counts"].items():
            key = unicodedata.normalize("NFC", lemma)
            totals[key] = totals.get(key, 0) + count
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])
    return ranked[:TOP_N], len(totals), sum(totals.values())


def build_rows(
    perseus_top100: list[tuple[str, int, str]], wordhoard_top100: list[tuple[str, int]]
) -> tuple[list[dict], int, int]:
    perseus_sum = sum(c for _, c, _ in perseus_top100)
    perseus_info = {
        lemma: {"rank": i + 1, "count": c, "gloss": g}
        for i, (lemma, c, g) in enumerate(perseus_top100)
    }
    wordhoard_sum = sum(c for _, c in wordhoard_top100)
    wordhoard_info = {
        lemma: {"rank": i + 1, "count": c} for i, (lemma, c) in enumerate(wordhoard_top100)
    }

    lemmas = list(perseus_info) + [
        lemma for lemma in wordhoard_info if lemma not in perseus_info
    ]

    rows = []
    for lemma in lemmas:
        p = perseus_info.get(lemma)
        w = wordhoard_info.get(lemma)
        rows.append(
            {
                "lemma": lemma,
                "gloss": (p["gloss"] if p else "") or "",
                "master_rank": p["rank"] if p else None,
                "master_count": p["count"] if p else None,
                "master_pct": round(p["count"] / perseus_sum * 100, 3) if p else None,
                "corpus_rank": w["rank"] if w else None,
                "corpus_count": w["count"] if w else None,
                "corpus_pct": round(w["count"] / wordhoard_sum * 100, 3) if w else None,
                "both": bool(p and w),
            }
        )

    ordered = sorted([r for r in rows if r["master_rank"]], key=lambda r: r["master_rank"])
    ordered += sorted([r for r in rows if not r["master_rank"]], key=lambda r: r["corpus_rank"])
    return ordered, perseus_sum, wordhoard_sum


def main() -> int:
    perseus_top100, perseus_total = load_perseus_homer_top100()
    wordhoard_top100, wordhoard_total_lemmas, wordhoard_total_tokens = load_wordhoard_top100()
    rows, perseus_sum, wordhoard_sum = build_rows(perseus_top100, wordhoard_top100)

    payload = {
        "rows": rows,
        "master_sum100": perseus_sum,
        "corpus_sum100": wordhoard_sum,
        "corpus_total_lemmas": wordhoard_total_lemmas,
        "corpus_total_tokens": wordhoard_total_tokens,
        "master_total_tokens": perseus_total,
    }

    template = TEMPLATE.read_text(encoding="utf-8")
    html = template.replace("__DATA_JSON__", json.dumps(payload, ensure_ascii=False))

    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(html, encoding="utf-8")

    both = sum(1 for r in rows if r["both"])
    print(f"{len(rows)} union rows ({both}/100 lemmas on both top-100 lists)")
    print(f"vocab.perseus.org Iliad+Odyssey: {perseus_total:,} tokens")
    print(
        f"WordHoard: {wordhoard_total_lemmas:,} distinct lemmas, "
        f"{wordhoard_total_tokens:,} tokens across Iliad+Odyssey"
    )
    print(f"-> {OUT_HTML}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
