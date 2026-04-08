"""
Database operations for the epistemological signature project.
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any
from contextlib import contextmanager

DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "corpus.db"


@contextmanager
def get_connection(db_path: Path = DEFAULT_DB_PATH):
    """Context manager for database connections.

    Foreign key enforcement is enabled per-connection (SQLite requires this
    to be set on every connection — schema FK declarations alone are not
    enforced). Without this, deletes/replaces silently orphan dependent rows.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path = DEFAULT_DB_PATH):
    """Initialize the database schema.

    NOTE: as of Chunk 0 the canonical schema lives in
    python/qino_lingo/migrations/. This function is retained for backwards
    compatibility with any callers that previously initialized a fresh
    db, but new schema work should be done as a numbered migration. The
    DDL below is kept in sync with the post-Chunk-1 schema (filename as
    FK target, claude_session_id as renamed identity column).
    """
    with get_connection(db_path) as conn:
        conn.executescript("""
            -- Files table: one row per conversation file
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT UNIQUE NOT NULL,
                claude_session_id TEXT,  -- truncated id from claude-extract; collision-prone, see Stage B
                date TEXT,
                is_agent BOOLEAN,
                file_size INTEGER,
                user_turns INTEGER,
                claude_turns INTEGER,
                substantive_user_turns INTEGER,
                user_word_count INTEGER,
                claude_word_count INTEGER,
                dialogue_density REAL,
                has_command_expansion BOOLEAN,
                has_reflective_language BOOLEAN,
                source_path TEXT,  -- original file location
                status TEXT DEFAULT 'active',  -- active | filtered | pending
                imported_at TEXT DEFAULT CURRENT_TIMESTAMP,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            -- Labels table: human judgments on conversation segments
            CREATE TABLE IF NOT EXISTS labels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                turn_start INTEGER,  -- NULL means whole conversation
                turn_end INTEGER,
                rating INTEGER NOT NULL,  -- 1=thin, 2=functional, 3=rich
                tags TEXT,  -- JSON array of secondary tags
                notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (filename) REFERENCES files(filename)
                    ON UPDATE CASCADE
            );

            -- Markers table: emergent vocabulary of epistemic patterns
            CREATE TABLE IF NOT EXISTS markers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            -- Examples table: links markers to specific conversation excerpts
            CREATE TABLE IF NOT EXISTS examples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                marker_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                turn_start INTEGER,
                turn_end INTEGER,
                excerpt TEXT,
                notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (marker_id) REFERENCES markers(id),
                FOREIGN KEY (filename) REFERENCES files(filename)
                    ON UPDATE CASCADE
            );

            -- Create indexes for common queries
            CREATE INDEX IF NOT EXISTS idx_files_date ON files(date);
            CREATE INDEX IF NOT EXISTS idx_files_substantive ON files(substantive_user_turns);
            CREATE INDEX IF NOT EXISTS idx_labels_filename ON labels(filename);
            CREATE INDEX IF NOT EXISTS idx_examples_marker ON examples(marker_id);
            CREATE INDEX IF NOT EXISTS idx_examples_filename ON examples(filename);
        """)


def extract_claude_session_id(filename: str) -> Optional[str]:
    """Extract the truncated Claude session id from a corpus filename.

    Filename format: claude-conversation-YYYY-MM-DD-XXXXXXXX.md
    Returned id: the suffix after the date (the 8-hex truncation that
    claude-extract emits, or `agent-XX` for sub-agent runs).

    NOTE: this is collision-prone. 35 collision groups exist in the
    current corpus (~294 duplicate rows). Stage B captures the full
    Claude UUID at ingestion time and stores it separately. For now,
    `filename` is the only stable identifier — `claude_session_id` is
    a description, not a key.
    """
    import re
    match = re.search(r'\d{4}-\d{2}-\d{2}-(.+)\.md$', filename)
    return match.group(1) if match else None


