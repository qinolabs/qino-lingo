# 01 — Holistic refactor of the persistence layer

**Status**: in progress
**Started**: 2026-04-08
**Trigger**: routine ingestion uncovered massive silent FK orphaning;
investigation revealed the schema was built for labeling and never adapted
when the MCP server became a second consumer.

## Why

When qino-lingo was just a labeling tool, the persistence layer's job was
simple: hold conversation metadata, hold human ratings on conversations, let
the labeling UI read both. Schema decisions reflected that — and several of
them are now actively wrong:

1. **Identity is fragile.** `files.id` is `INTEGER PRIMARY KEY AUTOINCREMENT`.
   Every dependent table FKs to it. The ingest path uses
   `INSERT OR REPLACE INTO files`, which SQLite implements as DELETE + INSERT
   on conflict — allocating a *new* id and silently orphaning every
   dependent row. Until 2026-04-08, this had been happening on every ingest
   run since around mid-January, accumulating into:

   | Table | Rows | Orphaned (% lost) |
   |---|---|---|
   | `noise_predictions` | 1506 | 1506 (100%) |
   | `conversation_signals` | 1038 | 1007 (97%) |
   | `pending_labels` | 21 | 17 (81%) |
   | `calibration_items` | 6 | 6 (100%) |
   | `labels` | 3 | 2 (67%) |

2. **Foreign keys are declared but not enforced.** The schema writes
   `FOREIGN KEY (file_id) REFERENCES files(id)`. SQLite ignores this unless
   each connection explicitly runs `PRAGMA foreign_keys = ON`. None do. So
   the FK declaration is documentation that lies — the database *describes*
   a constraint that nothing checks.

3. **Filesystem state and database state both encode "is this noise?"** —
   and they drift. `filter_noise.py` *moves files* into `_noise/`. The
   `files` table has a `status` column with values `active | filtered |
   pending`, but it's never set — every imported row is `'active'` forever.
   So a conversation can be physically in `_noise/` while its db row says
   `status='active'`. Today: ~340 db rows are in this state. They show up in
   "active files" counts but `compute_all` can't read them because it scans
   `data/corpus/` (top level) and never descends into `_noise/`.

4. **The MCP server depends on tables the original design didn't anticipate.**
   `conversation_signals`, `annotations`, the new `candidates`/`read_thinking`
   query patterns — these were grafted onto a schema designed for labeling.
   Because the MCP server's joins are inner joins through `files.id`, it
   silently dropped 97% of its corpus from results without anyone noticing.
   The system "worked" against a small healthy subset and an enormous
   invisible orphan layer.

5. **Backup discipline is frozen at the labeling era.** `backup-corpus.sh`
   reports `labels` and `noise_predictions` counts in its output — both are
   training-side tables. It doesn't know about `conversation_signals`,
   `annotations`, or `calibration_items`. It's manual. It was last run twice,
   in January, three months apart. It uses `cp` rather than SQLite's
   transactional `.backup` command. The "keep last 10" rotation never
   triggered because it had only 2 rows to rotate.

The data that the MCP server reads is now load-bearing for downstream work
(metalogue sourcing, deck composition, conversation discovery). Treating it
as scaffolding under the labeling app is no longer safe.

## Constraints

- **No schema migration tooling exists** in qino-lingo today. Anything that
  changes table layout has to be either an idempotent `CREATE TABLE IF NOT
  EXISTS` (which won't add columns to existing tables) or a manual ALTER
  script. Adding migration tooling is in scope for this iteration if needed,
  but should be lightweight — Alembic is overkill.
- **The corpus is regeneratable but expensive to lose.** Source markdown
  files in `data/corpus/` are the canonical truth — every db row and every
  signal can be rebuilt from them. But signal recompute is ~30 seconds for
  ~1700 files, and the markdown files themselves come from
  `claude-extract`'s view of `~/.claude/projects/`, which can be lost or
  corrupted. The backup story has to think about both layers.
- **The `lingo-label` app and the MCP server both read this database.**
  Schema changes need to keep both working. The lingo-label app uses Drizzle
  ORM (TypeScript) — schema changes need a corresponding Drizzle update.
- **No active labeling work.** Per user, no meaningful labels have been
  produced yet, so the `labels` table can be reshaped without preserving
  existing data. This is the only reason a holistic refactor is feasible
  rather than incremental.

## Design

### Identity strategy

Switch from `files.id INTEGER` (autoincrement, fragile) to a stable
content-derived identifier as the foreign key target across all dependent
tables. The right identifier requires care — see findings below.

**Findings from the uniqueness audit (2026-04-08)**:

The current `files.session_id` column is **NOT unique**. Across 1773 rows:
- 1479 distinct values
- 35 collision groups
- 294 duplicate rows
- All collisions concentrated in `agent-XX` sub-agent runs (e.g., `agent-a2`
  appears in 21 different conversations across different dates)

Root cause: `claude-extract` (the third-party CLI we use to pull
conversations out of `~/.claude/projects/`) truncates Claude's full session
UUIDs to 8 hex chars when writing markdown filenames, and truncates agent
runs even more aggressively (`agent-a2`, only ~256 possible values). By the
time files land in `data/corpus/`, the full UUID is already gone, and our
`extract_session_id()` reads the truncated form back from the filename.

**But we have access to the original UUIDs ourselves.**
`ingest_conversations.py::filter_by_folder` already walks
`~/.claude/projects/*/` directly to determine which sessions belong to
qinolabs projects. At that exact moment we have the full `.jsonl` filenames
with their complete UUIDs. We can capture them and bypass claude-extract's
truncation entirely.

**Naming clarity**: rename `session_id` → `claude_session_id` across the
schema. Reasoning:
- The current name reads as "the qino-lingo session identifier" — implying
  we generate it. We don't. It comes from Claude Code.
- Reserving the unprefixed `session_id` leaves room for a future
  qino-lingo-internal session concept (a labeling session, an MCP
  exploration session) without name collision.
- The longer name self-documents the external dependency at every read site.
- General principle: when a column references an external system's
  identifier, name it with the external system's prefix (`claude_`,
  `github_`, `linear_`) rather than a generic name. Future contributors
  reading the schema should never have to ask "whose ID is this?"

