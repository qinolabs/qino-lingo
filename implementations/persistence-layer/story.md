# Persistence Layer

The persistence layer is `corpus.db` (SQLite) plus the markdown files in
`data/corpus/` plus the various scripts that move data between them.

## What lives here

- `corpus.db` — single-file SQLite database, ~1.2 MB
- `data/corpus/` — markdown conversation files, the canonical source
- `data/corpus/_noise/` — files filter_noise.py classified as noise
- `python/qino_lingo/db.py` — schema, connection management, CRUD
- `python/qino_lingo/signals.py` — pre-computed analysis writes
- `ingest_conversations.py` + `filter_noise.py` + `extract_metadata.py` — the
  ingestion pipeline that populates the db
- `backup-corpus.sh` — manual db copy with timestamp
- `mcp-server/server.py` — primary read consumer of the db (the new one)
- `apps/lingo-label/` — secondary read consumer (the original one)

## Why this is its own concern now

The persistence layer was designed when qino-lingo had **one consumer**: the
labeling app. Schema decisions, the backup script's awareness, the
ingestion-as-rebuild pattern — all of it is shaped by labeling-only
assumptions.

The MCP server (`mcp-server/server.py`) is now an **active second consumer**,
used during metalogue sourcing, deck composition, and conversation discovery
by other parts of the qino ecosystem. It depends on tables (`conversation_signals`,
`annotations`) that didn't exist when the schema was first laid down, and on
join semantics that the original schema didn't think hard about.

The dual-consumer reality is exposing structural debt that was invisible
when there was only one reader. The persistence layer now needs to be
considered as a layer in its own right, not as scaffolding under the
labeling app.

## Iteration history

- `content/01-holistic-refactor.md` — current
