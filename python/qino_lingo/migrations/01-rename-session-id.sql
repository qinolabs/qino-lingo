-- 01-rename-session-id.sql
--
-- Rename files.session_id → files.claude_session_id.
--
-- Why: the column holds an identifier extracted from the conversation
-- filename, which itself comes from claude-extract's view of
-- ~/.claude/projects/. The current name reads as "the qino-lingo session
-- identifier" — implying we generate it. We don't. Renaming with the
-- claude_ prefix self-documents the external dependency at every read site
-- and reserves the unprefixed session_id for a future qino-lingo-internal
-- session concept.
--
-- This migration also drops and recreates the supporting index so its
-- name reflects the new column. SQLite ≥3.25 auto-updates index column
-- references on RENAME COLUMN, but the *index name* doesn't change unless
-- you drop and recreate it.
--
-- Note: this rename does NOT change the value of the column — it remains
-- the truncated 8-hex form that claude-extract emits. Stage B (a future
-- iteration) captures the full UUID at ingest time and switches the FK
-- target. For now, claude_session_id is a description, not a stable key.

DROP INDEX IF EXISTS idx_files_session;

ALTER TABLE files RENAME COLUMN session_id TO claude_session_id;

CREATE INDEX idx_files_claude_session ON files(claude_session_id);
