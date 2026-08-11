.PHONY: all work-list match fetch combine clean distclean

# End-to-end: scrape Perseus's catalog -> match great_books.tsv against
# it -> fetch each matched work's vocabulary -> combine into the one
# reusable output file. Safe to re-run: fetch skips anything already
# cached in data/raw/ (see fetch_vocab.py), so a re-run after editing
# aliases.yaml/overrides.yaml only re-does the (cheap, local) match and
# combine steps.
all: work-list match fetch combine

# Re-scrapes Perseus's own work list (data/perseus_works.json) --
# re-run this if Perseus's catalog might have changed since the last run.
work-list:
	uv run python3 fetch_work_list.py

# Re-resolve great_books.tsv against data/perseus_works.json (+
# aliases.yaml/overrides.yaml) -> data/matches.yaml. Cheap, local, no
# network -- re-run any time those inputs change.
match:
	uv run python3 match_books.py

# Fetch every unique matched URN's vocabulary list, caching to
# data/raw/ and recording data/fetch_manifest.json. Idempotent: only
# fetches URNs not already recorded as successful. `make fetch
# REDO=1` re-fetches everything.
fetch:
	uv run python3 fetch_vocab.py $(if $(REDO),--redo,)

# Parse data/raw/* -> output/master_vocab.csv + .json, the single
# reusable deliverable.
combine:
	uv run python3 combine.py

# Remove generated data/output, but keep great_books.tsv/aliases.yaml/
# overrides.yaml (the hand-authored inputs).
clean:
	rm -rf data/perseus_works.json data/matches.yaml output

# Also drop the fetched raw cache -- a full re-run from `make all`
# after this re-downloads everything from Perseus.
distclean: clean
	rm -rf data/raw data/fetch_manifest.json
