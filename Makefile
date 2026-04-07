# qino-lingo ingestion routine
#
# Single source of truth for pulling new Claude conversations into the corpus
# and keeping signals up to date for the MCP server.
#
# Usage:
#   make ingest          # Pull all new, run full pipeline + signals + digest
#   make ingest-recent   # Pull only last 20 sessions (fast iteration)
#   make verify          # Dry-run: report what would be ingested + corpus state
#   make digest          # Print the corpus digest without ingesting
#   make signals         # Recompute signals across the corpus (full)
#   make stats           # Raw db stats
#   make migrate         # Apply pending corpus.db schema migrations
#   make migrate-status  # Show applied + pending migrations
#   make migrate-dry     # Report what `make migrate` would do

# Use the project venv's python so subprocess `python3` calls also resolve
# to the venv. Both python and python3 in .venv/bin point to the same binary.
PY := .venv/bin/python

.PHONY: help ingest ingest-recent verify digest signals stats migrate migrate-status migrate-dry

help:
	@echo "qino-lingo ingestion targets:"
	@echo "  make ingest          Pull all new conversations, run full pipeline + digest"
	@echo "  make ingest-recent   Pull only the last 20 sessions"
	@echo "  make verify          Dry-run preview + show current corpus state"
	@echo "  make digest          Print the corpus digest without ingesting"
	@echo "  make signals         Recompute signals across the entire corpus"
	@echo "  make stats           Print raw corpus.db stats"
	@echo "  make migrate         Apply pending corpus.db schema migrations"
	@echo "  make migrate-status  Show applied + pending migrations"
	@echo "  make migrate-dry     Report what migrate would do without applying"

ingest:
	@PATH=.venv/bin:$$PATH $(PY) ingest_conversations.py

ingest-recent:
	@PATH=.venv/bin:$$PATH $(PY) ingest_conversations.py --recent 20

verify:
	@PATH=.venv/bin:$$PATH $(PY) ingest_conversations.py --dry-run

digest:
	@PATH=.venv/bin:$$PATH $(PY) -c "from ingest_conversations import print_digest; print_digest()"

signals:
	@PATH=.venv/bin:$$PATH $(PY) -m python.qino_lingo.signals compute

stats:
	@$(PY) -c "from python.qino_lingo.db import get_stats; import json; print(json.dumps(get_stats(), indent=2))"

migrate:
	@PATH=.venv/bin:$$PATH $(PY) -m python.qino_lingo.migrate

migrate-status:
	@PATH=.venv/bin:$$PATH $(PY) -m python.qino_lingo.migrate --status

migrate-dry:
	@PATH=.venv/bin:$$PATH $(PY) -m python.qino_lingo.migrate --dry-run
