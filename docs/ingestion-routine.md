# Ingestion Routine

How new Claude conversations get into the corpus, and how to do it on purpose.

## When to run

Run **`make ingest`** at the start of any session that will use the corpus —
metalogue sourcing, lingo exploration, MCP-backed conversation discovery, or
any other reach into `corpus.db`.

The routine is designed around encounter, not background sync. There is no
cron, no scheduled `/loop`. The act of typing `make ingest` is the moment of
attention: you turn toward the corpus, you see what arrived, you start
working. If you don't have corpus work to do, don't run it.

## What it does

```
make ingest
  │
  ├─ Phase 1 — Pull
  │   claude-extract → temp dir
  │   filter to qinolabs* projects
  │   dedupe against data/corpus/ (flat after Chunk 2)
  │   copy new files into data/corpus/
  │   update .ingest_state.json
  │
  ├─ Phase 1.5 — Backup
  │   sqlite3 .backup() → backups/corpus-TIMESTAMP-pre-ingest.db
  │   write sha256 manifest of data/corpus/
  │   rotate (last 10 + one per ISO week for 8 weeks)
  │   refuses to continue if backup fails
  │
  ├─ Phase 2 — Index
  │   filter_noise.py     → sets status='noise' on matching db rows
  │   extract_metadata.py → writes metadata.json
  │   import_metadata()   → upserts into files table
  │
  ├─ Phase 3 — Enrich
  │   signals.compute_all(since=<oldest_new_file_date>)
  │      → conversation_signals table populated for new files
  │      → MCP candidates() / read_thinking() can now see them
  │
  └─ Digest
      corpus state + 5 highest-signal arrivals from the last 7 days
```

Phase 1.5 is the only phase that produces something *outside* `data/corpus/`
and `corpus.db` itself: a sidecar `backups/` directory whose contents are
gitignored. The backup uses SQLite's online `.backup()` API rather than `cp`,
so it is safe under concurrent reads/writes and cannot capture a half-written
page. To skip the backup phase (e.g. while reproducing an issue), pass
`--skip-backup`. Don't make a habit of it.

The signals step is the part that earns this routine its existence. Without
it, newly-ingested conversations are invisible to the MCP server's discovery
tools (`candidates`, `read_thinking`, `search(min_concept_density=...)`). Any
entry point that doesn't run signals is incomplete.

## Targets

| Target | What | When |
|---|---|---|
| `make ingest` | Full pipeline + backup + digest | Default. Pre-session. |
| `make ingest-recent` | Last 20 sessions only + full pipeline + digest | Fast iteration during a session, when you know you're only after recent material |
| `make verify` | Dry-run preview, no writes | When you want to see what would be ingested without committing |
| `make digest` | Print corpus digest only | Mid-session check on what's in the db right now |
| `make signals` | Recompute signals for the entire corpus | After upgrading the algorithm version (`signals.py::ALGORITHM_VERSION`) |
| `make stats` | Raw `corpus.db` stats | Quick numerical sanity check |
| `make backup` | Ad-hoc transactional snapshot of `corpus.db` + sha256 manifest of `data/corpus/`, with rotation | Before any manual db surgery (migrations, one-shot data scripts) |
| `make backup-dry` | Plan a backup + rotation without writing anything | Before tweaking `--keep-recent` / `--keep-weekly`, or to see which files would be pruned |

## How to verify success

After `make ingest`, the digest shows four lines that should look right:

```
Active files:    1742    ← went up by the "Copied N files" count from Phase 1
With signals:    1007    ← went up by some fraction of N (not 100%)
Without signals: 735     ← may go up; this is OK (see below)
Latest in db:    2026-04-05
```

**On the "without signals" gap**: this is not a backlog from a missing run.
`analyze_conversation` legitimately returns `None` for files without
substantive user turns (agent-only sessions, terse command-only sessions).
These files exist in `files` but never get a row in `conversation_signals`.
The gap should be roughly *stable as a fraction* across runs — if it spikes
suddenly, something else is wrong.

**On the fresh high-signal list**: the digest surfaces the top 5 conversations
from the last 7 days that have a metalogue score and no `metalogue_verdict`
annotation yet. This is the "what's worth your attention now" view. Empty
list means: nothing new of interest, or you've already annotated everything
recent.

## Troubleshooting

**`claude-extract: command not found`**
Install via `uv tool install claude-conversation-extractor` (or pipx). The
script lives at `~/.local/bin/claude-extract`.

**`No new conversations to import`**
This is normal if you've already ingested today, or if you haven't had any
qino-related Claude Code sessions since the last run. The digest still
prints, so you can confirm corpus state.

**Pipeline errors mid-run**
Re-run `make ingest`. The pipeline is idempotent: filter_noise/metadata/import
run against whatever is currently in `data/corpus/`, and signals use
`INSERT OR REPLACE`. There's no cleanup step needed after a failed run.

**Signals "WARNING: stale" on MCP server startup**
The algorithm version in `signals.py` was bumped but the corpus still has
older signal rows. Run `make signals` to recompute the full corpus. This
takes ~30 seconds for ~1700 files.

**Numbers in the digest look wrong**
`make stats` shows raw `files`/`labels`/`signals` counts straight from the
db with no aggregation. Use it to cross-check the digest against ground truth.

## Why no scheduled `/loop`

Claude Code's `/loop` (backed by `CronCreate`) can run this routine on a
schedule. We're deliberately not using it. Reasoning:

1. The corpus is **material**, not a feed. The right time to ingest is when
   you're about to use it — not at 9:07am whether you wanted to or not.
2. A scheduled digest produces messages whether or not you have attention to
   spend on them. Ambient digests train you to skim them.
3. The 7-day auto-expire on durable cron jobs means it would need weekly
   re-scheduling — friction without benefit, since `make ingest` is itself
   one command.
4. The qino design stance is "encounter over pipeline." This routine should
   feel like opening a library, not subscribing to a newsletter.

If at some point the corpus genuinely becomes a daily reading practice — a
"morning paper" you actually want to read every day independent of any
specific task — then `/loop` is the right shape. Until then, manual.

## Architecture references

- `ingest_conversations.py` — entry point, all phases live here
- `filter_noise.py` — Phase 2 noise filter
- `extract_metadata.py` — Phase 2 metadata extraction
- `python/qino_lingo/db.py::import_metadata` — Phase 2 db upsert
- `python/qino_lingo/signals.py::compute_all` — Phase 3 signal computation
- `python/qino_lingo/backup.py` — Phase 1.5 transactional backup runner
- `mcp-server/server.py` — the consumer that depends on Phase 3 freshness
- `docs/mcp-server-evolution.md` — why the MCP server now needs signals at all
