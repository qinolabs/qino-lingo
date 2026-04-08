"""
Transactional backup runner for corpus.db (+ a sha256 manifest of data/corpus/).

Replaces the legacy `backup-corpus.sh` (which used `cp` — vulnerable to
half-written pages — and only knew about labeling-era tables). This module:

  1. Snapshots `corpus.db` via SQLite's online `.backup()` API. Safe to run
     while another process holds the db open for reads or writes; cannot
     capture a torn page; uses a single transaction at the SQLite level.
  2. Writes a sidecar `corpus-TIMESTAMP.manifest.json` listing every `.md`
     file in `data/corpus/` with its sha256 + size. The markdown files
     themselves are not copied — they are large and regeneratable from
     `claude-extract`. The manifest is what lets us *detect* if any source
     file later disappears or corrupts.
  3. Reports row counts at backup time for both consumer surfaces (the MCP
     side: signals + annotations; the training side: labels, calibration
     items, pending labels, etc.) so the backup record itself documents
     "this is what the corpus looked like the moment we snapshotted it."
  4. Rotates older backups: always keep the N most-recent files, plus —
     among older files — keep the newest file per ISO week for the last M
     weeks. This gives short-term granularity for "I broke something today"
     plus a few months of weekly anchors for "what did the corpus look like
     in early March."

Usage:
    python -m python.qino_lingo.backup                   # ad-hoc backup
    python -m python.qino_lingo.backup --tag pre-ingest  # labeled snapshot
    python -m python.qino_lingo.backup --dry-run         # plan-only
    python -m python.qino_lingo.backup --no-rotate       # don't prune
    python -m python.qino_lingo.backup --keep-recent 20 --keep-weekly 12

Or, from Python:
    from python.qino_lingo.backup import run_backup, print_report
    result = run_backup(tag="pre-ingest")
    print_report(result)
"""

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).parent.parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "corpus.db"
DEFAULT_CORPUS_DIR = PROJECT_ROOT / "data" / "corpus"
DEFAULT_BACKUP_DIR = PROJECT_ROOT / "backups"

# Recognizes both untagged and tagged backup filenames:
#   corpus-20260408-013653.db
#   corpus-20260408-013653-pre-ingest.db
# The optional trailing slug must be kebab-case so the regex stays simple.
BACKUP_FILENAME_RE = re.compile(
    r"^corpus-(\d{8}-\d{6})(?:-[a-z0-9]+(?:-[a-z0-9]+)*)?\.db$"
)

# Tags must match this shape so they slot cleanly into the filename regex.
TAG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# Tables whose counts we capture in the backup report. Grouped by consumer
# so the report makes the dual-purpose nature of the db visible. Order
# inside each group is just the order they tend to come up in conversation.
REPORTED_TABLES: List[Tuple[str, str]] = [
    ("files",                "shared"),
    ("conversation_signals", "mcp"),
    ("annotations",          "mcp"),
    ("labels",               "training"),
    ("markers",              "training"),
    ("examples",             "training"),
    ("pending_labels",       "training"),
    ("noise_predictions",    "training"),
    ("model_feedback",       "training"),
    ("calibration_rounds",   "training"),
    ("calibration_items",    "training"),
]

DEFAULT_KEEP_RECENT = 10
DEFAULT_KEEP_WEEKLY = 8


@dataclass
class BackupResult:
    """What happened during one invocation of `run_backup`.

    On dry runs, `db_bytes` and `corpus_file_count` reflect the *current*
    state that would be backed up; the `db_path` and `manifest_path` are
    the paths that *would* be written. `pruned` is what would be deleted.
    """
    timestamp: str
    db_path: Path
    manifest_path: Path
    db_bytes: int
    corpus_file_count: int
    counts: Dict[str, int]
    pruned: List[Path] = field(default_factory=list)
    kept: int = 0
    dry_run: bool = False


# --------------------------------------------------------------------------
# Filename / time helpers
# --------------------------------------------------------------------------

def timestamp_now() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def parse_timestamp(filename: str) -> Optional[datetime]:
    """Extract the backup timestamp from a backup filename, or None."""
    match = BACKUP_FILENAME_RE.match(filename)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d-%H%M%S")
    except ValueError:
        return None


