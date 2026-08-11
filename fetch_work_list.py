#!/usr/bin/env python3
"""Scrape Perseus's Greek Vocabulary Tool's own work-selector list into
data/perseus_works.json: one row per `<option>` in the page's
`<select name="works" multiple>` -- the full catalog match_books.py
matches great_books.tsv against.

The vocablist page (https://www.perseus.tufts.edu/hopper/vocablist?lang=greek)
is plain server-rendered HTML, no JS/auth needed. Each option looks like:

    <option value="Perseus:text:1999.01.0133" >Homer, <span class="title">Iliad</span></option>

-- author (may be empty, e.g. the anonymous "Homeric Hymns"), a Perseus
CTS-ish URN, and a title, sometimes followed by "(ed. ...)" after the
closing </span> which we keep as `edition` for reference but don't
match against.

Usage
-----
    uv run python3 fetch_work_list.py
"""

from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path

import requests

URL = "https://www.perseus.tufts.edu/hopper/vocablist?lang=greek"
OUT = Path("data/perseus_works.json")


class WorksParser(HTMLParser):
    """Walks the page once, collecting every `<option>` inside
    `<select name="works">` as {urn, author, title, edition}."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_works_select = False
        self.in_option = False
        self.in_title_span = False
        self.current_urn: str | None = None
        self.author_parts: list[str] = []
        self.title_parts: list[str] = []
        self.edition_parts: list[str] = []
        self.works: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrd = dict(attrs)
        if tag == "select" and attrd.get("name") == "works":
            self.in_works_select = True
        elif tag == "option" and self.in_works_select:
            self.in_option = True
            self.current_urn = attrd.get("value")
            self.author_parts = []
            self.title_parts = []
            self.edition_parts = []
        elif tag == "span" and self.in_option and attrd.get("class") == "title":
            self.in_title_span = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "select" and self.in_works_select:
            self.in_works_select = False
        elif tag == "option" and self.in_option:
            self.in_option = False
            if self.current_urn:
                self.works.append(
                    {
                        "urn": self.current_urn,
                        "author": "".join(self.author_parts).strip().rstrip(",").strip(),
                        "title": "".join(self.title_parts).strip(),
                        "edition": "".join(self.edition_parts).strip(),
                    }
                )
        elif tag == "span" and self.in_title_span:
            self.in_title_span = False

    def handle_data(self, data: str) -> None:
        if not self.in_option:
            return
        if self.in_title_span:
            self.title_parts.append(data)
        elif self.title_parts:
            # After the title span closes (e.g. " (ed. Whoever)").
            self.edition_parts.append(data)
        else:
            # Before the title span opens -- the author.
            self.author_parts.append(data)


def fetch_works() -> list[dict[str, str]]:
    resp = requests.get(URL, headers={"User-Agent": "greek-core-vocab/0.1"}, timeout=30)
    resp.raise_for_status()
    parser = WorksParser()
    parser.feed(resp.text)
    if not parser.works:
        raise SystemExit(
            'found 0 works in the <select name="works"> list -- did Perseus change '
            "the vocablist page's markup?"
        )
    return parser.works


def main() -> int:
    works = fetch_works()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(works, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(works)} works -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