**Two-stage migration**:

*Stage A — interim FK target (no UUID capture yet)*:
- Use `filename` as the FK target. It is already UNIQUE in the schema,
  verified unique today (1773/1773), and stable across re-imports.
  `filename` is essentially `(date, claude-extract-truncated-id)` encoded
  as a string, which is unique even though its individual pieces aren't.
- This stage gets us off `files.id INTEGER` autoincrement and onto a
  natural key with zero new ingestion logic.

*Stage B — capture full UUIDs and switch the FK target to claude_session_id*:
- Modify `ingest_conversations.py` to capture the full Claude UUID at the
  point where `filter_by_folder` walks `~/.claude/projects/*/`.
- Pass the full UUID through to `extract_metadata.py` (currently
  filename-only) and on to `import_metadata`.
- Add `claude_session_id TEXT NOT NULL UNIQUE` to `files`. Backfill by
  re-walking `~/.claude/projects/` for files already in the corpus
  (matching by truncated id + filename date).
- Switch FK targets from `filename` to `claude_session_id`.

Stage A is small and self-contained. Stage B is more involved because it
touches the ingestion pipeline. Stage A can ship first to stop the bleeding
structurally; Stage B can follow in a separate iteration if the appetite
isn't there immediately.

This makes the FK pattern naturally orphan-resistant: even if `files` is
re-imported with `INSERT OR REPLACE`, the `claude_session_id` survives, so
dependent rows stay valid by content rather than by SQLite-internal id.

### FK enforcement

Enable `PRAGMA foreign_keys = ON` in `db.py::get_connection`. Done in this
session as part of stopping the bleeding. Going forward, FK violations will
error loudly instead of accumulating.

Caveat: this only catches *new* writes that violate constraints. Pre-existing
orphans are not retroactively detected. A `PRAGMA foreign_key_check` on
startup (or before backup) would catch drift early.

### Status as the single source of truth for noise

Replace the filesystem-as-noise-marker pattern with a `status` column that
filter_noise.py actually sets.

- `status='active'` — conversation is in `data/corpus/`, has substantive content
- `status='noise'` — filter_noise.py classified it as noise
- `status='empty'` — has no substantive user turns (signals legitimately empty)
- `status='missing'` — db row exists but markdown file is gone

Stop physically moving files into `_noise/`. Keep them in `data/corpus/`
and update `status` instead. This:
- Makes `compute_all` correct by default (it can filter by status)
- Eliminates the filesystem/db drift
- Lets the MCP server query the full corpus consistently
- Makes "what was filtered out and why" inspectable from the db

Trade-off: `data/corpus/` becomes a flat ~2000-file directory instead of
two ~1000-file directories. This is fine — it's a data dir, not a working dir.

Migration plan: read the current contents of `data/corpus/_noise/`,
upsert those filenames as `status='noise'` rows in the db, then move them
back into `data/corpus/`. After this, `_noise/` no longer exists as a
filesystem concept.

### Dual-consumer aware schema

Formally separate the two consumer concerns *within the same database* by
namespace (table prefixes), not by file:

- **Shared core**: `files`
- **MCP-side**: `conversation_signals`, `annotations`
- **Training-side**: `labels`, `markers`, `examples`, `pending_labels`,
  `noise_predictions`, `calibration_items`

The point isn't to isolate them — they share `files`. The point is to make
the dual-purpose nature of the db explicit so schema decisions are made
with both consumers in mind, not silently shaped by whichever one was
loudest at the time.

Document the separation in `docs/schema.md` and add a "consumer matrix" —
which tools read which tables. The MCP server should never read training-side
tables; the lingo-label app should never read `conversation_signals` directly
(it should query through a service layer if it needs signals).

### Signal coverage instrumentation

The current `check_staleness()` only catches algorithm version drift. It
should also catch:

- Files whose `status='active'` but have no signal row AND no recorded reason
- Signal rows whose `algorithm_version` doesn't match `ALGORITHM_VERSION`
- Signal rows whose `file_id`/`session_id` doesn't resolve to a live file
  (with FK enforcement on, this should never happen — but verify on startup)

The MCP server should call this on startup (it already does for version
drift) and refuse to start if the gap is severe — or at minimum print a
loud warning *that the user can actually see*. Today's stderr warning is
swallowed by IDEs.

### Backup overhaul

Replace `backup-corpus.sh` with a Python script that:

1. Uses SQLite's `.backup` API (transactional, safe under concurrent reads)
   instead of `cp` (which can capture half-written pages)
2. Backs up *both* `corpus.db` *and* an inventory of `data/corpus/` (not
   the markdown files themselves — too much disk — but a manifest with
   filename + sha256, so we can detect if any source files went missing)
3. Reports counts for the new tables (`conversation_signals`, `annotations`,
   `calibration_items`) alongside the old ones
4. Can be invoked from the Makefile (`make backup`) and is automatically
   run by `make ingest` before destructive db work
5. Optionally pushes to a remote location (cloud bucket, second disk) — to
   be decided

Cadence: at least before each `make ingest`. One per day if `make ingest`
runs daily. Keep the last N (current: 10) plus weekly snapshots for the
last M weeks.

### Migration tooling

Add a tiny migration runner:
- Migrations live in `python/qino_lingo/migrations/{NN}-{name}.sql`
- A `schema_migrations` table tracks which have been applied
- `python -m python.qino_lingo.migrate` runs all unapplied migrations in order
- `make migrate` from the Makefile

This is ~80 lines of Python and replaces the need for any heavyweight ORM
migration tool. The `lingo-label` Drizzle schema introspects the db
afterward — it doesn't participate in the migration, just stays in sync.

### Drizzle source-of-truth: db.py is canonical

Decision: **db.py (and the migration files it manages) is the canonical
schema source. The lingo-label Drizzle schema is a generated mirror.**

Evidence this is already the de facto state:
- `apps/lingo-label/src/server/schema.ts` opens with the comment
  "Matches the existing schema in qino-lingo/corpus.db" — explicitly
  framing itself as a mirror.