def iso_week(dt: datetime) -> Tuple[int, int]:
    """(ISO year, ISO week) for grouping backups into weekly buckets."""
    iy, iw, _ = dt.isocalendar()
    return (iy, iw)


def sidecar_manifest_path(db_backup_path: Path) -> Path:
    """Given .../corpus-TIMESTAMP.db return .../corpus-TIMESTAMP.manifest.json"""
    return db_backup_path.with_suffix(".manifest.json")


# --------------------------------------------------------------------------
# DB backup (SQLite online backup API)
# --------------------------------------------------------------------------

def backup_db(db_path: Path, out_path: Path) -> int:
    """Take a transactional snapshot of `db_path` to `out_path`.

    Uses `sqlite3.Connection.backup()`, which is the official safe way to
    copy a live SQLite database. The alternative (`cp` or `shutil.copy`)
    can capture a half-written page if a writer is mid-commit. The online
    backup API holds the right locks for the duration of the copy and
    produces a consistent snapshot even under concurrent access.

    On any failure the partial destination file is removed so a botched
    backup never sits in the rotation looking like a real one.

    Returns the size of the resulting file in bytes.
    """
    src = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(out_path)
        try:
            with dst:
                src.backup(dst)
        finally:
            dst.close()
    except Exception:
        out_path.unlink(missing_ok=True)
        raise
    finally:
        src.close()
    return out_path.stat().st_size


def read_counts(db_path: Path) -> Dict[str, int]:
    """Return row counts for every table in REPORTED_TABLES.

    Tables that don't exist (e.g., because a migration hasn't run on this
    db yet) are recorded as -1 so the report can distinguish "missing"
    from "zero rows."
    """
    counts: Dict[str, int] = {}
    if not db_path.exists():
        return counts
    conn = sqlite3.connect(db_path)
    try:
        for name, _consumer in REPORTED_TABLES:
            try:
                row = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()
                counts[name] = row[0]
            except sqlite3.OperationalError:
                counts[name] = -1
    finally:
        conn.close()
    return counts


# --------------------------------------------------------------------------
# Manifest of data/corpus/
# --------------------------------------------------------------------------

def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(
    corpus_dir: Path,
    manifest_path: Path,
    timestamp: str,
) -> int:
    """Write a sha256 manifest of `corpus_dir` to `manifest_path`.

    Only top-level `.md` files are hashed. Sub-directories are ignored —
    post-Chunk 2 the corpus is flat (no `_noise/`), and we don't want a
    stray nested directory turning the manifest into something it isn't.

    The write is atomic: we write to a sibling `.tmp` file then rename, so
    a crashed backup leaves either nothing or a complete manifest, never
    a half-written one.

    Returns the number of files in the manifest.
    """
    files = sorted(p for p in corpus_dir.glob("*.md") if p.is_file())
    entries = [
        {
            "filename": p.name,
            "sha256":   sha256_file(p),
            "size":     p.stat().st_size,
        }
        for p in files
    ]
    manifest = {
        "generated_at": timestamp,
        "corpus_dir":   str(corpus_dir.relative_to(PROJECT_ROOT)),
        "file_count":   len(entries),
        "files":        entries,
    }
    tmp_path = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(manifest, indent=2) + "\n")
    tmp_path.replace(manifest_path)
    return len(entries)


# --------------------------------------------------------------------------
# Rotation
# --------------------------------------------------------------------------

def list_backups(backup_dir: Path) -> List[Tuple[datetime, Path]]:
    """List all backup files with parseable timestamps, newest first."""
    backups: List[Tuple[datetime, Path]] = []
    if backup_dir.exists():
        for p in backup_dir.glob("corpus-*.db"):
            ts = parse_timestamp(p.name)
            if ts is None:
                continue
            backups.append((ts, p))
    backups.sort(key=lambda x: x[0], reverse=True)
    return backups


