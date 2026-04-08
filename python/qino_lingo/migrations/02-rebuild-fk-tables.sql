-- 02-rebuild-fk-tables.sql
--
-- Switch the foreign-key target across every dependent table from
-- files.id (autoincrement integer) to files.filename (natural key).
--
-- Why: files.id is fragile. INSERT OR REPLACE INTO files allocates a new
-- id on conflict, silently orphaning every dependent row. Chunk 0 fixed
-- the immediate bleeding by switching ingest to a proper UPSERT, but the
-- structural fragility remains until the FK target itself is content-
-- derived. files.filename is already UNIQUE NOT NULL and verified unique
-- across all 1773 rows; using it as the FK target makes orphaning
-- impossible regardless of upsert pattern. (See 01-holistic-refactor.md
-- "Identity strategy" for the full reasoning, including why we use
-- filename rather than the truncated claude_session_id which has 35
-- collision groups.)
--
-- Pattern: SQLite cannot easily change FK targets in place. The standard
-- workaround is rebuild-and-rename: CREATE TABLE foo_new with the new
-- schema, INSERT ... SELECT joining through the old FK to populate the
-- new column, DROP TABLE foo, ALTER TABLE foo_new RENAME TO foo, then
-- recreate indices. PRAGMA foreign_keys is OFF for the duration so the
-- in-progress rebuild doesn't trip on intermediate states; it's restored
-- to ON at the end. The migration runner wraps the whole thing in a
-- transaction, so either all 7 rebuilds land or none do.
--
-- FK action: ON UPDATE CASCADE, ON DELETE NO ACTION (default).
-- The choice of NO ACTION on delete is deliberate. ON DELETE CASCADE
-- would propagate parent deletes to children, which is exactly the
-- orphaning failure mode we're trying to eliminate (an INSERT OR REPLACE
-- pattern would cascade-delete signals/labels/annotations).
--
-- Combined with the filename-as-FK choice, this gives a stronger
-- guarantee than file_id-as-FK ever could:
--
--  1. INSERT OR REPLACE INTO files (filename='X', ...) works without
--     orphaning. SQLite's FK check is per-statement, not per-operation.
--     At end of statement, every dependent row still has a parent with
--     filename='X' (the new row). The intermediate "delete" inside
--     REPLACE is invisible to the checker. With file_id as FK target
--     this used to break because the new row got a new autoincrement id.
--  2. Proper UPSERT (Chunk 0's ingest pattern) works perfectly — no
--     DELETE involved, FK never trips.
--  3. Explicit DELETE FROM files WHERE ... with dependent rows present:
--     blocked with FK constraint error 19. Correct: forced cleanup.
--  4. DROP TABLE files: still possible (and still destructive) but
--     now an obviously dangerous operation, not a silent ingestion bug.
--
-- The one residual sharp edge is that a partial-column INSERT OR REPLACE
-- can leave the parent in a bad state (un-supplied columns become NULL)
-- while children survive. This is a write-site bug, not a structural
-- one — Chunk 4's `make doctor` would catch it. Chunk 0's UPSERT is the
-- correct ingestion pattern; INSERT OR REPLACE should not appear in
-- production code paths at all.
--
-- ON UPDATE CASCADE is kept defensively so a future filename rename
-- (e.g. normalized casing) propagates correctly to all children.
--
-- Tables rebuilt (with current row counts at write time):
--   conversation_signals (1037 rows) — file_id was INTEGER UNIQUE NOT NULL
--   pending_labels       (4 rows)    — file_id was INTEGER NOT NULL
--   labels               (1 row)     — file_id was INTEGER NOT NULL
--   noise_predictions    (0 rows)    — UNIQUE(file_id, turn_idx)
--   examples             (0 rows)    — file_id was INTEGER NOT NULL
--   annotations          (0 rows)    — file_id was INTEGER NOT NULL
--   calibration_items    (0 rows)    — UNIQUE(round_id, file_id)
--
-- After this migration the entire FK orphaning failure mode is gone
-- structurally. Even an `INSERT OR REPLACE INTO files` regression
-- couldn't reintroduce orphans, because the dependent rows reference
-- the filename string, not an autoincrement id.

PRAGMA foreign_keys = OFF;

-- ============================================================
-- conversation_signals
-- ============================================================
-- file_id INTEGER UNIQUE → filename TEXT UNIQUE
-- The UNIQUE on the FK column matters: one signals row per conversation.

CREATE TABLE conversation_signals_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL UNIQUE,
    metalogue_score INTEGER,
    concept_density REAL,
    reflective_turns INTEGER,
    reflective_words INTEGER,
    rich_turns INTEGER,
    medium_rich_turns INTEGER,
    very_rich_turns INTEGER,
    corrections INTEGER,
    meta_awareness INTEGER,
    cross_diversity INTEGER,
    terse_ratio REAL,
    trajectory_shape TEXT,
    concept_keywords TEXT,
    best_preview TEXT,
    computed_at TEXT DEFAULT CURRENT_TIMESTAMP,
    algorithm_version TEXT,
    FOREIGN KEY (filename) REFERENCES files(filename)
        ON UPDATE CASCADE
);

