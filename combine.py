#!/usr/bin/env python3
"""Parse every successfully-fetched work in data/fetch_manifest.json,
collapse identical headwords together (across every work), sum their
exact token counts, and write the single reusable deliverable:
output/master_vocab.csv (+ a .json mirror).

Collapsing key: NFC-normalized Unicode headword -- vocab.perseus.org's
own lemma is already Unicode (no beta-code conversion needed, unlike
the old hopper). vocab.perseus.org doesn't fully disambiguate
homographs either (the same risk the old source had -- two distinct LSJ
senses can in principle share one headword string), so grouping on the
headword string alone is still the direct reading of "collapse
identical forms into one reading," and the natural join key across
works.

Combine function: SUM each headword's exact `count` across every work
it appears in -- a user decision, rewards a word for being both locally
frequent and used across many works, the standard way to merge
frequency lists. Unlike the old hopper's `weightedFrequency` (a
probabilistic estimate), vocab.perseus.org's `count` is an exact token
count straight from the text, so this sum is exact too, not a
scale-compatible approximation.

`corpus_freq_per_10k`/`core_freq_per_10k` are NOT summed -- they're
per-lemma constants (vocab.perseus.org's own whole-corpus and Core
Reading List frequency, computed by Perseus itself over its entire
21.4M/1.36M-token base, the same number regardless of which work's page
reports it). Every work reporting a given headword is expected to agree
on these; a disagreement gets flagged rather than silently averaged or
overwritten.

Usage
-----
    uv run python3 combine.py
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

MANIFEST = Path("data/fetch_manifest.json")
OUT_CSV = Path("output/master_vocab.csv")
OUT_JSON = Path("output/master_vocab.json")

_ROW_RE = re.compile(
    r'<th class="lemma_text"><a href="/lemma/(\d+)/[^"]*">(.*?)</a>\s*'
    r'<td class="shortdef">(.*?)\s*'
    r'<td class="count">([\d,]+)\s*'
    r'<td class="frequency">\(([^)]*)\)\s*'
    r'<td class="frequency">\(([^)]*)\)\s*'
    r'<td class="frequency">\(([^)]*)\)',
    re.S,
)


@dataclass
class Entry:
    lemma_id: str
    headword: str  # Unicode, as vocab.perseus.org rendered it
    count: int
    short_definition: str
    corpus_freq_per_10k: float
    core_freq_per_10k: float


@dataclass
class Group:
    lemma_id: str = ""
    count: int = 0
    urns: set[str] = field(default_factory=set)
    short_definition: str = ""
    corpus_freq_per_10k: float | None = None
    core_freq_per_10k: float | None = None
    freq_mismatch: bool = False


def parse_wordlist(text: str) -> list[Entry]:
    entries = []
    for lemma_id, word, shortdef, count, _this_work, corpus_freq, core_freq in _ROW_RE.findall(
        text
    ):
        entries.append(
            Entry(
                lemma_id=lemma_id,
                headword=word.strip(),
                count=int(count.replace(",", "")),
                short_definition=shortdef.strip(),
                corpus_freq_per_10k=float(corpus_freq),
                core_freq_per_10k=float(core_freq),
            )
        )
    return entries


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    groups: dict[str, Group] = {}
    parsed_ok = 0
    parse_failures: list[str] = []
    for entry in manifest:
        if not entry["success"]:
            continue
        path = Path(entry["cache_file"])
        text = path.read_text(encoding="utf-8")
        work_entries = parse_wordlist(text)
        if not work_entries:
            parse_failures.append(f"{entry['urn']}: parsed 0 entries")
            continue
        parsed_ok += 1
        for e in work_entries:
            headword = unicodedata.normalize("NFC", e.headword)
            g = groups.setdefault(headword, Group())
            g.count += e.count
            g.urns.add(entry["urn"])
            if not g.lemma_id:
                g.lemma_id = e.lemma_id
            if not g.short_definition and e.short_definition:
                g.short_definition = e.short_definition
            # These two figures are vocab.perseus.org's own whole-corpus/
            # core-reading-list constants for this lemma -- every work
            # reporting it should agree; keep the first seen, flag (not
            # silently overwrite) if a later one disagrees.
            if g.corpus_freq_per_10k is None:
                g.corpus_freq_per_10k = e.corpus_freq_per_10k
                g.core_freq_per_10k = e.core_freq_per_10k
            elif (
                g.corpus_freq_per_10k != e.corpus_freq_per_10k
                or g.core_freq_per_10k != e.core_freq_per_10k
            ):
                g.freq_mismatch = True

    rows = []
    for headword, g in groups.items():
        rows.append(
            {
                "headword_unicode": headword,
                "lemma_id": g.lemma_id,
                "count": g.count,
                "works_count": len(g.urns),
                "short_definition": g.short_definition,
                "corpus_freq_per_10k": g.corpus_freq_per_10k,
                "core_freq_per_10k": g.core_freq_per_10k,
                "source_urns": ";".join(sorted(g.urns)),
            }
        )

    rows.sort(key=lambda r: (-r["count"], r["headword_unicode"]))

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        writer.writeheader()
        writer.writerows(rows)
    OUT_JSON.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    mismatches = [h for h, g in groups.items() if g.freq_mismatch]
    print(f"{parsed_ok}/{len([e for e in manifest if e['success']])} fetched works parsed")
    if parse_failures:
        print(f"{len(parse_failures)} parse failure(s):")
        for f_ in parse_failures:
            print(f"  {f_}")
    if mismatches:
        print(
            f"{len(mismatches)} headword(s) reported inconsistent corpus/core frequency "
            f"across works (kept the first seen): {', '.join(mismatches[:10])}"
            + (", ..." if len(mismatches) > 10 else "")
        )
    print(f"{len(rows)} distinct headwords -> {OUT_CSV}, {OUT_JSON}")
    print("\ntop 20 by combined count:")
    for r in rows[:20]:
        print(
            f"  {r['headword_unicode']:12s} {r['count']:>8,}  "
            f"({r['works_count']} works)  {r['short_definition']}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