def split_rotation(
    backups: List[Tuple[datetime, Path]],
    keep_recent: int,
    keep_weekly: int,
) -> Tuple[List[Path], List[Path]]:
    """Decide which entries to keep and which to prune from a backup list.

    Strategy:
      1. Always keep the `keep_recent` newest entries.
      2. Among the rest, walk newest-to-oldest and keep one entry per
         distinct ISO week, until `keep_weekly` weeks have been retained.
      3. Everything else is pruned.

    The limit check in step 2 happens BEFORE adding to the kept set so
    `keep_weekly=0` is a true no-op. Returns (to_keep, to_prune), both
    newest-first.
    """
    kept: set[Path] = set()

    # Recent window: top N regardless of date.
    for _ts, p in backups[:keep_recent]:
        kept.add(p)

    # Weekly window: among the rest, keep one per ISO week for M weeks.
    seen_weeks: Dict[Tuple[int, int], Path] = {}
    for ts, p in backups[keep_recent:]:
        if len(seen_weeks) >= keep_weekly:
            break
        wk = iso_week(ts)
        if wk in seen_weeks:
            continue
        seen_weeks[wk] = p
    for p in seen_weeks.values():
        kept.add(p)

    to_keep  = [p for _ts, p in backups if p in kept]
    to_prune = [p for _ts, p in backups if p not in kept]
    return (to_keep, to_prune)


def plan_rotation(
    backup_dir: Path,
    keep_recent: int,
    keep_weekly: int,
) -> Tuple[List[Path], List[Path]]:
    """Decide which existing backups to keep and which to prune.

    Thin wrapper around `split_rotation` that reads the backup directory
    from disk. Use `split_rotation` directly when you want to inject a
    simulated set (e.g. dry-run that includes a not-yet-written file).
    """
    return split_rotation(list_backups(backup_dir), keep_recent, keep_weekly)


def prune(paths: List[Path]) -> None:
    """Delete each path and its sidecar manifest. Idempotent."""
    for p in paths:
        sidecar = sidecar_manifest_path(p)
        p.unlink(missing_ok=True)
        sidecar.unlink(missing_ok=True)


# --------------------------------------------------------------------------
# Top-level orchestration
# --------------------------------------------------------------------------

def run_backup(
    db_path: Path = DEFAULT_DB_PATH,
    corpus_dir: Path = DEFAULT_CORPUS_DIR,
    backup_dir: Path = DEFAULT_BACKUP_DIR,
    tag: Optional[str] = None,
    keep_recent: int = DEFAULT_KEEP_RECENT,
    keep_weekly: int = DEFAULT_KEEP_WEEKLY,
    rotate: bool = True,
    dry_run: bool = False,
) -> BackupResult:
    """Take one backup and (optionally) rotate older ones.

    Order of operations:
      1. Read row counts from the live db (cheap, just for the report).
      2. Snapshot db -> backups/corpus-TIMESTAMP[-tag].db
      3. Write manifest -> backups/corpus-TIMESTAMP[-tag].manifest.json
      4. Rotate the backups directory.

    Step 4 happens AFTER the new file is written so the new file is
    inside the rotation window — it can immediately count toward the
    "10 most recent" and toward its own ISO week's anchor.
    """
    if tag is not None and not TAG_RE.match(tag):
        raise ValueError(f"tag must be kebab-case ([a-z0-9-]+), got: {tag!r}")

    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = timestamp_now()
    tag_suffix = f"-{tag}" if tag else ""
    db_backup_path = backup_dir / f"corpus-{timestamp}{tag_suffix}.db"
    manifest_path = sidecar_manifest_path(db_backup_path)

    counts = read_counts(db_path)

    if dry_run:
        # Don't write anything, but still compute what *would* happen.
        corpus_count = sum(1 for p in corpus_dir.glob("*.md") if p.is_file())
        # Simulate the post-backup state by injecting the would-be new file
        # at the head of the backup list, then run the same rotation split
        # against the simulated set. This makes the dry-run report match
        # exactly what the real run would do.
        simulated = [
            (datetime.strptime(timestamp, "%Y%m%d-%H%M%S"), db_backup_path)
        ] + list_backups(backup_dir)
        if rotate:
            sim_keep, sim_prune = split_rotation(
                simulated, keep_recent, keep_weekly
            )
        else:
            # --no-rotate: keep everything that exists + the new file.
            sim_keep = [p for _ts, p in simulated]
            sim_prune = []
        return BackupResult(
            timestamp=timestamp,
            db_path=db_backup_path,
            manifest_path=manifest_path,
            db_bytes=db_path.stat().st_size if db_path.exists() else 0,
            corpus_file_count=corpus_count,
            counts=counts,
            pruned=sim_prune,
            kept=len(sim_keep),
            dry_run=True,
        )

    if not db_path.exists():
        raise FileNotFoundError(f"corpus.db not found at {db_path}")
    if not corpus_dir.exists():
        raise FileNotFoundError(f"corpus dir not found at {corpus_dir}")

    db_bytes = backup_db(db_path, db_backup_path)
    corpus_count = write_manifest(corpus_dir, manifest_path, timestamp)

    pruned: List[Path] = []
    if rotate:
        _to_keep, to_prune = plan_rotation(backup_dir, keep_recent, keep_weekly)
        prune(to_prune)
        pruned = to_prune

    final_keep, _ = plan_rotation(backup_dir, keep_recent, keep_weekly)

    return BackupResult(
        timestamp=timestamp,
        db_path=db_backup_path,
        manifest_path=manifest_path,
        db_bytes=db_bytes,
        corpus_file_count=corpus_count,
        counts=counts,
        pruned=pruned,
        kept=len(final_keep),
        dry_run=False,
    )


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def format_bytes(n: int) -> str:
    val = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if val < 1024:
            return f"{val:.1f}{unit}"
        val /= 1024
    return f"{val:.1f}TB"