INSERT INTO conversation_signals_new (
    id, filename, metalogue_score, concept_density,
    reflective_turns, reflective_words,
    rich_turns, medium_rich_turns, very_rich_turns,
    corrections, meta_awareness, cross_diversity,
    terse_ratio, trajectory_shape, concept_keywords,
    best_preview, computed_at, algorithm_version
)
SELECT
    cs.id, f.filename, cs.metalogue_score, cs.concept_density,
    cs.reflective_turns, cs.reflective_words,
    cs.rich_turns, cs.medium_rich_turns, cs.very_rich_turns,
    cs.corrections, cs.meta_awareness, cs.cross_diversity,
    cs.terse_ratio, cs.trajectory_shape, cs.concept_keywords,
    cs.best_preview, cs.computed_at, cs.algorithm_version
FROM conversation_signals cs
JOIN files f ON cs.file_id = f.id;

DROP TABLE conversation_signals;
ALTER TABLE conversation_signals_new RENAME TO conversation_signals;

CREATE INDEX idx_signals_score ON conversation_signals(metalogue_score DESC);
CREATE INDEX idx_signals_filename ON conversation_signals(filename);

-- ============================================================
-- pending_labels
-- ============================================================
-- file_id INTEGER → filename TEXT (no uniqueness — multiple pending
-- labels per file allowed, e.g. different turn ranges)

CREATE TABLE pending_labels_new (
    id INTEGER PRIMARY KEY,
    filename TEXT NOT NULL,
    turn_start INTEGER,
    turn_end INTEGER,
    source TEXT DEFAULT 'manual',
    context TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (filename) REFERENCES files(filename)
        ON UPDATE CASCADE
);

INSERT INTO pending_labels_new (
    id, filename, turn_start, turn_end, source, context, created_at
)
SELECT
    pl.id, f.filename, pl.turn_start, pl.turn_end,
    pl.source, pl.context, pl.created_at
FROM pending_labels pl
JOIN files f ON pl.file_id = f.id;

DROP TABLE pending_labels;
ALTER TABLE pending_labels_new RENAME TO pending_labels;

CREATE INDEX idx_pending_labels_filename ON pending_labels(filename);

-- ============================================================
-- labels
-- ============================================================
-- file_id INTEGER → filename TEXT

CREATE TABLE labels_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    turn_start INTEGER,
    turn_end INTEGER,
    rating INTEGER NOT NULL,
    tags TEXT,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (filename) REFERENCES files(filename)
        ON UPDATE CASCADE
);

INSERT INTO labels_new (
    id, filename, turn_start, turn_end, rating, tags, notes, created_at
)
SELECT
    l.id, f.filename, l.turn_start, l.turn_end,
    l.rating, l.tags, l.notes, l.created_at
FROM labels l
JOIN files f ON l.file_id = f.id;

DROP TABLE labels;
ALTER TABLE labels_new RENAME TO labels;

CREATE INDEX idx_labels_filename ON labels(filename);

-- ============================================================
-- noise_predictions
-- ============================================================
-- file_id INTEGER → filename TEXT
-- UNIQUE(file_id, turn_idx) → UNIQUE(filename, turn_idx)