def import_metadata(
    metadata_path: Path,
    source_dir: Optional[Path] = None,
    db_path: Path = DEFAULT_DB_PATH
):
    """Import metadata from JSON into the database.

    Args:
        metadata_path: Path to metadata.json
        source_dir: Original directory where files came from (for source_path)
        db_path: Database path
    """
    with open(metadata_path) as f:
        metadata = json.load(f)

    with get_connection(db_path) as conn:
        for m in metadata:
            claude_session_id = extract_claude_session_id(m['filename'])
            source_path = str(source_dir / m['filename']) if source_dir else None

            # Proper UPSERT — preserves the parent row's identity across
            # re-imports. After Chunk 1, dependent tables FK on
            # files.filename (a content-derived natural key), so even an
            # INSERT OR REPLACE regression couldn't orphan rows; but the
            # UPSERT remains the correct ingestion pattern because it
            # avoids triggering FK constraint errors and preserves the
            # parent row's full state across re-imports.
            conn.execute("""
                INSERT INTO files (
                    filename, claude_session_id, date, is_agent, file_size,
                    user_turns, claude_turns, substantive_user_turns,
                    user_word_count, claude_word_count, dialogue_density,
                    has_command_expansion, has_reflective_language,
                    source_path, status, imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', CURRENT_TIMESTAMP)
                ON CONFLICT(filename) DO UPDATE SET
                    claude_session_id = excluded.claude_session_id,
                    date = excluded.date,
                    is_agent = excluded.is_agent,
                    file_size = excluded.file_size,
                    user_turns = excluded.user_turns,
                    claude_turns = excluded.claude_turns,
                    substantive_user_turns = excluded.substantive_user_turns,
                    user_word_count = excluded.user_word_count,
                    claude_word_count = excluded.claude_word_count,
                    dialogue_density = excluded.dialogue_density,
                    has_command_expansion = excluded.has_command_expansion,
                    has_reflective_language = excluded.has_reflective_language,
                    source_path = excluded.source_path,
                    imported_at = CURRENT_TIMESTAMP
            """, (
                m['filename'], claude_session_id, m['date'], m['is_agent'], m['file_size'],
                m['user_turns'], m['claude_turns'], m['substantive_user_turns'],
                m['user_word_count'], m['claude_word_count'], m['dialogue_density'],
                m['has_command_expansion'], m['has_reflective_language'],
                source_path
            ))

    return len(metadata)


# --- File queries ---

def get_file(filename: str, db_path: Path = DEFAULT_DB_PATH) -> Optional[Dict]:
    """Get a file by filename."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM files WHERE filename = ?", (filename,)
        ).fetchone()
        return dict(row) if row else None


def get_unlabeled_files(db_path: Path = DEFAULT_DB_PATH) -> List[Dict]:
    """Get files that haven't been labeled yet."""
    with get_connection(db_path) as conn:
        rows = conn.execute("""
            SELECT f.* FROM files f
            LEFT JOIN labels l ON f.filename = l.filename
            WHERE l.id IS NULL
            ORDER BY f.substantive_user_turns DESC
        """).fetchall()
        return [dict(r) for r in rows]


def get_files_by_criteria(
    min_substantive_turns: int = 0,
    has_reflective: Optional[bool] = None,
    min_user_words: int = 0,
    db_path: Path = DEFAULT_DB_PATH
) -> List[Dict]:
    """Get files matching criteria."""
    query = "SELECT * FROM files WHERE substantive_user_turns >= ? AND user_word_count >= ?"
    params = [min_substantive_turns, min_user_words]

    if has_reflective is not None:
        query += " AND has_reflective_language = ?"
        params.append(has_reflective)

    query += " ORDER BY user_word_count DESC"

    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


# --- Label operations ---

def add_label(
    filename: str,
    rating: int,
    tags: Optional[List[str]] = None,
    notes: str = "",
    turn_start: Optional[int] = None,
    turn_end: Optional[int] = None,
    db_path: Path = DEFAULT_DB_PATH
) -> int:
    """Add a label for a file or segment. Idempotent — updates if exists.

    Args:
        filename: Conversation filename (FK target after Chunk 1)
        rating: 1=thin, 2=functional, 3=rich
        tags: Optional list of secondary tags
        notes: Optional notes
        turn_start: Start turn (None means whole conversation)
        turn_end: End turn
        db_path: Database path
    """
    tags_json = json.dumps(tags) if tags else None

    with get_connection(db_path) as conn:
        # Check if label exists for this file/segment
        existing = conn.execute("""
            SELECT id FROM labels
            WHERE filename = ? AND turn_start IS ? AND turn_end IS ?
        """, (filename, turn_start, turn_end)).fetchone()

        if existing:
            # Update existing label
            conn.execute("""
                UPDATE labels SET rating = ?, tags = ?, notes = ?, created_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (rating, tags_json, notes, existing[0]))
            return existing[0]

        cursor = conn.execute("""
            INSERT INTO labels (filename, turn_start, turn_end, rating, tags, notes)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (filename, turn_start, turn_end, rating, tags_json, notes))
        return cursor.lastrowid


