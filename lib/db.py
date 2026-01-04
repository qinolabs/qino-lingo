"""
Database operations for the epistemological signature project.
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any
from contextlib import contextmanager

DEFAULT_DB_PATH = Path(__file__).parent.parent / "corpus.db"


@contextmanager
def get_connection(db_path: Path = DEFAULT_DB_PATH):
    """Context manager for database connections."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path = DEFAULT_DB_PATH):
    """Initialize the database schema."""
    with get_connection(db_path) as conn:
        conn.executescript("""
            -- Files table: one row per conversation file
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT UNIQUE NOT NULL,
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
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            -- Labels table: human judgments on conversation segments
            CREATE TABLE IF NOT EXISTS labels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id INTEGER NOT NULL,
                turn_start INTEGER,  -- NULL means whole conversation
                turn_end INTEGER,
                is_rich BOOLEAN NOT NULL,
                notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (file_id) REFERENCES files(id)
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
                file_id INTEGER NOT NULL,
                turn_start INTEGER,
                turn_end INTEGER,
                excerpt TEXT,
                notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (marker_id) REFERENCES markers(id),
                FOREIGN KEY (file_id) REFERENCES files(id)
            );

            -- Create indexes for common queries
            CREATE INDEX IF NOT EXISTS idx_files_date ON files(date);
            CREATE INDEX IF NOT EXISTS idx_files_substantive ON files(substantive_user_turns);
            CREATE INDEX IF NOT EXISTS idx_labels_file ON labels(file_id);
            CREATE INDEX IF NOT EXISTS idx_examples_marker ON examples(marker_id);
        """)


def import_metadata(metadata_path: Path, db_path: Path = DEFAULT_DB_PATH):
    """Import metadata from JSON into the database."""
    with open(metadata_path) as f:
        metadata = json.load(f)

    with get_connection(db_path) as conn:
        for m in metadata:
            conn.execute("""
                INSERT OR REPLACE INTO files (
                    filename, date, is_agent, file_size,
                    user_turns, claude_turns, substantive_user_turns,
                    user_word_count, claude_word_count, dialogue_density,
                    has_command_expansion, has_reflective_language
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                m['filename'], m['date'], m['is_agent'], m['file_size'],
                m['user_turns'], m['claude_turns'], m['substantive_user_turns'],
                m['user_word_count'], m['claude_word_count'], m['dialogue_density'],
                m['has_command_expansion'], m['has_reflective_language']
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
            LEFT JOIN labels l ON f.id = l.file_id
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
    file_id: int,
    is_rich: bool,
    notes: str = "",
    turn_start: Optional[int] = None,
    turn_end: Optional[int] = None,
    db_path: Path = DEFAULT_DB_PATH
) -> int:
    """Add a label for a file or segment."""
    with get_connection(db_path) as conn:
        cursor = conn.execute("""
            INSERT INTO labels (file_id, turn_start, turn_end, is_rich, notes)
            VALUES (?, ?, ?, ?, ?)
        """, (file_id, turn_start, turn_end, is_rich, notes))
        return cursor.lastrowid


def get_labels(db_path: Path = DEFAULT_DB_PATH) -> List[Dict]:
    """Get all labels with file info."""
    with get_connection(db_path) as conn:
        rows = conn.execute("""
            SELECT l.*, f.filename, f.user_word_count
            FROM labels l
            JOIN files f ON l.file_id = f.id
            ORDER BY l.created_at DESC
        """).fetchall()
        return [dict(r) for r in rows]


def get_rich_files(db_path: Path = DEFAULT_DB_PATH) -> List[Dict]:
    """Get files labeled as rich."""
    with get_connection(db_path) as conn:
        rows = conn.execute("""
            SELECT f.* FROM files f
            JOIN labels l ON f.id = l.file_id
            WHERE l.is_rich = 1
        """).fetchall()
        return [dict(r) for r in rows]


# --- Marker operations ---

def add_marker(name: str, description: str = "", db_path: Path = DEFAULT_DB_PATH) -> int:
    """Add a new marker to the vocabulary."""
    with get_connection(db_path) as conn:
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
    file_id: int,
    excerpt: str,
    notes: str = "",
    turn_start: Optional[int] = None,
    turn_end: Optional[int] = None,
    db_path: Path = DEFAULT_DB_PATH
) -> int:
    """Add an example for a marker."""
    with get_connection(db_path) as conn:
        cursor = conn.execute("""
            INSERT INTO examples (marker_id, file_id, turn_start, turn_end, excerpt, notes)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (marker_id, file_id, turn_start, turn_end, excerpt, notes))
        return cursor.lastrowid


def get_examples_for_marker(marker_id: int, db_path: Path = DEFAULT_DB_PATH) -> List[Dict]:
    """Get all examples for a marker."""
    with get_connection(db_path) as conn:
        rows = conn.execute("""
            SELECT e.*, f.filename
            FROM examples e
            JOIN files f ON e.file_id = f.id
            WHERE e.marker_id = ?
        """, (marker_id,)).fetchall()
        return [dict(r) for r in rows]


# --- Statistics ---

def get_stats(db_path: Path = DEFAULT_DB_PATH) -> Dict[str, Any]:
    """Get corpus statistics."""
    with get_connection(db_path) as conn:
        stats = {}

        # File counts
        stats['total_files'] = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        stats['labeled_files'] = conn.execute(
            "SELECT COUNT(DISTINCT file_id) FROM labels"
        ).fetchone()[0]
        stats['rich_files'] = conn.execute(
            "SELECT COUNT(DISTINCT file_id) FROM labels WHERE is_rich = 1"
        ).fetchone()[0]

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