- No `drizzle.config.ts` exists. No `drizzle-kit push` step.
- `apps/lingo-label/src/server/db.ts::getDb` runs `CREATE TABLE IF NOT EXISTS`
  for `pending_labels`, `model_feedback`, and `noise_predictions` inline at
  startup — defensive DDL that exists because there's no shared schema
  authority. This should go away once a real migration runner exists.

There are currently three places that touch schema:
1. `python/qino_lingo/db.py::init_db` — main definitions
2. `python/qino_lingo/signals.py::init_signal_tables` — signals table
3. `apps/lingo-label/src/server/db.ts::getDb` — pending_labels et al.

The migration runner consolidates all three. After this iteration:
- All schema lives in `python/qino_lingo/migrations/{NN}-*.sql` files
- `db.py` and `signals.py` remove their `init_*` and `CREATE TABLE IF NOT
  EXISTS` calls — they trust the schema is correct
- `lingo-label/db.ts` removes its inline DDL — same reason
- `apps/lingo-label/drizzle.config.ts` is added (~5 lines) so `pnpm db:pull`
  can regenerate `schema.ts` from corpus.db
- `apps/lingo-label/src/server/schema.ts` becomes a generated file with a
  header comment forbidding hand edits

**Workflow for schema changes after this iteration**:
1. Write a migration file (`migrations/NN-descriptive-name.sql`)
2. `make migrate` runs it against corpus.db
3. `cd apps/lingo-label && pnpm db:pull` regenerates `schema.ts`
4. TypeScript compile errors in lingo-label tell you what code needs updating
5. Fix the TypeScript, commit

**Why not the inverse (Drizzle canonical, db.py reflects)**: the gravity of
this codebase is in Python. The vast majority of schema decisions are
driven by Python concerns — ingestion, signals, MCP server. The lingo-label
app is a single-purpose consumer (labeling UI). Putting schema authority in
the TypeScript app would invert the gravity and add a "run a pnpm command
in a sibling repo to change a column" friction tax to every Python-side
schema decision.

## Changes

(Filled in as work progresses.)

### Already done in the session that triggered this iteration

- [x] `db.py::get_connection` — enable `PRAGMA foreign_keys = ON`
- [x] `db.py::import_metadata` — replace `INSERT OR REPLACE` with proper
      UPSERT (`ON CONFLICT(filename) DO UPDATE SET ...`) so `files.id` survives
      re-imports
- [x] One-time heal: deleted 2538 orphan rows across 5 tables, recomputed
      signals across the corpus
- [x] `ingest_conversations.py` — added Phase 3 (signals computation) so the
      ingestion routine is now end-to-end correct
- [x] `Makefile` — added `ingest`, `ingest-recent`, `verify`, `digest`,
      `signals`, `stats` targets
- [x] `docs/ingestion-routine.md` — wrote the routine spec

### Planned for this iteration

**Migration tooling**
- [x] Add migration runner (`python/qino_lingo/migrate.py` + `migrations/` dir)
- [x] `schema_migrations` table to track applied migrations
- [x] Add `make migrate` to Makefile

**Identity, Stage A — interim (filename as FK target)**
- [x] Migration `01-rename-session-id.sql`: rename `files.session_id` →
      `files.claude_session_id` (truncated form, kept for now). Index
      renamed to `idx_files_claude_session`.
- [x] Migration `02-rebuild-fk-tables.sql`: rebuild-and-rename for all 7
      dependent tables in a single transaction (`conversation_signals`,
      `noise_predictions`, `pending_labels`, `calibration_items`,
      `labels`, `examples`, `annotations`). Filename FK with
      `ON UPDATE CASCADE` and `ON DELETE NO ACTION` (default). The
      4-migration plan from the original Why was collapsed to 2 because
      add-column / backfill / drop-column / add-FK is awkward in SQLite;
      one rebuild-and-rename per table is the natural unit.
- [x] Update `signals.py::store_signals` to use proper UPSERT (filename
      as the conflict target) and remove `init_signal_tables` DDL —
      schema authority is the migration runner now.
- [x] Update `db.py`: rename `extract_session_id` →
      `extract_claude_session_id`, switch all FK joins to filename,
      change `add_label` / `add_example` / `add_annotation` /
      `update_file_status` parameters from `file_id: int` to
      `filename: str`. `get_file_by_session` accepts either filename
      (preferred, ends in `.md`) or claude_session_id (fallback).
- [x] Update `mcp-server/server.py` queries to join on filename. Public
      API parameter name `session_id` kept for backwards compatibility;
      it now resolves to filename or claude_session_id internally.
      Result objects still expose `"session_id"` mapped from the
      `claude_session_id` column.
- [x] Update `calibrate.py` (BASE_QUERY joins, calibration_items insert,
      label callsite). `ensure_tables` is now a no-op.
- [x] Update `characterize.py` (STRATEGIES joins, `store_result`
      parameter, callsite).
- [x] Update `sync.py` — minimally edited and quarantined; the remote
      qino-label D1 backend has not been migrated, so calibration sync
      is documented as broken until calibration is revived.
- [x] Update `sampler.py` (joins + `get_labeling_progress` count).
- [x] Update `lingo-label` Drizzle schema by hand (no `drizzle.config.ts`
      yet, so `pnpm db:pull` deferred). schema.ts now uses filename FK
      references on labels, examples, pending_labels, noise_predictions.
