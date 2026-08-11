#!/usr/bin/env python3
"""Parse every successfully-fetched work in data/fetch_manifest.json,
collapse identical headwords together (within and across works), sum
their weightedFrequency, and write the single reusable deliverable:
output/master_vocab.csv (+ a .json mirror).

Collapsing key: the raw beta-code headword string, exactly as Perseus's
own tool reports it (`lemma/headword` in the XML, the `l=` query param
of a table row's word link -- both are the same value, since the table
is just Perseus's own HTML rendering of the identical underlying data).
Perseus doesn't fully disambiguate homographs at this field -- two
different LSJ senses can share one headword, split apart only in the
`lexiconQueries`/"Lexicon Entries" refs -- so grouping on the headword
string alone is both the direct reading of "collapse identical forms
into one reading" and the natural join key across works.

Combine function: SUM each headword's weightedFrequency across every
work it appears in (a user decision -- rewards a word for being both
locally frequent and used widely, the standard way to merge frequency
lists; see README.md).

Usage
-----
    uv run python3 combine.py
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import beta_code

from fetch_vocab import urn_id

MANIFEST = Path("data/fetch_manifest.json")
OUT_CSV = Path("output/master_vocab.csv")
OUT_JSON = Path("output/master_vocab.json")


@dataclass
class Entry:
    headword: str  # beta-code
    weighted_frequency: float
    short_definition: str


@dataclass
class Group:
    weighted_frequency: float = 0.0
    urns: set[str] = field(default_factory=set)
    short_definition: str = ""


def parse_xml(text: str) -> list[Entry]:
    import xml.etree.ElementTree as ET

    root = ET.fromstring(text)
    entries = []
    for freq in root.findall("frequency"):
        lemma = freq.find("lemma")
        headword = (lemma.findtext("headword") or "").strip() if lemma is not None else ""
        if not headword:
            continue
        short_def = (
            (lemma.findtext("shortDefinition") or "").strip() if lemma is not None else ""
        )
        wf_text = (freq.findtext("weightedFrequency") or "0").strip()
        entries.append(Entry(headword, float(wf_text), short_def))
    return entries


class _TableParser(HTMLParser):
    """Walks a `<table id="vocab_list">` (see fetch_vocab.py's module
    docstring for why this format sometimes has to stand in for XML),
    collecting the same three fields XML gives directly: the word's
    beta-code (from its link's `l=` query param -- the same value the
    XML `headword` field holds), the "This Word" weighted-frequency
    column, and the definition column. Column order, 0-indexed:
    0 count (blank), 1 word, 2 max freq, 3 min freq, 4 THIS WORD
    weighted freq, 5 total weighted freq, 6 key term score,
    7 definition, 8 lexicon entries."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_vocab_table = False
        self.table_depth = 0
        self.in_row = False
        self.in_cell = False
        self.row_cells: list[str] = []
        self.cell_text: list[str] = []
        self.row_headword: str | None = None
        self.entries: list[Entry] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrd = dict(attrs)
        if tag == "table" and attrd.get("id") == "vocab_list":
            self.in_vocab_table = True
            self.table_depth = 0
            return
        if not self.in_vocab_table:
            return
        if tag == "table":
            self.table_depth += 1
        elif tag == "tr" and self.table_depth == 0:
            self.in_row = True
            self.row_cells = []
            self.row_headword = None
        elif tag == "td" and self.in_row:
            self.in_cell = True
            self.cell_text = []
        elif tag == "a" and self.in_row and self.row_headword is None:
            href = attrd.get("href") or ""
            if href.startswith("morph?"):
                query = parse_qs(urlparse(href).query)
                if "l" in query:
                    self.row_headword = query["l"][0]

    def handle_endtag(self, tag: str) -> None:
        if not self.in_vocab_table:
            return
        if tag == "table":
            if self.table_depth == 0:
                self.in_vocab_table = False
            else:
                self.table_depth -= 1
        elif tag == "td" and self.in_cell:
            self.in_cell = False
            self.row_cells.append("".join(self.cell_text).strip())
        elif tag == "tr" and self.in_row:
            self.in_row = False
            if self.row_headword and len(self.row_cells) >= 8:
                wf_raw = self.row_cells[4].replace(",", "")
                try:
                    wf = float(wf_raw)
                except ValueError:
                    wf = 0.0
                self.entries.append(Entry(self.row_headword, wf, self.row_cells[7]))

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.cell_text.append(data)


def parse_table(text: str) -> list[Entry]:
    parser = _TableParser()
    parser.feed(text)
    return parser.entries


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
        try:
            work_entries = parse_xml(text) if entry["method"] == "xml" else parse_table(text)
        except Exception as e:  # noqa: BLE001 -- one bad file shouldn't abort the run
            parse_failures.append(f"{entry['urn']}: {e}")
            continue
        if not work_entries:
            parse_failures.append(f"{entry['urn']}: parsed 0 entries")
            continue
        parsed_ok += 1
        for e in work_entries:
            g = groups.setdefault(e.headword, Group())
            g.weighted_frequency += e.weighted_frequency
            g.urns.add(entry["urn"])
            if not g.short_definition and e.short_definition:
                g.short_definition = e.short_definition

    rows = []
    conversion_failures = 0
    for headword, g in groups.items():
        try:
            unicode_form = beta_code.beta_code_to_greek(headword)
        except Exception:  # noqa: BLE001 -- keep the beta-code form, don't drop the word
            unicode_form = headword
            conversion_failures += 1
        rows.append(
            {
                "headword_unicode": unicode_form,
                "headword_betacode": headword,
                "combined_weighted_frequency": round(g.weighted_frequency, 4),
                "works_count": len(g.urns),
                "short_definition": g.short_definition,
                "source_urns": ";".join(sorted(urn_id(u) for u in g.urns)),
            }
        )

    rows.sort(key=lambda r: (-r["combined_weighted_frequency"], r["headword_unicode"]))

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        writer.writeheader()
        writer.writerows(rows)
    OUT_JSON.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"{parsed_ok}/{len([e for e in manifest if e['success']])} fetched works parsed")
    if parse_failures:
        print(f"{len(parse_failures)} parse failure(s):")
        for f_ in parse_failures:
            print(f"  {f_}")
    if conversion_failures:
        print(f"{conversion_failures} headword(s) failed beta-code conversion (kept as-is)")
    print(f"{len(rows)} distinct headwords -> {OUT_CSV}, {OUT_JSON}")
    print("\ntop 20 by combined weighted frequency:")
    for r in rows[:20]:
        print(
            f"  {r['headword_unicode']:12s} {r['combined_weighted_frequency']:>10.2f}  "
            f"({r['works_count']} works)  {r['short_definition']}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