def get_labels(db_path: Path = DEFAULT_DB_PATH) -> List[Dict]:
    """Get all labels with file info."""
    with get_connection(db_path) as conn:
        rows = conn.execute("""
            SELECT l.*, f.user_word_count
            FROM labels l
            JOIN files f ON l.filename = f.filename
            ORDER BY l.created_at DESC
        """).fetchall()
        return [dict(r) for r in rows]


def get_rich_files(db_path: Path = DEFAULT_DB_PATH) -> List[Dict]:
    """Get files labeled as rich (rating = 3)."""
    with get_connection(db_path) as conn:
        rows = conn.execute("""
            SELECT f.* FROM files f
            JOIN labels l ON f.filename = l.filename
            WHERE l.rating = 3
        """).fetchall()
        return [dict(r) for r in rows]


def get_files_by_rating(
    rating: int,
    db_path: Path = DEFAULT_DB_PATH
) -> List[Dict]:
    """Get files with a specific rating (1=thin, 2=functional, 3=rich)."""
    with get_connection(db_path) as conn:
        rows = conn.execute("""
            SELECT f.* FROM files f
            JOIN labels l ON f.filename = l.filename
            WHERE l.rating = ?
        """, (rating,)).fetchall()
        return [dict(r) for r in rows]


# --- Marker operations ---

def add_marker(name: str, description: str = "", db_path: Path = DEFAULT_DB_PATH) -> int:
    """Add a new marker to the vocabulary. Idempotent — returns existing if name exists."""
    with get_connection(db_path) as conn:
        # Check if exists
        existing = conn.execute(
            "SELECT id FROM markers WHERE name = ?", (name,)
        ).fetchone()
        if existing:
            return existing[0]

        cursor = conn.execute("""
            INSERT INTO markers (name, description) VALUES (?, ?)
        """, (name, description))
        return cursor.lastrowid


def get_markers(db_path: Path = DEFAULT_DB_PATH) -> List[Dict]:
    """Get all markers."""
    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM markers ORDER BY name").fetchall()
        return [dict(r) for r in rows]


