# Architecture

Technical architecture for the epistemological signature extraction pipeline.

qino-lingo's `corpus.db` serves two consumers: the historical labeling
workflow (`lingo-label`, `calibrate.py`, `characterize.py`) and the MCP
server that surfaces conversations for metalogue sourcing, deck composition,
and other downstream work. See `docs/schema.md` for the consumer matrix and
the full per-table reference.

## Overview — the `make ingest` pipeline

```
┌──────────────────────────────────────────────────────────────────────────┐
│                              Data Flow                                    │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  Phase 1 Pull    Phase 1.5 Backup    Phase 2 Index      Phase 3 Enrich   │
│  ─────────────►  ────────────────►   ───────────────►   ───────────────► │
│  claude-extract  sqlite3 .backup     filter_noise       signals.compute   │
│  filter + dedup  sha256 manifest     extract_metadata   (MCP discovery    │
│  copy into       rotate backups      import_metadata    surface)          │
│  data/corpus/                                                             │
│                                                                           │
│  Sources         backups/            corpus.db          conversation_     │
│  ~/.claude/      *.db + .manifest    files (UPSERT)     signals table     │
│  .projects/                          filter_noise       + status writes   │
│                                      sets status='noise'                  │
└──────────────────────────────────────────────────────────────────────────┘
```

Every phase after the first is idempotent: re-running `make ingest` against
an unchanged `~/.claude/projects/` is a no-op aside from the backup itself
(which always snapshots the current state). See
`docs/ingestion-routine.md` for the full routine spec.

## Components

### 0. Conversation Extraction (ingest_conversations.py)

Pulls conversations from Claude Code's local storage (`~/.claude/projects/`).

