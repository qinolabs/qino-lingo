# Architecture

Technical architecture for the epistemological signature extraction pipeline.

## Overview

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              Data Flow                                        │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  Claude Code      Extraction       Filtering       Metadata       Database   │
│  Storage       ─────────────►   ──────────────►  ──────────────►  ─────────► │
│  (~/.claude/)    (ingest_*)      (noise removal)  (extraction)    (SQLite)   │
│                                                                               │
│  JSONL files     corpus/         corpus/_noise/   metadata.json   corpus.db  │
│  ~2000 sessions  ~1000 files                      JSON array      4 tables   │
└──────────────────────────────────────────────────────────────────────────────┘
```

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

### 1. Conversation Files (corpus/)

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

Moves obviously non-rich files to `corpus/_noise/`:

| Criterion | Description |
|-----------|-------------|
| Empty sessions | <1KB, no Claude response |
| Command-only | Just /clear or /exit |
| Agent warmup | Agent sessions with no substantive exchange |
| No substantive input | Commands only, no real user text |
| Pure transactional | Only commit/update operations, no conceptual exchange |

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

### 4. Database (lib/db.py)

SQLite database with four tables. See `docs/schema.md` for details.

### 5. Parser (lib/parser.py)

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

### 6. Sampler (lib/sampler.py)

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

New conversations are ingested automatically from Claude Code's local storage:

```bash
# Full sync — extracts all new conversations
python3 ingest_conversations.py

# Quick update — only last N sessions
python3 ingest_conversations.py --recent 20

# Preview changes
python3 ingest_conversations.py --dry-run
```

The `ingest_conversations.py` script:
1. Uses [claude-conversation-extractor](https://github.com/ZeroSumQuant/claude-conversation-extractor) to export from `~/.claude/projects/`
2. Filters to configured project folders (see `INCLUDE_FOLDERS` in script)
3. Deduplicates by session ID against existing corpus
4. Runs the pipeline: `filter_noise.py` → `extract_metadata.py` → DB import

Schema supports incremental import via:
- `session_id` — stable identity from filename
- `source_path` — original file location
- `status` — active | filtered | pending
- `imported_at` — timestamp

## Future Components

### Labeling UI (planned)

React app in qinolabs-repo:
- FastAPI server exposing db operations
- Keyboard-driven interface for rapid labeling
- Split-view: conversation | annotation
- Marker management

### Pattern Detection (eventual)

- Embeddings for similarity to "rich" samples
- Claude analysis to propose markers
- Semi-automated candidate surfacing

### Fine-Tuning Pipeline (eventual)

- Format labeled data for training
- Anthropic API or alternatives
