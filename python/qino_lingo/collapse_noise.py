"""
One-shot data migration: collapse data/corpus/_noise/ into files.status.

After Chunk 1 the schema can hold filename-as-FK references reliably,
and after migration 03 the files.status column has a CHECK constraint
that allows 'noise' as a value. This script does the data half of
Chunk 2:

  1. For files in _noise/ that already have a db row, set status='noise'.
  2. For files in _noise/ that have NO db row (legacy orphans from when
     filter_noise.py ran before db ingestion existed), extract metadata
     locally and INSERT them with status='noise'. This is the only
     reasonable way to recover them — they predate the ingestion
     pipeline so make ingest cannot pick them up (it walks
     ~/.claude/projects/, not the local corpus).
  3. Move all of those files from _noise/ back into data/corpus/. After
     Chunk 2, _noise/ is no longer a filesystem concept — files are
     classified by their db row's status, regardless of where they
     physically live.
  4. Remove the (now-empty) _noise/ directory.

This script is one-shot. Once run successfully it has no work left to
do, but it is kept in the repo as documentation of the chunk 2 data
migration. The Make target `chunk2-collapse` invokes it.

Usage:
    python -m python.qino_lingo.collapse_noise              # apply
    python -m python.qino_lingo.collapse_noise --dry-run    # report only
"""

import argparse
import shutil
import sys
from pathlib import Path

# extract_metadata.py lives at the project root, not under python/.
# Walk up two levels from this file to reach it.
PROJECT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from extract_metadata import extract_metadata as extract_file_metadata  # noqa: E402

from .db import get_connection, extract_claude_session_id, DEFAULT_DB_PATH  # noqa: E402

CORPUS_DIR = PROJECT_DIR / "data" / "corpus"
NOISE_DIR = CORPUS_DIR / "_noise"


def collect_state(db_path: Path = DEFAULT_DB_PATH) -> dict:
    """Read the current filesystem and db state. Returns a categorized view."""
    if not NOISE_DIR.exists():
        return {
            "noise_dir_exists": False,
            "noise_files": [],
            "in_db_to_backfill": [],
            "orphans_to_ingest": [],
        }

    noise_files = sorted(p for p in NOISE_DIR.glob("claude-conversation-*.md"))
    noise_filenames = {p.name for p in noise_files}

    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT filename FROM files WHERE filename IN (%s)"
            % ",".join("?" * len(noise_filenames)),
            tuple(noise_filenames),
        ).fetchall() if noise_filenames else []
        in_db = {r[0] for r in rows}

    in_db_to_backfill = [p for p in noise_files if p.name in in_db]
    orphans_to_ingest = [p for p in noise_files if p.name not in in_db]

    return {
        "noise_dir_exists": True,
        "noise_files": noise_files,
        "in_db_to_backfill": in_db_to_backfill,
        "orphans_to_ingest": orphans_to_ingest,
    }


def ingest_orphan(filepath: Path, conn) -> None:
    """Insert a row for an orphan file with status='noise'.

    Uses extract_metadata.extract_metadata to compute the same metadata
    fields the normal ingestion path would. The only difference is that
    `status` is set to 'noise' explicitly rather than defaulting to
    'active', and source_path is unset (these files have no upstream
    in ~/.claude/projects/).
    """
    meta = extract_file_metadata(filepath)
    claude_session_id = extract_claude_session_id(meta["filename"])

    conn.execute(
        """
        INSERT INTO files (
            filename, claude_session_id, date, is_agent, file_size,
            user_turns, claude_turns, substantive_user_turns,
            user_word_count, claude_word_count, dialogue_density,
            has_command_expansion, has_reflective_language,
            source_path, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'noise')
        """,
        (
            meta["filename"], claude_session_id, meta["date"],
            meta["is_agent"], meta["file_size"],
            meta["user_turns"], meta["claude_turns"],
            meta["substantive_user_turns"],
            meta["user_word_count"], meta["claude_word_count"],
            meta["dialogue_density"],
            meta["has_command_expansion"], meta["has_reflective_language"],
            None,
        ),
    )


def run(db_path: Path = DEFAULT_DB_PATH, dry_run: bool = False) -> int:
    state = collect_state(db_path)

    if not state["noise_dir_exists"]:
        print(f"_noise/ does not exist at {NOISE_DIR}; nothing to do.")
        return 0

    noise_files = state["noise_files"]
    in_db = state["in_db_to_backfill"]
    orphans = state["orphans_to_ingest"]

    print(f"Found {len(noise_files)} files in {NOISE_DIR}:")
    print(f"  {len(in_db)} have existing db rows (backfill status='noise')")
    print(f"  {len(orphans)} are orphans (insert as new noise rows)")

    if dry_run:
        print()
        print("DRY RUN — no changes made.")
        if orphans:
            print(f"\nFirst 5 orphans that would be ingested:")
            for p in orphans[:5]:
                print(f"  {p.name}")
        return 0

    # Backfill + ingest in a single transaction. Bail if anything errors;
    # the file moves below run only after the db work commits cleanly.
    with get_connection(db_path) as conn:
        # 1. Backfill: set status='noise' for files that already have db rows
        for filepath in in_db:
            conn.execute(
                "UPDATE files SET status = 'noise' WHERE filename = ?",
                (filepath.name,),
            )

        # 2. Ingest orphans
        for i, filepath in enumerate(orphans, 1):
            try:
                ingest_orphan(filepath, conn)
            except Exception as e:
                print(f"  [ERROR] {filepath.name}: {e}")
                raise

        print(f"  db: marked {len(in_db)} as noise, ingested {len(orphans)} orphans")

    # 3. Move all noise files back to top-level corpus/. After this, every
    # conversation file lives at top level — the noise/active distinction
    # is purely a db column.
    moved = 0
    collisions = []
    for filepath in noise_files:
        dest = CORPUS_DIR / filepath.name
        if dest.exists():
            collisions.append(filepath.name)
            continue
        shutil.move(str(filepath), str(dest))
        moved += 1
    print(f"  fs: moved {moved} files to {CORPUS_DIR}")
    if collisions:
        print(f"  WARNING: {len(collisions)} files already existed at top level — left in _noise/")
        for name in collisions[:5]:
            print(f"    {name}")

    # 4. Remove the now-empty _noise/ directory (only if it's truly empty)
    remaining = list(NOISE_DIR.iterdir()) if NOISE_DIR.exists() else []
    if not remaining:
        NOISE_DIR.rmdir()
        print(f"  fs: removed {NOISE_DIR}")
    else:
        print(f"  WARNING: {len(remaining)} files left in {NOISE_DIR}, not removing")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collapse data/corpus/_noise/ into files.status (chunk 2).",
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
        help="Report what would happen without changing anything.",
    )
    args = parser.parse_args()
    return run(db_path=args.db, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
