# Database Schema

SQLite database for conversation labeling and pattern extraction.

## Tables

### files

Metadata for each conversation file in the corpus.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| filename | TEXT | Unique filename |
| session_id | TEXT | Extracted from filename for stable identity |
| date | TEXT | Date from filename (YYYY-MM-DD) |
| is_agent | BOOLEAN | Agent conversation flag |
| file_size | INTEGER | File size in bytes |
| user_turns | INTEGER | Total user turns |
| claude_turns | INTEGER | Total Claude turns |
| substantive_user_turns | INTEGER | Turns with real content (>10 words, not commands) |
| user_word_count | INTEGER | Total user words |
| claude_word_count | INTEGER | Total Claude words |
| dialogue_density | REAL | user_word_count / user_turns |
| has_command_expansion | BOOLEAN | Contains expanded slash command |
| has_reflective_language | BOOLEAN | Contains reflective patterns |
| source_path | TEXT | Original file location |
| status | TEXT | 'active' \| 'filtered' \| 'pending' |
| imported_at | TEXT | Import timestamp |
| created_at | TEXT | Row creation timestamp |

**Indexes:**
- `idx_files_date` on `date`
- `idx_files_substantive` on `substantive_user_turns`

### labels

Human judgments on conversations or segments.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| file_id | INTEGER | Foreign key → files.id |
| turn_start | INTEGER | Start turn index (NULL = whole conversation) |
| turn_end | INTEGER | End turn index |
| is_rich | BOOLEAN | Rich/not-rich judgment |
| notes | TEXT | Annotation explaining judgment |
| created_at | TEXT | Timestamp |

**Indexes:**
- `idx_labels_file` on `file_id`

**Idempotency:** Labels are upserted based on (file_id, turn_start, turn_end). Re-labeling the same segment updates the existing label.

### markers

Emergent vocabulary of epistemic patterns.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| name | TEXT | Unique marker name (e.g., "framing-before-solving") |
| description | TEXT | What this pattern looks like |
| created_at | TEXT | Timestamp |

**Idempotency:** Markers are upserted by name. Adding an existing marker returns its ID.

### examples

Concrete excerpts linked to markers.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| marker_id | INTEGER | Foreign key → markers.id |
| file_id | INTEGER | Foreign key → files.id |
| turn_start | INTEGER | Start turn index |
| turn_end | INTEGER | End turn index |
| excerpt | TEXT | The actual text excerpt |
| notes | TEXT | Why this exemplifies the marker |
| created_at | TEXT | Timestamp |

**Indexes:**
- `idx_examples_marker` on `marker_id`

## Relationships

```
files ──────┬──────────────── labels
            │
            └──────────────── examples ──── markers
```

- A file can have multiple labels (different segments)
- A file can have multiple examples (different patterns found)
- A marker can have multiple examples (evidence from various conversations)
- Examples link markers to specific file segments

## Key Queries

### Unlabeled files (for labeling queue)

```sql
SELECT f.* FROM files f
LEFT JOIN labels l ON f.id = l.file_id
WHERE l.id IS NULL
ORDER BY f.substantive_user_turns DESC
```

### Rich files

```sql
SELECT f.* FROM files f
JOIN labels l ON f.id = l.file_id
WHERE l.is_rich = 1
```

### Examples for a marker

```sql
SELECT e.*, f.filename
FROM examples e
JOIN files f ON e.file_id = f.id
WHERE e.marker_id = ?
```

### Corpus statistics

```sql
SELECT 
    COUNT(*) as total_files,
    SUM(user_word_count) as total_user_words,
    SUM(claude_word_count) as total_claude_words
FROM files
```

### Status breakdown

```sql
SELECT status, COUNT(*) 
FROM files 
GROUP BY status
```

## Python API

```python
from python.qino_lingo.db import (
    init_db,           # Create schema
    import_metadata,   # JSON → database
    get_file,          # By filename
    get_unlabeled_files,
    get_files_by_criteria,
    add_label,         # Idempotent
    get_labels,
    get_rich_files,
    add_marker,        # Idempotent
    get_markers,
    add_example,
    get_examples_for_marker,
    update_file_status,
    get_files_by_status,
    get_pending_files,
    get_stats,
)
```

All functions accept optional `db_path` parameter (default: `corpus.db`).