def print_report(result: BackupResult) -> None:
    header = "BACKUP (dry run)" if result.dry_run else "BACKUP"
    print(header)
    print(f"  timestamp:    {result.timestamp}")
    print(f"  db file:      {result.db_path}")
    print(f"  manifest:     {result.manifest_path}")
    print(f"  size:         {format_bytes(result.db_bytes)}")
    print(f"  corpus .md:   {result.corpus_file_count} files")
    print()
    print("  row counts:")
    by_consumer: Dict[str, List[str]] = {}
    for name, consumer in REPORTED_TABLES:
        by_consumer.setdefault(consumer, []).append(name)
    for consumer in ("shared", "mcp", "training"):
        print(f"    [{consumer}]")
        for name in by_consumer.get(consumer, []):
            val = result.counts.get(name, -1)
            label = f"{val:>6}" if val >= 0 else "   n/a"
            print(f"      {name:<22} {label}")
    print()
    if result.pruned:
        print(f"  pruned:       {len(result.pruned)} old backup(s)")
        for p in result.pruned:
            print(f"    - {p.name}")
    else:
        print("  pruned:       0")
    print(f"  kept:         {result.kept} backup(s)")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Take a transactional backup of corpus.db plus a "
                    "sha256 manifest of data/corpus/.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Path to corpus.db (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=DEFAULT_CORPUS_DIR,
        help=f"Path to the corpus directory (default: {DEFAULT_CORPUS_DIR})",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_BACKUP_DIR,
        help=f"Backup output directory (default: {DEFAULT_BACKUP_DIR})",
    )
    parser.add_argument(
        "--tag",
        type=str,
        default=None,
        help="Optional kebab-case tag appended to the backup filename "
             "(e.g. 'pre-ingest', 'pre-chunk4-apply').",
    )
    parser.add_argument(
        "--keep-recent",
        type=int,
        default=DEFAULT_KEEP_RECENT,
        help=f"Always keep this many most-recent backups "
             f"(default: {DEFAULT_KEEP_RECENT}).",
    )
    parser.add_argument(
        "--keep-weekly",
        type=int,
        default=DEFAULT_KEEP_WEEKLY,
        help=f"Among older backups, keep one per ISO week for this many "
             f"weeks (default: {DEFAULT_KEEP_WEEKLY}).",
    )
    parser.add_argument(
        "--no-rotate",
        action="store_true",
        help="Take a backup but don't prune older ones.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would happen without writing anything.",
    )
    args = parser.parse_args()

    try:
        result = run_backup(
            db_path=args.db,
            corpus_dir=args.corpus,
            backup_dir=args.out,
            tag=args.tag,
            keep_recent=args.keep_recent,
            keep_weekly=args.keep_weekly,
            rotate=not args.no_rotate,
            dry_run=args.dry_run,
        )
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print_report(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
