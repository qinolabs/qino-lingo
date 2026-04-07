-- 00-init.sql
--
-- Placeholder migration that exists so the runner has at least one file
-- to discover and record. The schema_migrations table itself is bootstrapped
-- by migrate.py::ensure_migrations_table on every run, so there is no DDL
-- to do here.
--
-- This file can be removed once a real migration 01-* exists; nothing
-- depends on its presence. It is intentionally a no-op.

SELECT 1;
