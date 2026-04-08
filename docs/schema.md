# Database Schema

`corpus.db` is a single SQLite database serving two consumers with very
different concerns:

- **The training side** — `lingo-label` (labeling UI), `characterize.py`,
  `calibrate.py`, `sampler.py`, the noise-filter training scripts.
  Historically the reason the db exists.
- **The MCP side** — `mcp-server/` and its `candidates`, `read_thinking`,
  `search`, `metadata`, `annotate` tools. Added later; now load-bearing
  for downstream work (metalogue sourcing, deck composition, conversation
  discovery).

The schema is designed to make the dual-purpose nature explicit. The same
`files` table serves both sides; MCP-only tables (`conversation_signals`,
`annotations`) and training-only tables (`labels`, `markers`, `examples`,
`pending_labels`, `noise_predictions`, `model_feedback`, `calibration_*`)
are grouped by consumer in the [table reference](#tables) below.

See `implementations/persistence-layer/content/01-holistic-refactor.md` for
the full rationale behind the identity, status, backup, and diagnostics
decisions documented here.

## Canonical authorities

| What | Lives in |
|---|---|
| Schema DDL (canonical) | `python/qino_lingo/migrations/*.sql` |
| Schema migration runner | `python/qino_lingo/migrate.py` (`make migrate`) |
| Python read/write helpers | `python/qino_lingo/db.py` |
| Signal computation + storage | `python/qino_lingo/signals.py` |
| Drizzle schema (mirror of db) | `apps/lingo-label/src/server/schema.ts` |
| Backup runner | `python/qino_lingo/backup.py` (`make backup`) |
| Health check | `python/qino_lingo/doctor.py` (`make doctor`) |

**Rules:**

- **All schema changes go through a numbered migration.** No inline
  `CREATE TABLE IF NOT EXISTS` calls in consumer code. Write a new
  `migrations/NN-descriptive-name.sql` file, run `make migrate`, then
  update consumers to match.
- **Every connection must enable `PRAGMA foreign_keys = ON`.** SQLite
  silently ignores FK declarations otherwise. Both `db.py::get_connection`
  (Python) and `apps/lingo-label/src/server/db.ts::getDb` (TypeScript)
  enable the pragma. Migration scripts may toggle it off during
  rebuild-and-rename swaps; application code must always have it on.
- **The Drizzle schema is a hand-maintained mirror, not an authority.**
  When a migration lands, update `schema.ts` to match. The TypeScript
  compiler will surface any drift in consumer code after the update.

## Identity strategy

Dependent tables FK on `files.filename`, not `files.id`.

- `filename` is a content-derived natural key (`claude-conversation-YYYY-MM-DD-XXXXXXXX.md`)
  and is verified unique across the corpus. It survives re-imports even
  under pathological patterns like `INSERT OR REPLACE` — because SQLite's
  FK check runs per-statement, a replacement row with the same filename
  satisfies every dependent row before the statement ends.
- `files.id INTEGER PRIMARY KEY AUTOINCREMENT` still exists but *no
  longer participates in cross-table FKs*. It remains the Drizzle
  `fileId` for the labeling UI's edit-mode route keys only.
- `claude_session_id` is an advisory column only. It holds the truncated
  8-hex suffix that `claude-extract` writes into filenames, which has
  **35 known collision groups** in the current corpus (all concentrated
  in `agent-XX` sub-agent runs). Treat it as a description, not a key.
- **Full Claude UUIDs are deferred** (iteration "Chunk 5"). The plan
  exists for capturing the untruncated UUIDs from `~/.claude/projects/`
  directly and switching FK targets to that value. It has not been
  implemented because nothing is currently broken by the collisions —
  filename is the stable key and `get_file_by_session` is a smart
  resolver that falls through to `claude_session_id` only for
  non-filename inputs.

## Status enum

`files.status` is the single source of truth for "where does this file
belong in the pipeline." The enum is enforced by CHECK constraint:

| Status | Meaning | Who sets it | Re-evaluable? |
|---|---|---|---|
| `active` | Has (or will have) signals; eligible for discovery | `ingest` writes as default; `signals.compute_all` promotes from `empty` | n/a (default) |
| `empty` | Algorithm legitimately cannot score this file (too few substantive turns, all `is_system` content, etc.) | `signals.compute_all` on files that return `None` from `analyze_conversation` | **Yes** — walked on every `compute_all` run; promoted back to `active` if a future algorithm bump makes it scorable |
| `noise` | User/regex classified as not worth indexing | `filter_noise.py` | No — noise is a user content judgment, not an algorithm verdict |
| `missing` | DB row exists but markdown file is gone from `data/corpus/` | `signals.compute_all` on files whose filename has no file on disk | No — requires re-ingestion to repair |

The **empty ↔ active promotion** is a key asymmetry. Because an
algorithm bump (v6 → v7) can change what counts as scorable,
`compute_all` walks `status IN ('active', 'empty')` on every run and
flips `empty → active` when a previously-unscorable file newly returns
signals. Without this, `empty` would gradually pollute with files that
are "empty" relative to a stale algorithm version. `noise` and `missing`
are deliberately NOT walked — they represent judgments the algorithm
should not override.

**Current breakdown (steady state after Chunks 0–4):**

```
1037 active  (100% have signals)
 396 empty   (algorithm returned None; re-evaluable on next algorithm bump)
 629 noise   (regex/user classified)
2062 total
```

## Consumer matrix

Which tool reads which tables. This table is also the source of truth for
the grouping in `backup.py::REPORTED_TABLES` and `doctor.py` output.

| Table | Consumer group | Read by | Written by |
|---|---|---|---|
| `files` | **shared** | everything | `import_metadata`, `filter_noise`, `signals.compute_all` (for status) |
| `schema_migrations` | **shared** | `migrate.py` | `migrate.py` |
| `conversation_signals` | **mcp** | `mcp-server`, `ingest_conversations::print_digest` | `signals.compute_all` |
| `annotations` | **mcp** | `mcp-server`, `ingest_conversations::print_digest` | `mcp-server` (via `annotate` tool), `db.py::add_annotation` |
| `labels` | **training** | `lingo-label`, `sampler.py`, `calibrate.py` | `lingo-label::submit-label`, `calibrate.py::label` |
| `markers` | **training** | `lingo-label` (if it grows marker UI) | `db.py::add_marker` |
| `examples` | **training** | `lingo-label` (if it grows marker UI) | `db.py::add_example` |
| `pending_labels` | **training** | `lingo-label::get-queue` | `characterize.py::store_result` |
| `noise_predictions` | **training** | `lingo-label::get-conversation` | `noise_filter/deterministic.py`, `noise_filter/inference.py` |
| `model_feedback` | **training** | (unused today) | (unused today) |
| `calibration_rounds` | **training** | `calibrate.py`, `sync.py` (quarantined) | `calibrate.py::round` |
| `calibration_items` | **training** | `calibrate.py` | `calibrate.py::round` |

**The MCP server must not read training-side tables.** If the MCP surface
ever needs label or marker information, it should go through a service
layer, not query the tables directly — this keeps the consumer boundary
enforceable by inspection.

## Tables

### `files` (shared)

One row per conversation file in `data/corpus/`.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | Legacy PK; no longer a FK target |
| `filename` | TEXT UNIQUE NOT NULL | **FK target for all dependent tables** |
| `claude_session_id` | TEXT | Advisory (collision-prone) |
| `date` | TEXT | Extracted from filename (`YYYY-MM-DD`) |
| `is_agent` | BOOLEAN | Agent conversation flag |
| `file_size` | INTEGER | Bytes |
| `user_turns` | INTEGER | Total user turns |
| `claude_turns` | INTEGER | Total Claude turns |
| `substantive_user_turns` | INTEGER | Turns with >10 words, not commands |
| `user_word_count` | INTEGER | |
| `claude_word_count` | INTEGER | |
| `dialogue_density` | REAL | `user_word_count / user_turns` |
| `has_command_expansion` | BOOLEAN | Contains an expanded slash command |
| `has_reflective_language` | BOOLEAN | Matches reflective patterns |
| `source_path` | TEXT | Original file location from ingestion |
| `status` | TEXT DEFAULT 'active' | CHECK: `active\|noise\|empty\|missing` |
| `imported_at` | TEXT | Timestamp |
| `created_at` | TEXT | Timestamp |

**Indexes:** `idx_files_date`, `idx_files_substantive`,
`idx_files_claude_session`, `idx_files_status`.

**Upsert pattern** (in `db.py::import_metadata`): `ON CONFLICT(filename)
DO UPDATE SET ...`. Preserves `id` across re-imports, which in turn
preserves the legacy Drizzle `fileId` used by the labeling UI's
edit-mode route.

### `schema_migrations` (shared)

Tracks which migration files have been applied. Bootstrapped by
`migrate.py::ensure_migrations_table` on every run.

| Column | Type | Notes |
|---|---|---|
| `name` | TEXT PK | Migration filename (e.g. `02-rebuild-fk-tables.sql`) |
| `applied_at` | TEXT NOT NULL | ISO timestamp (UTC) |

### `conversation_signals` (mcp)

One row per file that the current signal algorithm can score. Missing
rows for an `active` file indicate a coverage gap that `make doctor`
will surface.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `filename` | TEXT UNIQUE NOT NULL | FK → `files(filename)` ON UPDATE CASCADE |
| `metalogue_score` | INTEGER | Overall score; `idx_signals_score DESC` for ranking |
| `concept_density` | REAL | Keywords per turn |
| `reflective_turns` | INTEGER | Turns matching reflective patterns |
| `reflective_words` | INTEGER | Words inside reflective turns |
| `rich_turns` | INTEGER | Turns meeting rich threshold |
| `medium_rich_turns` | INTEGER | |
| `very_rich_turns` | INTEGER | |
| `corrections` | INTEGER | Count of detected user corrections |
| `meta_awareness` | INTEGER | Count of meta-awareness markers |
| `cross_diversity` | INTEGER | Distinct modalities referenced |
| `terse_ratio` | REAL | Proportion of terse turns |
| `trajectory_shape` | TEXT | Classifier output |
| `concept_keywords` | TEXT | JSON array |
| `best_preview` | TEXT | Best user-turn excerpt (for digest display) |
| `computed_at` | TEXT | Timestamp |
| `algorithm_version` | TEXT | `signals.py::ALGORITHM_VERSION` at compute time; stale rows flagged by `check_staleness` |

**Upsert pattern**: `ON CONFLICT(filename) DO UPDATE SET ...`.

**Indexes:** `idx_signals_score` (DESC), `idx_signals_filename`.

### `annotations` (mcp)

Marginal signals written against conversations or passages within them.
The grammar is kind/value/thread where `kind` identifies the signal
type (`reading`, `connection`, `tension`, `proposal`, `metalogue_verdict`,
etc.), `value` is a short classification, and `thread` optionally links
multiple annotations into a line of attention.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `filename` | TEXT NOT NULL | FK → `files(filename)` ON UPDATE CASCADE |
| `exchange_start` | INTEGER | NULL = whole conversation |
| `exchange_end` | INTEGER | NULL = whole conversation |
| `kind` | TEXT NOT NULL | E.g. `reading`, `connection`, `tension`, `proposal`, `metalogue_verdict` |
| `value` | TEXT | Short classification |
| `thread` | TEXT | Optional thread name tying related annotations together |
| `notes` | TEXT | Long-form note |
| `source` | TEXT DEFAULT 'human' | `human` or agent identifier |
| `created_at` | TEXT | Timestamp |

**Indexes:** `idx_annotations_filename`, `idx_annotations_kind`,
`idx_annotations_thread`.

**Multiple annotations per file are allowed.** Whole-conversation and
passage-level annotations coexist on the same file.

### `labels` (training)

Human judgments on conversations or segments, produced by `lingo-label`
or `calibrate.py`.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `filename` | TEXT NOT NULL | FK → `files(filename)` ON UPDATE CASCADE |
| `turn_start` | INTEGER | NULL = whole conversation |
| `turn_end` | INTEGER | |
| `rating` | INTEGER NOT NULL | 1=thin, 2=functional, 3=rich |
| `tags` | TEXT | JSON array of secondary tags |
| `notes` | TEXT | |
| `created_at` | TEXT | Timestamp |

**Idempotency:** upsert on `(filename, turn_start, turn_end)` —
re-labeling the same segment updates the existing row. Implemented in
`db.py::add_label`.

**Index:** `idx_labels_filename`.

### `markers` (training)

Emergent vocabulary of epistemic patterns. Small, slow-growing table.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | FK target for `examples.marker_id` |
| `name` | TEXT UNIQUE NOT NULL | E.g. `framing-before-solving` |
| `description` | TEXT | What this pattern looks like |
| `created_at` | TEXT | |

**Idempotency:** `add_marker(name)` returns the existing id if `name`
already exists.

### `examples` (training)

Concrete excerpts illustrating a marker.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `marker_id` | INTEGER NOT NULL | FK → `markers(id)` |
| `filename` | TEXT NOT NULL | FK → `files(filename)` ON UPDATE CASCADE |
| `turn_start` | INTEGER | |
| `turn_end` | INTEGER | |
| `excerpt` | TEXT | The actual text |
| `notes` | TEXT | Why this exemplifies the marker |
| `created_at` | TEXT | |

**Indexes:** `idx_examples_marker`, `idx_examples_filename`.

### `pending_labels` (training)

Queue of candidate label suggestions produced by `characterize.py`
(automated epistemic analysis), awaiting human confirmation in
`lingo-label`.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `filename` | TEXT NOT NULL | FK → `files(filename)` ON UPDATE CASCADE |
| `turn_start` | INTEGER | |
| `turn_end` | INTEGER | |
| `source` | TEXT DEFAULT 'manual' | Which characterization strategy produced it |
| `context` | TEXT | Model reasoning, if any |
| `created_at` | TEXT | |

**Index:** `idx_pending_labels_filename`.

### `noise_predictions` (training)

Per-turn noise classification used by `lingo-label`'s conversation view
to grey out noise turns.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `filename` | TEXT NOT NULL | FK → `files(filename)` ON UPDATE CASCADE |
| `turn_idx` | INTEGER NOT NULL | |
| `deterministic_is_noise` | INTEGER | Regex-based classification |
| `deterministic_reason` | TEXT | Which rule matched |
| `ml_score` | REAL | Classifier probability |
| `ml_is_noise` | INTEGER | Classifier verdict |
| `human_label` | INTEGER | Human override (0 or 1) |
| `created_at` | TEXT | |
| `updated_at` | TEXT | |

**Unique:** `(filename, turn_idx)` — one prediction per turn.

**Index:** `idx_noise_predictions_filename`.

### `model_feedback` (training)

Unused today. Historical artifact from an earlier pairwise-feedback
exploration. Kept in the schema because its row count is zero and
removing it would be a migration for no gain.

### `calibration_rounds`, `calibration_items` (training)

Themed calibration rounds for human ground-truth labeling. Used by
`calibrate.py` via CLI (`python -m python.qino_lingo.calibrate`).
The remote-sync half of this workflow (`sync.py`) is currently
quarantined — the local schema is post-Chunk-1, but the remote D1
backend has not been migrated, so calibration sync is documented as
broken until calibration is revived as its own iteration.

## Key queries

### Unlabeled active files (for labeling queue)

```sql
SELECT f.* FROM files f
LEFT JOIN labels l ON f.filename = l.filename
WHERE f.status = 'active' AND l.id IS NULL
ORDER BY f.substantive_user_turns DESC;
```

### Fresh high-signal arrivals (last 7 days, unannotated)

```sql
SELECT f.date, cs.metalogue_score, cs.best_preview
FROM conversation_signals cs
JOIN files f ON cs.filename = f.filename
WHERE f.status = 'active'
  AND f.date >= date('now', '-7 days')
  AND f.filename NOT IN (
    SELECT filename FROM annotations WHERE kind = 'metalogue_verdict'
  )
ORDER BY cs.metalogue_score DESC
LIMIT 5;
```

(This is the exact query `ingest_conversations.py::print_digest` runs
at the end of every `make ingest`.)

### Coverage gap (should be zero in steady state)

```sql
SELECT COUNT(*) FROM files f
WHERE f.status = 'active'
  AND f.filename NOT IN (SELECT filename FROM conversation_signals);
```

If this returns non-zero, either `make signals` needs to catch up
(transient, fine) or the algorithm is rejecting files that ingestion
classified as active (`make doctor` will distinguish the two).

### Status breakdown

```sql
SELECT status, COUNT(*) FROM files GROUP BY status;
```

### Rich files (label rating = 3)

```sql
SELECT f.* FROM files f
JOIN labels l ON f.filename = l.filename
WHERE l.rating = 3;
```

### Examples for a marker

```sql
SELECT e.*, f.filename
FROM examples e
JOIN files f ON e.filename = f.filename
WHERE e.marker_id = ?;
```

## Operational commands

```bash
make migrate          # Apply pending migrations
make migrate-status   # Show applied + pending
make migrate-dry      # Preview without applying

make backup           # Transactional snapshot of corpus.db + sha256 manifest
make backup-dry       # Plan a backup + rotation without writing anything

make doctor           # FK + coverage + reconciliation health check
make doctor-verbose   # Same, with up to 5 sample rows per finding

make stats            # Raw corpus.db stats as JSON
make signals          # Recompute signals for the entire corpus
make ingest           # Full pipeline (pull + backup + index + signals + digest)
```

## Python API

The Python surface in `db.py` is filename-keyed throughout. All functions
accept an optional `db_path` parameter (default: `corpus.db`).

```python
from python.qino_lingo.db import (
    get_connection,         # Context manager (enables FK enforcement)

    # File queries
    import_metadata,        # JSON → upsert into files
    get_file,               # By filename
    get_file_by_session,    # Filename (preferred) or claude_session_id (fallback)
    get_files_by_criteria,
    get_files_by_status,
    get_unlabeled_files,
    get_pending_files,
    update_file_status,

    # Labels
    add_label,              # Idempotent on (filename, turn_start, turn_end)
    get_labels,
    get_rich_files,
    get_files_by_rating,

    # Markers + examples
    add_marker,             # Idempotent on name
    get_markers,
    add_example,
    get_examples_for_marker,

    # Annotations
    add_annotation,
    get_annotations,
    update_annotation,

    # Stats
    get_stats,
)
```

`init_db` still exists for fresh-db bootstrapping but is not the canonical
schema authority — it's kept in sync with the post-Chunk-1 schema as a
convenience, but the real truth lives in `migrations/*.sql`.

## Related documentation

- `docs/architecture.md` — top-level data flow (Phase 1 pull, Phase 1.5
  backup, Phase 2 index, Phase 3 enrich, digest)
- `docs/ingestion-routine.md` — the `make ingest` routine spec
- `docs/mcp-server-evolution.md` — why the MCP side grew and what it needs
- `implementations/persistence-layer/content/01-holistic-refactor.md` —
  the iteration that produced this schema, with chunk-by-chunk rationale
  and learnings