- [x] Delete inline `CREATE TABLE IF NOT EXISTS` blocks in
      `apps/lingo-label/src/server/db.ts`. Added
      `pragma("foreign_keys = ON")` so the lingo-label app respects FK
      enforcement (it didn't before).
- [x] Update lingo-label server functions: `get-conversation.ts`,
      `get-queue.ts`, `get-labels.ts`, `submit-label.ts`,
      `queue-actions.ts`. The submit-label form now sends `filename`
      instead of `fileId`. `get-labels` keeps a `fileId` field in its
      response (sourced from `files.id` via the join) only because
      `LabeledTab` links to the edit-mode route which keys on
      `files.id`; the autoincrement PK still exists, just no longer
      participates in cross-table FKs.
- [x] Update `src/types.ts` (FileRecord, PendingLabel, Label, Example,
      QueueItem). Caught and fixed a pre-existing type lie:
      `Label.isRich: boolean` didn't match the actual `rating: integer`
      column.
- [x] Update `src/routes/label.$id.tsx` (`fileId` → `filename` in
      submit calls).
- [x] Update batch scripts: `apps/lingo-label/scripts/noise_filter/`
      (`deterministic.py`, `inference.py`, `train.py`) and
      `training/validations/lib/` (`export.py`, `types.py`). Removed
      the inline `CREATE TABLE` block from `deterministic.py` (schema
      authority is the migration runner now). All scripts pass FK
      enforcement.

**Identity, Stage B — capture full Claude UUIDs (separate sub-iteration)**
- [ ] Modify `ingest_conversations.py::filter_by_folder` to capture the full
      UUID for each accepted file alongside the truncated form
- [ ] Pass full UUID through to `extract_metadata.py` and `import_metadata`
- [ ] Migration 05: add `claude_session_full_id TEXT UNIQUE` to `files`
- [ ] Migration 06: backfill by re-walking `~/.claude/projects/` and matching
      against existing rows by (date, truncated_id)
- [ ] Migration 07: switch FK targets from `filename` to
      `claude_session_full_id` (rename to just `claude_session_id` after
      Stage A's column is dropped)

**Status as single source of truth**
- [x] Migration `03-extend-status-enum.sql`: extend `files.status` enum
      via CHECK constraint to allow `active | noise | empty | missing`.
      Files table rebuilt-and-renamed; FK references from dependent
      tables survived because the column kept its name and uniqueness.
      `idx_files_status` added.
- [x] One-shot data migration `python/qino_lingo/collapse_noise.py`:
      backfilled 340 files (db rows whose filename was in `_noise/`)
      with `status='noise'`, ingested 289 orphans (legacy files in
      `_noise/` that had no db row at all — they predated db ingestion
      and could not be picked up by `make ingest` because that walks
      `~/.claude/projects/`, not the local corpus). Used
      `extract_metadata.extract_metadata` directly to compute their
      metadata.
- [x] Moved all 629 files from `_noise/` back into `data/corpus/`.
- [x] Removed `_noise/` directory entirely.
- [x] Update `filter_noise.py` to set status='noise' in db instead of
      moving files. Walks the active subset of the db (so noise files
      already classified are skipped). Run-once pattern is gone — it
      can be invoked safely against the active set repeatedly.
- [x] Update `signals.py::compute_all` to query db by `status='active'`
      instead of globbing `data/corpus/`. The new path resolves
      filenames to filepaths via the corpus dir, computes signals only
      for active files, and reports any files marked active but
      missing from disk (Chunk 4 will reconcile these as `missing`).
- [x] Defensive: add `status='active'` filter to MCP server
      `candidates()` query (it was relying on signal-coverage as an
      implicit filter — fine in practice because no signal rows exist
      for noise files, but explicit is safer).
- [x] Remove `_noise/` filesystem fallback in
      `apps/lingo-label/src/server/get-conversation.ts::findConversationFile`.

**Backup overhaul**
- [x] Replace `backup-corpus.sh` with `python/qino_lingo/backup.py` using
      SQLite's transactional `.backup` API. Old shell script deleted.
- [x] Add manifest of `data/corpus/` (filename + sha256 + size, no
      content) to the backup directory as a sidecar
      `corpus-TIMESTAMP[-tag].manifest.json`. Manifest is written
      atomically (`.tmp` + rename).
- [x] Backup script reports counts for new tables. The report is grouped
      by consumer (shared / mcp / training) so the dual-purpose nature
      of the db is visible at backup time, not just in `docs/schema.md`.
      Tables that don't yet exist on a given db render as `n/a` rather
      than `0` so a fresh db can be distinguished from an empty one.
- [x] Add `make backup` and `make backup-dry` to Makefile.
- [x] `make ingest` runs backup automatically before destructive db
      work. Implemented as Phase 1.5 inside `ingest_conversations.py`
      (after files are copied into `data/corpus/`, before
      `run_pipeline()` mutates the db). `--skip-backup` flag added as
      an escape hatch for the cases that need it.
- [x] Rotation: keep last 10 + one per ISO week for 8 weeks.
      Configurable via `--keep-recent` / `--keep-weekly`. The weekly
      window walks newest-to-oldest among the *post-recent* tail and
      keeps the first file per ISO week.

**Diagnostics + observability**
- [ ] `check_staleness` enhancement: catch coverage gaps + orphan rows
- [ ] Add `make doctor` — runs `PRAGMA foreign_key_check`, signal coverage
      audit, file/db reconciliation report
- [ ] MCP server startup: surface stale/orphan warnings in a way the user
      can actually see (not just stderr)

**Documentation**
- [ ] `docs/schema.md` rewrite — consumer matrix, identity strategy, status
      semantics, migration workflow
- [ ] Update `docs/architecture.md` to reflect dual-consumer reality
- [ ] Update `apps/lingo-label/CLAUDE.md` to reference db.py as canonical

## Sequencing

The change list above is organized by topic (identity, status, backup, etc.)
but execution should follow a different order — one shaped by what unlocks
what, and by how much each chunk can be reasoned about in isolation. Each
sub-iteration below is meant to be a single focused session with a clear
beginning and end. Start a fresh Claude Code session per chunk rather than
attempting more than one at a time; the iteration file is the running
context they share.

### Order of execution

**Chunk 0 — Migration runner (prerequisite for everything else)**
Build the tooling first. ~80 lines of Python. No schema changes yet, just
the runner + `schema_migrations` table + `make migrate` target.
- Add `python/qino_lingo/migrate.py` with: discover migrations in
  `migrations/` directory, track applied state in `schema_migrations`
  table, run unapplied migrations in lexical order inside a transaction.
- Add `migrations/` directory with a placeholder `00-init.sql` (no-op or
  CREATE TABLE IF NOT EXISTS for `schema_migrations` itself).
- Add `make migrate` target to Makefile.
- Verify by running `make migrate` against a copy of corpus.db, checking
  that it's idempotent (running twice does nothing the second time).

This chunk is safe in isolation — it adds infrastructure without touching
any existing schema. Land it and you can pause here without commitment.

**Chunk 1 — Stage A migrations (interim FK target = filename)**
The orphan-resistance fix. This is the biggest chunk and the one that
actually heals the structural problem. After this lands, the FK orphaning
category cannot recur regardless of upsert patterns.
- Migration `01-rename-session-id.sql`: rename `files.session_id` →
  `files.claude_session_id`.
- Update Python and TypeScript reads of `session_id`/`sessionId`.
- Migration `02-add-filename-fk.sql`: add `filename TEXT NOT NULL` to
  every dependent table, with FK declaration.
- Migration `03-backfill-filename.sql`: populate new columns by joining
  through `file_id`.
- Migration `04-drop-file-id.sql`: drop `file_id INTEGER` columns. Note:
  SQLite doesn't support `DROP COLUMN` on tables with foreign keys
  pre-3.35; use the rebuild-and-rename pattern (`CREATE new TABLE`, copy
  data, drop old, rename new).
- Update `signals.py::store_signals` to use UPSERT and write `filename`.
- Update `mcp-server/server.py` queries to join on `filename`.
- Regenerate `apps/lingo-label/src/server/schema.ts` via `pnpm db:pull`
  (also: add `apps/lingo-label/drizzle.config.ts` if it doesn't exist).
- Delete `lingo-label/db.ts`'s inline `CREATE TABLE IF NOT EXISTS` calls.
- Verify: `make doctor` (added in Chunk 4) should report zero orphans.

This chunk touches the most files but each edit is small. Run `make
ingest` end-to-end at the end and confirm the digest still reports correct
numbers.

**Chunk 2 — Status as single source of truth (collapse `_noise/`)**
Independent of Chunk 1. Can be done before, after, or in parallel with
Stage B.
- Migration `05-status-enum.sql`: extend `files.status` to allow
  `active | noise | empty | missing`.
- Migration `06-backfill-noise.sql`: read `data/corpus/_noise/`, set
  `status='noise'` for matching rows, then delete the directory.
- Update `filter_noise.py` to set status instead of moving files.
- Update `signals.py::compute_all` to query db by status, not glob.
- Update `mcp-server/server.py` to filter by status.
- Verify: digest's "without signals" number drops meaningfully because
  the ~340 files-in-_noise-but-active-in-db rows are now correctly tagged.

**Chunk 3 — Backup overhaul**
Independent of everything else. Can happen anytime.
- Replace `backup-corpus.sh` with `python/qino_lingo/backup.py` using
  SQLite's transactional `.backup` API.
- Add manifest of `data/corpus/` (filename + sha256) to backup output.
- Report counts for `conversation_signals`, `annotations`,
  `calibration_items` alongside the legacy tables.
- Add `make backup` target.
- `make ingest` runs backup automatically before destructive db work.

**Chunk 4 — Diagnostics + observability**
Small, additive, no schema changes.
- Add `make doctor` — runs `PRAGMA foreign_key_check`, signal coverage
  audit, file/db reconciliation report.
- `check_staleness` enhancement: detect coverage gaps + orphan rows.
- MCP server startup warning that surfaces in user-visible places, not
  just stderr.

**Chunk 5 — Stage B (capture full Claude UUIDs) — OPTIONAL**
Only do this if Chunk 1's `filename`-as-FK turns out to be insufficient
for some real consumer need. Most likely: not needed.
- Modify `ingest_conversations.py::filter_by_folder` to capture the full
  Claude UUID alongside the truncated form.
- Pass through to `import_metadata`.
- Migration `07-add-full-uuid.sql`: add `claude_session_full_id TEXT
  UNIQUE` to `files`.
- Migration `08-backfill-full-uuid.sql`: re-walk `~/.claude/projects/`
  and match by `(date, truncated_id)`.
- Migration `09-switch-fk-to-uuid.sql`: rebuild dependent tables with
  `claude_session_id` as the FK target instead of `filename`.
- Drop `claude_session_id` (truncated form), rename
  `claude_session_full_id` → `claude_session_id`.

### Sub-iteration discipline

Each chunk above is its own iteration session. Don't combine them, even if
they look small individually. Reasons:

1. **Verification inside the iteration is the point.** Each chunk ends
   with "verify: X is now Y." Combining chunks blurs which change caused
   which observation, and you lose the ability to reason about a single
   migration in isolation.
2. **Backup taken at the start of each chunk.** Migrations are
   destructive. A clean `make backup` checkpoint per chunk means you can
   roll back to a known state per chunk, not per arbitrary in-progress
   point.
3. **Each chunk is small enough to commit cleanly.** The git history
   becomes a meaningful sequence of "this iteration did this" rather than
   "everything happened in one giant commit."
4. **The user (operator) gets natural decision points.** After Chunk 1
   they can decide whether Chunk 2 is still worth doing now or can wait.
   After Chunk 2 they can decide whether Chunk 5 is needed at all.

### Stopping conditions

This iteration is "done enough" when Chunks 0–4 are complete. Chunk 5 is
optional and may never be needed. The iteration file should get a
"Learnings" section when each chunk lands, and the iteration as a whole
should be marked complete only after all required chunks are verified
healthy via `make doctor`.

## Technical decisions

(To be filled in during execution. Capture decisions that a reasonable
person could have made differently and the reasoning that pushed toward the
chosen path.)

## Learnings

(To be filled in after the iteration completes. Capture surprises,
incidents, and things that should change the next iteration's approach.)

### Chunk 3 — Backup overhaul (landed 2026-04-08)

- **`sqlite3.Connection.backup()` is the right primitive — and it's in
  the stdlib.** No external dependency. The shell script was using
  `cp`, which can capture a torn page if a writer is mid-commit; the
  online backup API holds the right locks for the duration of the
  copy and produces a snapshot whose `PRAGMA integrity_check` AND
  `PRAGMA foreign_key_check` both come back clean. Verified on the
  first real backup of the iteration: a `corpus-…-pre-chunk3-apply.db`
  snapshot is byte-correct, FK-consistent, and identical in size to
  the live db.
- **Atomic manifest writes via `.tmp` + rename.** The manifest is a
  372KB JSON file listing 2062 files with sha256 + size. A naive write
  could leave a half-written manifest if the script is killed
  mid-write. Writing to `manifest_path.with_suffix(".json.tmp")` and
  then `.replace()` (POSIX `rename()`, atomic on the same filesystem)
  guarantees the manifest is either complete or absent — never
  partial. Same trick the SQLite backup API uses internally for the
  db file.
- **Two pruning bugs caught by dry-run at boundary inputs.** First
  draft of `plan_rotation` checked the weekly-window limit *after*
  adding to the kept set — so `keep_weekly=0` retained one entry
  instead of zero. Caught by running `--dry-run --keep-recent 3
  --keep-weekly 0` against the existing 7 backups: expected 4 pruned,
  saw 3. Fix was a one-line reorder. Second issue: the dry-run was
  computing rotation against the *current* file set (7 files) instead
  of the *post-backup* file set (8 files), so the dry-run prune count
  was off by one against what the real run would do. Fixed by
  factoring out `split_rotation(list, ...)` from `plan_rotation(dir,
  ...)` and having the dry-run inject a simulated entry for the
  would-be new file. Both bugs would have been invisible at default
  thresholds (`keep_recent=10, keep_weekly=8` against 7 files prunes
  nothing). **Lesson: dry-run at the *boundaries* of inputs catches
  more than dry-run at the defaults.**
- **The chunk-anchor backup convention paid off.** The pre-chunk-0,
  pre-chunk-1, pre-chunk-2 backups already existed from the previous
  chunks (taken manually before each migration applied). With the new
  rotation policy (keep 10 recent + 8 weekly), they all stay safely
  inside the keep window and become the savepoint timeline that
  "Sub-iteration discipline" called for. The new
  `pre-chunk3-apply.db` snapshot continues the convention. After
  Chunk 4 lands, the backups directory will literally read like the
  iteration's running git tag history.
- **Report grouped by consumer (shared / mcp / training).** Pulled
  the `REPORTED_TABLES` table list from the iteration's "Dual-consumer
  aware schema" section: `files` is shared; `conversation_signals`
  and `annotations` are MCP-side; `labels`, `markers`, `examples`,
  `pending_labels`, `noise_predictions`, `model_feedback`,
  `calibration_rounds`, `calibration_items` are training-side. This
  makes the report self-document the dual-purpose nature of the db.
  When `docs/schema.md` gets its rewrite, the same grouping should be
  used as the consumer matrix.
- **Missing tables render as `n/a`, not `0`.** A fresh db (one that
  hasn't run all migrations yet) has rows missing from
  `REPORTED_TABLES`. Treating "table missing" as "0 rows" would
  silently let a half-migrated db pass for an empty one. The `-1`
  sentinel surfaces the distinction in the report.
- **Wired into ingestion as Phase 1.5, not as a Make dependency.**
  Considered chaining `make ingest: backup`, but that would skip the
  backup if anyone invoked `python3 ingest_conversations.py`
  directly. Inlining the call inside `main()` (after files copied,
  before `run_pipeline()` mutates the db) makes the backup *part of
  the ingest contract* rather than scaffolding around it. Added
  `--skip-backup` as the only escape hatch.
- **`--no-rotate` exists for the case where you're about to take a
  *labeled* backup that you don't want pruned by the rotation
  arithmetic.** Not used by `make ingest` (which always rotates), but
  the option is there for ad-hoc usage like
  `python -m python.qino_lingo.backup --tag pre-major-surgery
  --no-rotate`.
- **What `make ingest` looks like end-to-end after Chunk 3**:
  `claude-extract → temp dir → filter → dedupe → copy into
  data/corpus/ → BACKUP (transactional snapshot + manifest +
  rotation) → filter_noise → extract_metadata → import_metadata →
  signals.compute_all → digest`. Documented in
  `docs/ingestion-routine.md` as "Phase 1.5 — Backup."
- **Verification:**
  - `python -m python.qino_lingo.backup --dry-run` reports current
    state correctly
  - `python -m python.qino_lingo.backup --tag chunk3-verify` writes
    a real `.db` + sidecar `.manifest.json` (then cleaned up; the
    canonical Chunk-3 anchor is `pre-chunk3-apply.db`)
  - `sqlite3 backups/...pre-chunk3-apply.db "PRAGMA integrity_check;
    PRAGMA foreign_key_check;"` returns `ok` and empty
  - Manifest JSON validates: 2062 entries, every sha256 64 chars
    long, every entry has `filename` + `sha256` + `size`
  - `make backup`, `make backup-dry`, `make help` all work
  - Rotation tested at `keep_recent=3, keep_weekly=0` (3 kept,
    4 pruned), `keep_recent=3, keep_weekly=2` (5 kept), and
    defaults (7 kept, 0 pruned)
  - `make migrate-status` still shows all four migrations from
    Chunks 0–2 applied — backup module touched no schema
  - `ingest_conversations.py --help` shows the new `--skip-backup`
    flag

### Chunk 2 — Collapse `_noise/` into files.status (landed 2026-04-08)

- **The drift was bigger than the iteration plan estimated.** Plan
  said "~340 files in `_noise/`-but-active-in-db". Reality: 629 files
  in `_noise/` total — 340 with db rows (the expected case) plus 289
  *orphans* with no db row at all. The orphans were legacy state from
  when `filter_noise.py` ran *before* db ingestion existed: it moved
  files into `_noise/` before they ever got into the db, so they sat
  there invisibly for months.
- **Orphan recovery required a one-shot data migration, not pure SQL.**
  `make ingest` walks `~/.claude/projects/`, not the local corpus, so
  the orphans could not be re-ingested by re-running ingestion. The
  fix was to call `extract_metadata.extract_metadata()` directly on
  each orphan file, build the same metadata dict the normal pipeline
  produces, and INSERT with `status='noise'`. This is exactly the
  kind of data migration that doesn't fit the SQL-only migration
  runner — `python/qino_lingo/collapse_noise.py` is a one-shot script
  that does the work in a single transaction (340 backfills + 289
  inserts, then filesystem moves, then directory removal).
- **Schema change was small and clean.** Migration 03 only adds a
  CHECK constraint on `files.status`. Implemented via the same
  rebuild-and-rename pattern Chunk 1 used. The dependent tables FK to
  `files(filename)` and survived the rebuild because the column kept
  its name and uniqueness — verified with `PRAGMA foreign_key_check`
  empty after the rebuild.
- **Surprising win on signal coverage.** Before Chunk 2 the digest
  reported 736 active files without signals. After Chunk 2 it's 396 —
  a 340-file drop, exactly matching the number of in-db noise files
  that got reclassified. The remaining 396 are the *true* signal
  coverage gap (Chunk 4 territory). Pre-Chunk-2, the gap was a mix of
  "noise files we never expected to compute signals for" and "real
  coverage holes in the active set" — and there was no way to tell
  them apart. Now there is.
- **No stale signal data to clean up.** Counter-intuitive: zero
  `conversation_signals` rows existed for files that became noise in
  Chunk 2. Why? Because the OLD `signals.py::compute_all` globbed
  `data/corpus/*.md` (top level only) — `_noise/` was never in its
  scope. So even though the noise files had `status='active'` in db,
  they had been silently skipped by signal computation all along. The
  bug was that the system "worked" by accident: two layers of state
  (filesystem location and db status) drifted apart, but the
  filesystem-globbing reads happened to use the correct layer.
- **The 289 orphans turned out to be tiny files.** Spot-checked one:
  683 bytes, 2 user turns, 0 substantive content. These were noise
  classifications from before db ingestion existed — they're real
  conversations, just very short ones. Recovering them adds nothing
  to the signal corpus, but it does mean every file in `data/corpus/`
  now has a db row, which is the invariant Chunk 4's `make doctor`
  will verify.
- **`filter_noise.py` rewritten as a db updater, not a file mover.**
  New shape: walks the *active* subset of the db (by query, not by
  filesystem glob), checks each file against the same regex rules,
  sets `status='noise'` for matches. Idempotent — safe to run
  repeatedly. Reports a breakdown of reasons but doesn't move files
  anywhere. The `--dry-run` flag was added for safety; the post-Chunk
  2 dry-run shows 0 reclassifications because every active file is
  already correctly classified.
- **The TypeScript `findConversationFile` fallback is gone.** Chunk 1
  had a comment marking it as removable once Chunk 2 lands. Removed
  in this commit. After Chunk 2, every conversation lives at the top
  level of `data/corpus/` regardless of noise/active status — there's
  no other location to fall through to.
- **Defensive add: `status='active'` in candidates()**. Pre-Chunk-2,
  the MCP server's `candidates()` query relied implicitly on
  signal-coverage (no signals existed for noise files, so they
  couldn't appear in candidate results). With Chunk 2, the noise
  files DO have valid db rows but still no signals. The implicit
  guarantee still holds — but it's fragile. Added explicit
  `WHERE f.status = 'active'` so a future signal recompute that
  accidentally included noise files wouldn't surface them in
  candidates.
- **Verification:**
  - 2062 db rows = 2062 files at top level of `data/corpus/`
    (1433 active + 629 noise)
  - `_noise/` directory deleted
  - `PRAGMA foreign_key_check` empty
  - `make digest` shows the new active/coverage numbers correctly
  - `make signals --since 2026-04-01` exercises the new
    `compute_all` query path (44 active conversations, 41 computed)
  - `pnpm typecheck` clean
  - MCP server smoke tests pass: `search()` and `candidates()`
    return only active files; `metadata()` on a known noise file
    returns `status=noise` correctly (users can still retrieve noise
    files by id, they're just excluded from discovery queries)

### Chunk 1 — Stage A migrations + consumer updates (landed 2026-04-08)

- **Two migrations, not four.** The original plan called for four
  separate migrations (rename, add column, backfill, drop+FK). In
  practice the SQLite-natural unit is one rebuild-and-rename per table,
  and combining all 7 rebuilds in a single transaction is *more* atomic
  than splitting them, not less. Migration runner already wraps each
  migration in a transaction; one combined migration = one transaction
  = all-or-nothing. Final shape: `01-rename-session-id.sql` (trivial)
  and `02-rebuild-fk-tables.sql` (~330 lines, single transaction).
- **Filename-as-FK is stronger than expected.** The dry-run revealed
  a counter-intuitive fact: with `ON DELETE NO ACTION` (default), an
  `INSERT OR REPLACE INTO files` does NOT orphan dependent rows.
  SQLite's FK check is per-statement, not per-operation: at end of
  statement, every dependent row has a parent with the same filename
  (the new row), so the intermediate "delete" inside REPLACE is
  invisible to the checker. With `file_id` as the FK target, the same
  pattern was destructive because the new row got a new autoincrement
  id. So filename-as-FK eliminates the orphaning class entirely:
  - Proper UPSERT (Chunk 0 pattern): works, dependents preserved.
  - INSERT OR REPLACE on same filename: works, dependents preserved
    (the surprise — caught by behavioral test in dry-run).
  - Explicit DELETE FROM files with children present: blocked with
    constraint error 19 (correct: forced cleanup).
- **`ON DELETE CASCADE` was the wrong instinct.** First-draft migration
  used CASCADE; behavioral test showed it cascade-deleted dependent
  rows on REPLACE — *amplifying* the original bug instead of fixing
  it. This is exactly what dry-runs are for. Switched to NO ACTION
  (default) and the behavior inverted to correct.
- **Consumer surface area was bigger than the iteration plan listed.**
  Plan named signals.py, mcp-server, and lingo-label Drizzle. Reality:
  also calibrate.py, characterize.py, sync.py, sampler.py, six lingo-
  label server fns, types.ts, two routes, and four batch scripts in
  noise_filter/ and training/validations/. Catching all of them in one
  session was feasible because each edit was small (~5–20 lines), but
  a future iteration with more code surface should plan a 2-session
  split (backend / frontend) by default.
- **MCP public API kept stable.** The MCP server's tool signatures
  use `session_id` as a parameter name. Renaming this would break
  existing user workflows (the user passes `session_id` from search
  results to subsequent tool calls). The internal column is now
  `claude_session_id`; the parameter name is preserved as an external
  contract. `get_file_by_session` is now a smart resolver: if the
  input ends in `.md` it looks up by filename (the stable, unique
  identifier — preferred); otherwise it falls back to
  `claude_session_id`, which is collision-prone (35 collision groups
  in current corpus, returns first match arbitrarily). Stage B fixes
  the collision class by capturing full Claude UUIDs.
- **Two pre-existing bugs caught and fixed alongside the migration.**
  (1) `mcp-server/server.py::get` view="thinking" referenced
  `density` outside its conditional assignment scope — would
  `NameError` on conversations without signals. (2) `apps/lingo-label/
  src/types.ts::Label` declared `isRich: boolean` but the actual
  column is `rating: integer`. Both type-level lies that hadn't
  surfaced because no caller exercised them. Fixed during the
  migration sweep because they were in the same files.
- **`apps/lingo-label/src/server/db.ts` now has `foreign_keys = ON`.**
  It didn't before. This was a silent gap where the lingo-label app
  was reading from the same db as everything else but FK enforcement
  wasn't on for its connections. Without this fix, the structural
  guarantees from Chunk 1 would only have applied to Python writes.
- **Coverage gap surfaced (deferred to Chunk 4).** 736 of 1773 active
  files have no `conversation_signals` row. The migration left this
  state untouched (the rebuilds just preserved what was there). This
  is exactly what `make doctor` is meant to catch.
- **`sync.py` quarantined, not removed.** The calibration sync flow
  pushes to a remote D1 backend that has its own (unmigrated) schema.
  After Chunk 1, the local payload's `fileId` field carries a filename
  string instead of an integer id, which the remote will not accept.
  Module compiles against the new schema but is documented as broken
  until calibration is revived as its own iteration.
- **Verification: `make digest` end-to-end.** 1773 active files, 1037
  with signals, 736 without (Chunk 4 territory), top-5 fresh
  high-signal arrivals all rendering correctly with `claude_session_id`
  in the output. `PRAGMA foreign_key_check` empty. `pnpm typecheck`
  for lingo-label clean.

### Chunk 0 — Migration runner (landed 2026-04-08)

- The runner is ~190 lines including argparse + docstrings — the
  "~80 lines" estimate in the design was for the core logic only. The
  CLI surface (`--dry-run`, `--status`, `--db`) doubled the size and
  was worth the cost: dry-run in particular makes Chunks 1, 2, 5
  meaningfully safer to drive interactively.
- **Bootstrapping decision**: `schema_migrations` is created by the
  runner (`ensure_migrations_table`) on every invocation, not by a
  "migration zero" file. The placeholder `00-init.sql` is therefore a
  no-op (`SELECT 1;`) that exists only to exercise the discovery and
  bookkeeping path during verification. It can be deleted once a real
  `01-rename-session-id.sql` exists; nothing depends on its presence.
- **FK enforcement deliberately not turned on by the runner.** Chunk 1
  needs to drop `file_id INTEGER` columns via the rebuild-and-rename
  pattern, which requires `PRAGMA foreign_keys = OFF` for the duration
  of the swap. If the runner forced FK on, every such migration would
  have to fight it. Instead the runner opens a neutral connection and
  each migration manages its own FK state. Application code keeps
  using `db.py::get_connection`, which still enables FK on every
  connection — so production reads/writes are FK-enforced, only
  migration scripts get the freedom.
- **Atomicity model**: each migration's SQL plus its
  `INSERT INTO schema_migrations` row run inside a single
  `with conn:` transaction. A half-applied migration cannot be
  recorded as applied — verified by code path, not yet by injecting a
  failure (deferred until a real migration exists to fail against).
- **Verification on a scratch copy of `corpus.db`**: dry-run reported
  pending → first apply recorded the row → second apply was a no-op
  → status reported `[applied]`. Live `corpus.db` was untouched
  throughout (verified separately).

## Open questions

- Should training-side and MCP-side tables really live in the same SQLite
  file? Splitting would force the consumer separation more cleanly but
  introduces a JOIN-across-databases pattern that SQLite handles via ATTACH
  and is mildly awkward. **Tentative answer**: same file, different prefixes
  or namespaces. Re-evaluate if the training side grows substantially.

## Resolved questions

- ~~How do we handle the lingo-label app's Drizzle schema during migration?~~
  **Resolved 2026-04-08**: db.py (and the migration files it manages) is
  canonical; Drizzle introspects via `pnpm db:pull`. See "Drizzle
  source-of-truth" section above.

- ~~Is `session_id` actually unique in practice?~~
  **Resolved 2026-04-08**: NO. 35 collision groups, 294 duplicate rows, all
  concentrated in `agent-XX` sub-agent runs. Root cause is `claude-extract`
  truncating UUIDs to 8 hex chars (and agent runs even more aggressively).
  Identity strategy revised: use `filename` as interim FK target (already
  unique), then capture full Claude UUIDs from `~/.claude/projects/`
  ourselves and store as `claude_session_id` in a follow-up stage. See
  "Identity strategy" section above.

- ~~Should `calibrate.py` and the calibration backend be in scope?~~
  **Resolved 2026-04-08**: in scope for schema cleanup (FK targets,
  migrations, naming consistency), out of scope for workflow revival. The
  calibration workflow is currently unused and there is no plan to revive
  it within this iteration. Tables get cleaned up alongside everything
  else; the Python modules (`calibrate.py`, `sync.py`) get the minimum
  edits needed to compile against the new schema, but no functional work.
  If calibration is ever revived, treat it as its own iteration.