Depends on [claude-conversation-extractor](https://github.com/ZeroSumQuant/claude-conversation-extractor):
```bash
pipx install claude-conversation-extractor
```

Key features:
- Extracts from configured project folders (see `INCLUDE_FOLDERS`)
- Deduplicates by session ID against existing corpus
- Handles truncated session IDs (UUID first segment, agent prefixes)
- Runs full pipeline after extraction

### 1. Conversation Files (data/corpus/)

Raw exports from Claude Code CLI. Format:

```markdown
# Claude Conversation

**System:** ...
**Session ID:** abc123

---

## 👤 User

User message here

---

## 🤖 Claude

Claude response here

---
```

Key properties:
- Filename: `claude-conversation-YYYY-MM-DD-{session_id}.md`
- Contains system prompt, session metadata, and turn-by-turn dialogue
- May include command expansion (large system prompts from slash commands)

### 2. Noise Filtering (filter_noise.py)

Sets `files.status = 'noise'` on rows matching any of the regex-based
criteria below. Does **not** move files anywhere on disk —
`data/corpus/` is flat; `status` is the single source of truth for
"where does this file belong in the pipeline." See `docs/schema.md`
for the full status enum semantics.

| Criterion | Description |
|-----------|-------------|
| Empty sessions | <1KB, no Claude response |
| Command-only | Just /clear or /exit |
| Agent warmup | Agent sessions with no substantive exchange |
| No substantive input | Commands only, no real user text |
| Pure transactional | Only commit/update operations, no conceptual exchange |

Idempotent: walks the current `status='active'` subset on every run and
reclassifies matches. Safe to re-run. `--dry-run` available for preview.

### 3. Metadata Extraction (extract_metadata.py)

Extracts quantitative signals from each file:

```python
{
    "filename": "claude-conversation-2025-12-15-abc123.md",
    "date": "2025-12-15",
    "is_agent": false,
    "file_size": 45230,
    "user_turns": 12,
    "claude_turns": 11,
    "substantive_user_turns": 8,
    "user_word_count": 1250,
    "claude_word_count": 3400,
    "dialogue_density": 104.2,
    "exchange_ratio": 1.09,
    "has_command_expansion": false,
    "has_reflective_language": true
}
```

**Reflective language patterns** detected:
- "i've been thinking"
- "what makes/does/is..."
- "how can/do/should..."
- "the essence of"
- "i wonder"
- "this feels like"

### 4. Database (python/qino_lingo/db.py + migrations/)

SQLite database with 12 tables serving two consumer groups (shared / mcp /
training). The schema is owned by `python/qino_lingo/migrations/*.sql` —
all changes go through the numbered migration runner (`make migrate`),
never via inline `CREATE TABLE IF NOT EXISTS` in application code.

Key identity and status conventions:

- **FK target is `files.filename`**, not `files.id`. The legacy autoincrement
  PK still exists but no longer participates in cross-table FKs.
- **`PRAGMA foreign_keys = ON`** is required on every connection; both
  `db.py::get_connection` and the lingo-label Drizzle connection enable it.
- **`files.status`** is a CHECK-constrained enum (`active | noise | empty
  | missing`) and is the single source of truth for pipeline state.

See `docs/schema.md` for the full per-table reference, consumer matrix,
identity strategy, and the empty ↔ active promotion rule that makes signal
coverage recoverable across algorithm bumps.

### 5. Parser (python/qino_lingo/parser.py)

Transforms markdown files into structured Python objects:

```python
@dataclass
class Turn:
    role: str           # 'user' or 'assistant'
    content: str
    index: int
    word_count: int
    is_command: bool
    is_command_expansion: bool
    has_substantive_content: bool

@dataclass
class Conversation:
    filename: str
    session_id: str
    date: Optional[str]
    turns: List[Turn]
```

Key methods:
- `parse_conversation(filepath)` → `Conversation`
- `parse_all_conversations(directory)` → `List[Conversation]`

### 6. Sampler (python/qino_lingo/sampler.py)

Stratified sampling for diverse labeling:

| Stratum | Condition |
|---------|-----------|
| high_engagement | ≥10 substantive turns |
| medium_engagement | 3-9 substantive turns |
| low_engagement | 1-2 substantive turns |
| reflective | has reflective language markers |
| high_density | >100 words per turn |
| agent_sessions | agent conversation with content |

Functions:
- `sample_random(n)` — pure random
- `sample_stratified(n_per_stratum)` — from each stratum
- `sample_top_candidates(n)` — ranked by engagement signals
- `get_labeling_progress()` — statistics

## Data Flow for Labeling

```
1. sample_stratified()      → Select diverse unlabeled files
2. parse_conversation()     → Load full content
3. [Human reviews]          → Read, judge, annotate
4. add_label()              → Store judgment
5. add_marker() + add_example()  → Store emergent patterns
```

## Continuous Ingestion

New conversations are pulled from Claude Code's local storage via the
`make ingest` routine. Prefer `make ingest` over calling the script
directly so that Phase 1.5 (backup) always runs before any db mutation.

```bash
make ingest           # Full pipeline + backup + digest
make ingest-recent    # Only last 20 sessions (fast iteration)
make verify           # Dry-run preview, no writes
```

The `ingest_conversations.py` script:

1. Uses [claude-conversation-extractor](https://github.com/ZeroSumQuant/claude-conversation-extractor) to export from `~/.claude/projects/`
2. Filters to configured project folders (see `INCLUDE_FOLDERS` in script)
3. Deduplicates by filename against the existing corpus
4. **Phase 1.5** — takes a transactional backup of `corpus.db` plus a sha256 manifest of `data/corpus/` via `python/qino_lingo/backup.py` (with `--tag pre-ingest`), and refuses to proceed if the backup fails
5. Runs Phase 2: `filter_noise.py` → `extract_metadata.py` → `import_metadata`
6. Runs Phase 3: `signals.compute_all(since=<oldest_new_file_date>)` so newly-ingested files are immediately visible to the MCP discovery tools
7. Prints a digest of corpus state + top fresh high-signal arrivals

Schema supports incremental import via:

- `filename` — stable natural key (FK target for all dependent tables)
- `claude_session_id` — advisory identifier (collision-prone; see `docs/schema.md`)
- `source_path` — original file location at time of ingest
- `status` — `active | noise | empty | missing` (see `docs/schema.md`)
- `imported_at` — timestamp

## Labeling UI

The labeling interface is at `apps/lingo-label/`:

- TanStack Start with server functions
- Keyboard-driven interface for rapid labeling
- Turn-level selection and marking
- Noise prediction overlay from the noise-filter model
- `corpus.db` shared directly with the Python side via Drizzle ORM;
  the schema lives in `src/server/schema.ts` as a hand-maintained
  mirror of the canonical `python/qino_lingo/migrations/*.sql` files

## Future Components

### Pattern Detection

- Embeddings for similarity to "rich" samples
- Claude analysis to propose markers
- Semi-automated candidate surfacing

### Fine-Tuning Pipeline

- Export labeled data to Hugging Face Dataset format
- TRL for SFT/DPO training
- Push models to Hub for deployment via Ollama
