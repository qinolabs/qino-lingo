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
- [ ] Migration 01: rename `files.session_id` → `files.claude_session_id`
      (truncated form, kept for now). Update Python and Drizzle reads.
- [ ] Migration 02: add `filename TEXT NOT NULL` to every dependent table
      (`conversation_signals`, `noise_predictions`, `pending_labels`,
      `calibration_items`, `labels`, `examples`)
- [ ] Migration 03: backfill new `filename` columns by joining through
      current `file_id` (post-heal, all live data is reachable)
- [ ] Migration 04: add new FK declarations on `filename`, drop old
      `file_id INTEGER` columns
- [ ] Update `signals.py::store_signals` to use proper UPSERT and to write
      `filename` instead of `file_id`
- [ ] Update `mcp-server/server.py` queries to join on `filename`
- [ ] Update `lingo-label` Drizzle schema (regenerate via `pnpm db:pull`)

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
- [ ] Migration 08: extend `files.status` enum to include
      `active | noise | empty | missing`. Backfill from `_noise/` directory.
- [ ] Move `_noise/` files back into `data/corpus/`, set status='noise'
- [ ] Update `filter_noise.py` to set status instead of moving files
- [ ] Update `signals.py::compute_all` to query db by status instead of
      globbing `data/corpus/`
- [ ] Update `mcp-server/server.py` to filter by status
- [ ] Remove `_noise/` directory entirely

**Backup overhaul**
- [ ] Replace `backup-corpus.sh` with `python/qino_lingo/backup.py` using
      SQLite's transactional `.backup` API
- [ ] Add manifest of `data/corpus/` (filename + sha256, no content) to the
      backup directory
- [ ] Backup script reports counts for new tables (signals, annotations)
- [ ] Add `make backup` to Makefile
- [ ] `make ingest` runs backup automatically before destructive db work

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