CREATE TABLE noise_predictions_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    turn_idx INTEGER NOT NULL,
    deterministic_is_noise INTEGER,
    deterministic_reason TEXT,
    ml_score REAL,
    ml_is_noise INTEGER,
    human_label INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT,
    UNIQUE(filename, turn_idx),
    FOREIGN KEY (filename) REFERENCES files(filename)
        ON UPDATE CASCADE
);

INSERT INTO noise_predictions_new (
    id, filename, turn_idx, deterministic_is_noise, deterministic_reason,
    ml_score, ml_is_noise, human_label, created_at, updated_at
)
SELECT
    np.id, f.filename, np.turn_idx, np.deterministic_is_noise,
    np.deterministic_reason, np.ml_score, np.ml_is_noise, np.human_label,
    np.created_at, np.updated_at
FROM noise_predictions np
JOIN files f ON np.file_id = f.id;

DROP TABLE noise_predictions;
ALTER TABLE noise_predictions_new RENAME TO noise_predictions;

CREATE INDEX idx_noise_predictions_filename ON noise_predictions(filename);

-- ============================================================
-- examples
-- ============================================================
-- file_id INTEGER → filename TEXT
-- marker_id FK preserved unchanged

CREATE TABLE examples_new (
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

INSERT INTO examples_new (
    id, marker_id, filename, turn_start, turn_end, excerpt, notes, created_at
)
SELECT
    e.id, e.marker_id, f.filename, e.turn_start, e.turn_end,
    e.excerpt, e.notes, e.created_at
FROM examples e
JOIN files f ON e.file_id = f.id;

DROP TABLE examples;
ALTER TABLE examples_new RENAME TO examples;

CREATE INDEX idx_examples_marker ON examples(marker_id);
CREATE INDEX idx_examples_filename ON examples(filename);

-- ============================================================
-- annotations
-- ============================================================
-- file_id INTEGER → filename TEXT

CREATE TABLE annotations_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    exchange_start INTEGER,
    exchange_end INTEGER,
    kind TEXT NOT NULL,
    value TEXT,
    thread TEXT,
    notes TEXT,
    source TEXT DEFAULT 'human',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (filename) REFERENCES files(filename)
        ON UPDATE CASCADE
);

INSERT INTO annotations_new (
    id, filename, exchange_start, exchange_end, kind, value, thread,
    notes, source, created_at
)
SELECT
    a.id, f.filename, a.exchange_start, a.exchange_end, a.kind, a.value,
    a.thread, a.notes, a.source, a.created_at
FROM annotations a
JOIN files f ON a.file_id = f.id;

DROP TABLE annotations;
ALTER TABLE annotations_new RENAME TO annotations;

CREATE INDEX idx_annotations_filename ON annotations(filename);
CREATE INDEX idx_annotations_kind ON annotations(kind);
CREATE INDEX idx_annotations_thread ON annotations(thread);

-- ============================================================
-- calibration_items
-- ============================================================
-- file_id INTEGER → filename TEXT
-- UNIQUE(round_id, file_id) → UNIQUE(round_id, filename)
-- round_id and label_id FKs preserved unchanged

CREATE TABLE calibration_items_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    round_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    position INTEGER NOT NULL,
    excerpt TEXT,
    label_id INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(round_id, filename),
    FOREIGN KEY (round_id) REFERENCES calibration_rounds(id),
    FOREIGN KEY (label_id) REFERENCES labels(id),
    FOREIGN KEY (filename) REFERENCES files(filename)
        ON UPDATE CASCADE
);

INSERT INTO calibration_items_new (
    id, round_id, filename, position, excerpt, label_id, created_at
)
SELECT
    ci.id, ci.round_id, f.filename, ci.position, ci.excerpt,
    ci.label_id, ci.created_at
FROM calibration_items ci
JOIN files f ON ci.file_id = f.id;

DROP TABLE calibration_items;
ALTER TABLE calibration_items_new RENAME TO calibration_items;

CREATE INDEX idx_calibration_items_filename ON calibration_items(filename);

-- ============================================================
-- Re-enable FK enforcement and verify integrity
-- ============================================================

PRAGMA foreign_keys = ON;
PRAGMA foreign_key_check;