def add_example(
    marker_id: int,
    filename: str,
    excerpt: str,
    notes: str = "",
    turn_start: Optional[int] = None,
    turn_end: Optional[int] = None,
    db_path: Path = DEFAULT_DB_PATH
) -> int:
    """Add an example for a marker."""
    with get_connection(db_path) as conn:
        cursor = conn.execute("""
            INSERT INTO examples (marker_id, filename, turn_start, turn_end, excerpt, notes)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (marker_id, filename, turn_start, turn_end, excerpt, notes))
        return cursor.lastrowid


def get_examples_for_marker(marker_id: int, db_path: Path = DEFAULT_DB_PATH) -> List[Dict]:
    """Get all examples for a marker."""
    with get_connection(db_path) as conn:
        rows = conn.execute("""
            SELECT e.*
            FROM examples e
            WHERE e.marker_id = ?
        """, (marker_id,)).fetchall()
        return [dict(r) for r in rows]


# --- File status operations ---

def update_file_status(
    filename: str,
    status: str,
    db_path: Path = DEFAULT_DB_PATH
) -> None:
    """Update the status of a file (active, filtered, pending)."""
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE files SET status = ? WHERE filename = ?",
            (status, filename)
        )


def get_files_by_status(
    status: str,
    db_path: Path = DEFAULT_DB_PATH
) -> List[Dict]:
    """Get files by status."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM files WHERE status = ? ORDER BY date DESC",
            (status,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_pending_files(db_path: Path = DEFAULT_DB_PATH) -> List[Dict]:
    """Get files pending review (newly imported)."""
    return get_files_by_status('pending', db_path)


# --- Statistics ---

def get_stats(db_path: Path = DEFAULT_DB_PATH) -> Dict[str, Any]:
    """Get corpus statistics."""
    with get_connection(db_path) as conn:
        stats = {}

        # File counts
        stats['total_files'] = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        stats['labeled_files'] = conn.execute(
            "SELECT COUNT(DISTINCT filename) FROM labels"
        ).fetchone()[0]

        # Rating breakdown (1=thin, 2=functional, 3=rich)
        rating_rows = conn.execute(
            "SELECT rating, COUNT(*) FROM labels GROUP BY rating"
        ).fetchall()
        stats['by_rating'] = {
            row[0]: row[1] for row in rating_rows
        }
        stats['rich_files'] = stats['by_rating'].get(3, 0)
        stats['functional_files'] = stats['by_rating'].get(2, 0)
        stats['thin_files'] = stats['by_rating'].get(1, 0)

        # Status breakdown
        status_rows = conn.execute(
            "SELECT status, COUNT(*) FROM files GROUP BY status"
        ).fetchall()
        stats['by_status'] = dict(status_rows)

        # Marker counts
        stats['total_markers'] = conn.execute("SELECT COUNT(*) FROM markers").fetchone()[0]
        stats['total_examples'] = conn.execute("SELECT COUNT(*) FROM examples").fetchone()[0]

        # Word counts
        row = conn.execute("""
            SELECT SUM(user_word_count), SUM(claude_word_count)
            FROM files
        """).fetchone()
        stats['total_user_words'] = row[0] or 0
        stats['total_claude_words'] = row[1] or 0

        return stats


# --- Annotation operations ---


def add_annotation(
    filename: str,
    kind: str,
    value: Optional[str] = None,
    thread: Optional[str] = None,
    notes: Optional[str] = None,
    exchange_start: Optional[int] = None,
    exchange_end: Optional[int] = None,
    source: str = "human",
    db_path: Path = DEFAULT_DB_PATH,
) -> int:
    """Add an annotation to a conversation.

    Supports whole-conversation (exchange_start/end both None)
    or passage-level (both set) annotations.
    Multiple annotations per conversation are allowed.
    """
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO annotations (
                filename, exchange_start, exchange_end,
                kind, value, thread, notes, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (filename, exchange_start, exchange_end, kind, value, thread, notes, source),
        )
        return cursor.lastrowid


def get_annotations(
    filename: Optional[str] = None,
    kind: Optional[str] = None,
    thread: Optional[str] = None,
    source: Optional[str] = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> List[Dict]:
    """Get annotations, optionally filtered."""
    query = """
        SELECT a.*, f.claude_session_id, f.date
        FROM annotations a
        JOIN files f ON a.filename = f.filename
        WHERE 1=1
    """
    params: list = []

    if filename is not None:
        query += " AND a.filename = ?"
        params.append(filename)
    if kind is not None:
        query += " AND a.kind = ?"
        params.append(kind)
    if thread is not None:
        query += " AND a.thread = ?"
        params.append(thread)
    if source is not None:
        query += " AND a.source = ?"
        params.append(source)

    query += " ORDER BY a.created_at DESC"

    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def update_annotation(
    annotation_id: int,
    value: Optional[str] = None,
    thread: Optional[str] = None,
    notes: Optional[str] = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """Update an existing annotation."""
    updates = []
    params: list = []

    if value is not None:
        updates.append("value = ?")
        params.append(value)
    if thread is not None:
        updates.append("thread = ?")
        params.append(thread)
    if notes is not None:
        updates.append("notes = ?")
        params.append(notes)

    if not updates:
        return

    params.append(annotation_id)
    with get_connection(db_path) as conn:
        conn.execute(
            f"UPDATE annotations SET {', '.join(updates)} WHERE id = ?",
            params,
        )


def get_file_by_session(
    session_id: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> Optional[Dict]:
    """Look up a file by filename (preferred) or claude_session_id (fallback).

    The MCP server's external API still calls this `session_id` for
    backwards compatibility with existing user workflows. Internally,
    inputs ending in `.md` are treated as filenames (the stable, unique
    identifier — preferred); other inputs fall back to claude_session_id
    lookup, which is collision-prone (35 collision groups in current
    corpus, returns first match arbitrarily). Stage B captures full
    Claude UUIDs and removes the collision class entirely.
    """
    with get_connection(db_path) as conn:
        if session_id.endswith('.md'):
            row = conn.execute(
                "SELECT * FROM files WHERE filename = ?", (session_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM files WHERE claude_session_id = ?", (session_id,)
            ).fetchone()
        return dict(row) if row else None
