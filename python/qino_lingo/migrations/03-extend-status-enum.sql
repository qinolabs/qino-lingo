-- 03-extend-status-enum.sql
--
-- Add a CHECK constraint to files.status to enforce the post-Chunk-2
-- enum: 'active' | 'noise' | 'empty' | 'missing'.
--
-- Why: before this iteration, filter_noise.py moved files into
-- data/corpus/_noise/ without ever updating the db. The result was
-- ~340 db rows whose filename pointed at files physically in _noise/
-- but whose status column said 'active'. The status column was
-- effectively a comment that everyone ignored.
--
-- Chunk 2 collapses the filesystem-as-noise-marker pattern into the
-- status column as the single source of truth. This migration is the
-- schema half — it adds the CHECK constraint that defines the legal
-- values. The data half (UPDATE + INSERT for the orphans) lives in
-- python/qino_lingo/collapse_noise.py because it depends on
-- filesystem state and ingesting orphan files needs metadata
-- extraction.
--
-- Status semantics after Chunk 2:
--   'active'  — file is in data/corpus/, has substantive content,
--               eligible for signals computation and consumer queries
--   'noise'   — filter_noise.py classified it as noise; file still
--               lives in data/corpus/ (no longer moved to _noise/),
--               excluded from signals computation and most queries
--   'empty'   — has no substantive user turns; signals legitimately
--               cannot be computed (signals.py::analyze_conversation
--               returns None for these). Reserved for Chunk 4 use.
--   'missing' — db row exists but markdown file is gone. Reserved
--               for Chunk 4's `make doctor` to set when reconciling.
--
-- SQLite cannot add a CHECK constraint to an existing table in place;
-- the workaround is the same rebuild-and-rename pattern Chunk 1 used.
-- Wrap the whole thing inside PRAGMA foreign_keys = OFF since the
-- dependent tables FK to files(filename); the FK target survives the
-- rename because the new table has the same column name.

PRAGMA foreign_keys = OFF;

CREATE TABLE files_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT UNIQUE NOT NULL,
    claude_session_id TEXT,
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
    source_path TEXT,
    status TEXT DEFAULT 'active'
        CHECK (status IN ('active', 'noise', 'empty', 'missing')),
    imported_at TEXT DEFAULT CURRENT_TIMESTAMP,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO files_new
SELECT * FROM files;

DROP TABLE files;
ALTER TABLE files_new RENAME TO files;

CREATE INDEX idx_files_date ON files(date);
CREATE INDEX idx_files_substantive ON files(substantive_user_turns);
CREATE INDEX idx_files_claude_session ON files(claude_session_id);
CREATE INDEX idx_files_status ON files(status);

-- Re-enable FK enforcement and verify dependent FKs still resolve.
-- Every dependent table FKs to files(filename); the column survived
-- the rebuild with the same name and uniqueness, so foreign_key_check
-- should report empty.
PRAGMA foreign_keys = ON;
PRAGMA foreign_key_check;
