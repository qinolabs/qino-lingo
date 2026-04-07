"""
Migration runner for corpus.db.

Discovers `.sql` files in `python/qino_lingo/migrations/`, applies any that
have not yet been recorded in the `schema_migrations` table, and runs each
inside a single transaction so partial application is impossible.

Usage:
    python -m python.qino_lingo.migrate              # apply pending migrations
    python -m python.qino_lingo.migrate --dry-run    # report what would run
    python -m python.qino_lingo.migrate --status     # show applied + pending

The `schema_migrations` table is bootstrapped on every run, so there is no
chicken-and-egg "migration zero" requirement. Migrations are applied in
lexical filename order — the convention is `NN-descriptive-name.sql` where
`NN` is a zero-padded sequence number.
"""

import argparse
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

from .db import DEFAULT_DB_PATH

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# `NN-name.sql` — number, hyphen, slug, .sql. Anything else is ignored so
# editor scratch files (`.sql.swp`, `01-foo.sql.bak`) don't get picked up.
MIGRATION_FILENAME_RE = re.compile(r"^(\d+)-[a-z0-9-]+\.sql$")


def discover_migrations(migrations_dir: Path = MIGRATIONS_DIR) -> List[Path]:
    """Return migration files in lexical order."""
    if not migrations_dir.exists():
        return []
    files = [
        p for p in migrations_dir.iterdir()
        if p.is_file() and MIGRATION_FILENAME_RE.match(p.name)
    ]
    return sorted(files, key=lambda p: p.name)


def ensure_migrations_table(conn: sqlite3.Connection) -> None:
    """Bootstrap the `schema_migrations` table. Idempotent."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            name        TEXT PRIMARY KEY,
            applied_at  TEXT NOT NULL
        )
    """)


def applied_migrations(conn: sqlite3.Connection) -> set[str]:
    """Return the set of migration filenames already applied."""
    rows = conn.execute("SELECT name FROM schema_migrations").fetchall()
    return {row[0] for row in rows}


def pending_migrations(
    conn: sqlite3.Connection,
    migrations_dir: Path = MIGRATIONS_DIR,
) -> List[Path]:
    """Return migrations that exist on disk but are not yet recorded as applied."""
    applied = applied_migrations(conn)
    return [p for p in discover_migrations(migrations_dir) if p.name not in applied]


def apply_migration(conn: sqlite3.Connection, path: Path) -> None:
    """Run a single migration inside a transaction.

    The entire SQL file plus the schema_migrations bookkeeping insert run
    in one transaction. If anything raises, the rollback unwinds both — so
    a half-applied migration cannot be recorded as applied.
    """
    sql = path.read_text()
    try:
        with conn:  # context manager = BEGIN ... COMMIT/ROLLBACK
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                (path.name, datetime.now(timezone.utc).isoformat()),
            )
    except sqlite3.Error as e:
        raise RuntimeError(f"migration {path.name} failed: {e}") from e


def run(
    db_path: Path = DEFAULT_DB_PATH,
    migrations_dir: Path = MIGRATIONS_DIR,
    dry_run: bool = False,
) -> Tuple[List[str], List[str]]:
    """Apply all pending migrations.

    Returns a tuple of (applied_now, skipped_already_applied) — names only.
    On dry_run, applied_now is the list of migrations that *would* be applied.
    """
    # Open without the FK-enforcing context manager — migrations themselves
    # may need to toggle PRAGMA foreign_keys (e.g., for rebuild-and-rename
    # column drops on older SQLite). The runner stays neutral and lets each
    # migration manage its own enforcement state.
    conn = sqlite3.connect(db_path)
    try:
        ensure_migrations_table(conn)
        conn.commit()

        already = sorted(applied_migrations(conn))
        pending = pending_migrations(conn, migrations_dir)

        if dry_run:
            return ([p.name for p in pending], already)

        applied_now: List[str] = []
        for path in pending:
            apply_migration(conn, path)
            applied_now.append(path.name)
        return (applied_now, already)
    finally:
        conn.close()


def status(
    db_path: Path = DEFAULT_DB_PATH,
    migrations_dir: Path = MIGRATIONS_DIR,
) -> None:
    """Print applied and pending migrations."""
    conn = sqlite3.connect(db_path)
    try:
        ensure_migrations_table(conn)
        conn.commit()
        applied = applied_migrations(conn)
        all_files = discover_migrations(migrations_dir)
        if not all_files:
            print("no migrations found in", migrations_dir)
            return
        print(f"db: {db_path}")
        print(f"migrations dir: {migrations_dir}")
        print()
        for path in all_files:
            mark = "applied" if path.name in applied else "pending"
            print(f"  [{mark:>7}] {path.name}")
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply pending corpus.db migrations.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Path to corpus.db (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be applied without modifying the database.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show applied and pending migrations and exit.",
    )
    args = parser.parse_args()

    if args.status:
        status(db_path=args.db)
        return 0

    applied_now, already = run(db_path=args.db, dry_run=args.dry_run)

    if args.dry_run:
        if applied_now:
            print(f"would apply {len(applied_now)} migration(s):")
            for name in applied_now:
                print(f"  + {name}")
        else:
            print("no pending migrations")
        if already:
            print(f"({len(already)} already applied)")
        return 0

    if applied_now:
        print(f"applied {len(applied_now)} migration(s):")
        for name in applied_now:
            print(f"  + {name}")
    else:
        print("no pending migrations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
