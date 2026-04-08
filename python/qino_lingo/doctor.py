"""
Read-only health check for corpus.db (+ data/corpus/).

`doctor` is the diagnostic counterpart to `migrate` and `backup`. Where those
two are write-side operations (they change the corpus state), `doctor` only
reads — it answers the question "is the corpus internally consistent right
now?" by combining several invariants that this iteration's earlier chunks
care about:

  1. **Foreign-key integrity** — every dependent row's `filename` resolves to
     a row in `files`. Chunk 1 made this a real constraint by enabling
     `PRAGMA foreign_keys = ON` on every connection, but a `foreign_key_check`
     verifies it post-hoc and catches anything that slipped in via a
     connection that did not.
  2. **Signal coverage** — Chunk 2 collapsed `_noise/` into `files.status`,
     and the digest now reports the *real* gap between active files and
     computed signals. Doctor splits that gap into the two populations that
     matter: files that are legitimately too thin for the v6 algorithm to
     produce a result (`< 2 substantive user turns`), and files that look
     substantial but somehow have no signal row — i.e., the actual coverage
     hole.
  3. **File/db reconciliation** — for each `files` row whose markdown should
     live at `data/corpus/{filename}`, verify the file exists; for each `.md`
     file at the top level of `data/corpus/`, verify a row exists in `files`.
     After Chunk 2, both populations should be identical sets.
  4. **Algorithm version drift** — same check `signals.check_staleness` has
     always done, surfaced alongside the new gap audit so a single command
     answers "is the signal layer healthy."

Doctor never writes to the db. It exits non-zero if any invariant is
broken so it can be wired into CI later. The `--verbose` flag adds sample
filenames for each finding so the user can chase a specific row, but the
default output stays small enough to scan in a glance.

Usage:
    python -m python.qino_lingo.doctor                # default health check
    python -m python.qino_lingo.doctor --verbose      # with sample listings
    python -m python.qino_lingo.doctor --report-file PATH
                                                       # also write a copy of
                                                       # the report to PATH

Or, from Python:
    from python.qino_lingo.doctor import run_doctor, print_report
    result = run_doctor()
    print_report(result)
    if not result.is_healthy:
        ...
"""

import argparse
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .db import DEFAULT_DB_PATH
from .signals import ALGORITHM_VERSION

PROJECT_ROOT = Path(__file__).parent.parent.parent
DEFAULT_CORPUS_DIR = PROJECT_ROOT / "data" / "corpus"

# Tables grouped by consumer, mirroring backup.py's REPORTED_TABLES split.
# Doctor uses this only for reporting orphan FK populations: any dependent
# table that FKs to files(filename) appears here so the report can group
# the orphans by which consumer is affected if there are any.
DEPENDENT_TABLES: List[Tuple[str, str]] = [
    ("conversation_signals", "mcp"),
    ("annotations",          "mcp"),
    ("labels",               "training"),
    ("examples",             "training"),
    ("pending_labels",       "training"),
    ("noise_predictions",    "training"),
    ("calibration_items",    "training"),
]

# Sample size used by --verbose. Small on purpose: doctor's job is to
# surface a finding, not dump every offending row.
SAMPLE_LIMIT = 5

# A file with fewer than this many substantive user turns cannot produce
# signals via the v6 algorithm — `signals.analyze_conversation` returns
# None. Doctor uses this threshold to split the signal-coverage gap into
# "legitimately empty" vs "real coverage hole". Must stay in sync with
# signals.analyze_conversation's `len(reflective) < 2` short-circuit.
MIN_SUBSTANTIVE_TURNS_FOR_SIGNALS = 2


@dataclass
class FindingSample:
    """A small sample of rows or filenames that triggered a finding."""
    label: str
    items: List[str] = field(default_factory=list)


@dataclass
class DoctorResult:
    """Aggregate result of one doctor run.

    Each `*_count` field is the size of the affected population. The
    `samples` list carries representative items for `--verbose` output.
    `is_healthy` is the single boolean CI cares about.
    """
    timestamp: str
    db_path: Path
    corpus_dir: Path

    # FK integrity
    fk_violations: List[Tuple[str, int, str, int]] = field(default_factory=list)

    # Signal coverage (Chunk 2 left a 396-file gap; Chunk 4 splits it)
    active_files: int = 0
    signals_total: int = 0
    coverage_gap_total: int = 0
    coverage_gap_thin: int = 0          # legitimate (too few substantive turns)
    coverage_gap_substantive: int = 0   # the real coverage hole
    orphan_signal_rows: int = 0         # signal rows whose filename has no file row
    stale_signal_rows: int = 0          # algorithm_version != ALGORITHM_VERSION
    algorithm_version: str = ALGORITHM_VERSION

    # FK orphans across all dependent tables (should be 0 with FK enforcement)
    dependent_orphans: Dict[str, int] = field(default_factory=dict)

    # File/db reconciliation
    db_rows_missing_on_disk: int = 0
    disk_files_missing_in_db: int = 0

    # Verbose samples (only filled when run_doctor(verbose=True))
    samples: List[FindingSample] = field(default_factory=list)

    @property
    def is_healthy(self) -> bool:
        """The single bit CI / make exit-code cares about.

        Algorithm staleness, FK violations, dependent-table orphans, the
        substantive coverage hole, signal-row orphans, and disk/db drift
        all flip this to False. The legitimate-thin gap does NOT — it is
        the expected baseline noise of the v6 algorithm refusing to score
        very short conversations.
        """
        if self.fk_violations:
            return False
        if self.stale_signal_rows:
            return False
        if self.coverage_gap_substantive:
            return False
        if self.orphan_signal_rows:
            return False
        if any(v > 0 for v in self.dependent_orphans.values()):
            return False
        if self.db_rows_missing_on_disk:
            return False
        if self.disk_files_missing_in_db:
            return False
        return True


# --------------------------------------------------------------------------
# Individual checks
# --------------------------------------------------------------------------

def check_foreign_keys(conn: sqlite3.Connection) -> List[Tuple[str, int, str, int]]:
    """Run `PRAGMA foreign_key_check` and return raw violations.

    The pragma returns one row per violation: (table, rowid, parent, fkid).
    With the Chunk 1 invariant in place this list should be empty against
    every live db.
    """
    return [tuple(row) for row in conn.execute("PRAGMA foreign_key_check")]


def check_signal_coverage(
    conn: sqlite3.Connection,
    verbose: bool = False,
) -> Tuple[int, int, int, int, int, int, int, List[FindingSample]]:
    """Compute the signal coverage breakdown.

    Returns:
        (active_files, signals_total,
         coverage_gap_total,
         coverage_gap_thin, coverage_gap_substantive,
         orphan_signal_rows, stale_signal_rows,
         samples)

    The "thin" bucket is files that the v6 signals algorithm legitimately
    refuses to score (too few substantive user turns). The "substantive"
    bucket is the real coverage hole — substantial active files that
    *should* have signals but don't.
    """
    samples: List[FindingSample] = []

    active_files = conn.execute(
        "SELECT COUNT(*) FROM files WHERE status = 'active'"
    ).fetchone()[0]

    signals_total = conn.execute(
        "SELECT COUNT(*) FROM conversation_signals"
    ).fetchone()[0]

    coverage_gap_total = conn.execute(
        """
        SELECT COUNT(*) FROM files f
        WHERE f.status = 'active'
        AND f.filename NOT IN (SELECT filename FROM conversation_signals)
        """
    ).fetchone()[0]

    coverage_gap_thin = conn.execute(
        """
        SELECT COUNT(*) FROM files f
        WHERE f.status = 'active'
        AND f.filename NOT IN (SELECT filename FROM conversation_signals)
        AND COALESCE(f.substantive_user_turns, 0) < ?
        """,
        (MIN_SUBSTANTIVE_TURNS_FOR_SIGNALS,),
    ).fetchone()[0]

    coverage_gap_substantive = coverage_gap_total - coverage_gap_thin

    # Signal rows whose filename does not resolve to a files row.
    # With FK enforcement on this should be 0; we still verify because
    # the FK pragma can be turned off in some connection paths and a
    # second source of truth costs almost nothing.
    orphan_signal_rows = conn.execute(
        """
        SELECT COUNT(*) FROM conversation_signals cs
        WHERE cs.filename NOT IN (SELECT filename FROM files)
        """
    ).fetchone()[0]

    stale_signal_rows = conn.execute(
        "SELECT COUNT(*) FROM conversation_signals WHERE algorithm_version != ?",
        (ALGORITHM_VERSION,),
    ).fetchone()[0]

    if verbose:
        if coverage_gap_substantive > 0:
            rows = conn.execute(
                """
                SELECT f.filename, f.substantive_user_turns, f.user_word_count
                FROM files f
                WHERE f.status = 'active'
                AND f.filename NOT IN (SELECT filename FROM conversation_signals)
                AND COALESCE(f.substantive_user_turns, 0) >= ?
                ORDER BY f.user_word_count DESC
                LIMIT ?
                """,
                (MIN_SUBSTANTIVE_TURNS_FOR_SIGNALS, SAMPLE_LIMIT),
            ).fetchall()
            samples.append(
                FindingSample(
                    label="coverage gap (substantive, no signal row)",
                    items=[
                        f"{r[0]}  ({r[2] or 0} user words, "
                        f"{r[1] or 0} substantive turns)"
                        for r in rows
                    ],
                )
            )
        if orphan_signal_rows > 0:
            rows = conn.execute(
                """
                SELECT cs.filename FROM conversation_signals cs
                WHERE cs.filename NOT IN (SELECT filename FROM files)
                LIMIT ?
                """,
                (SAMPLE_LIMIT,),
            ).fetchall()
            samples.append(
                FindingSample(
                    label="orphan signal rows (filename not in files)",
                    items=[r[0] for r in rows],
                )
            )
        if stale_signal_rows > 0:
            rows = conn.execute(
                """
                SELECT filename, algorithm_version FROM conversation_signals
                WHERE algorithm_version != ?
                LIMIT ?
                """,
                (ALGORITHM_VERSION, SAMPLE_LIMIT),
            ).fetchall()
            samples.append(
                FindingSample(
                    label=f"stale signal rows (current = {ALGORITHM_VERSION})",
                    items=[f"{r[0]}  (stored: {r[1]})" for r in rows],
                )
            )

    return (
        active_files,
        signals_total,
        coverage_gap_total,
        coverage_gap_thin,
        coverage_gap_substantive,
        orphan_signal_rows,
        stale_signal_rows,
        samples,
    )


def check_dependent_orphans(
    conn: sqlite3.Connection,
    verbose: bool = False,
) -> Tuple[Dict[str, int], List[FindingSample]]:
    """Count orphans across every FK-dependent table.

    With Chunk 1's filename-as-FK + per-connection `PRAGMA foreign_keys = ON`,
    every table here should report 0. Running the query anyway is a
    belt-and-suspenders defense: if any code path opens a connection
    without FK enforcement and writes a row whose filename doesn't exist,
    this is the check that catches it.
    """
    counts: Dict[str, int] = {}
    samples: List[FindingSample] = []

    for table, _consumer in DEPENDENT_TABLES:
        try:
            n = conn.execute(
                f"""
                SELECT COUNT(*) FROM {table} t
                WHERE t.filename NOT IN (SELECT filename FROM files)
                """
            ).fetchone()[0]
        except sqlite3.OperationalError:
            # Table doesn't exist on this db (fresh / partially migrated).
            # We don't claim it's healthy or unhealthy — just skip it.
            continue
        counts[table] = n
        if verbose and n > 0:
            rows = conn.execute(
                f"SELECT filename FROM {table} t "
                f"WHERE t.filename NOT IN (SELECT filename FROM files) "
                f"LIMIT ?",
                (SAMPLE_LIMIT,),
            ).fetchall()
            samples.append(
                FindingSample(
                    label=f"orphan {table} rows",
                    items=[r[0] for r in rows],
                )
            )
    return counts, samples


def check_disk_reconciliation(
    conn: sqlite3.Connection,
    corpus_dir: Path,
    verbose: bool = False,
) -> Tuple[int, int, List[FindingSample]]:
    """Cross-check `files` rows against `data/corpus/*.md` on disk.

    Two findings here:
      - db rows whose filename does not exist on disk (file was deleted
        out from under the db, or status='missing' is the right next move)
      - top-level `.md` files in `data/corpus/` with no row in `files`
        (something landed without going through ingestion)

    Only top-level files are scanned. Sub-directories are ignored — after
    Chunk 2 the corpus is intentionally flat.
    """
    samples: List[FindingSample] = []

    db_filenames = {
        row[0] for row in conn.execute("SELECT filename FROM files")
    }
    disk_filenames = {
        p.name for p in corpus_dir.glob("*.md") if p.is_file()
    }

    missing_on_disk = sorted(db_filenames - disk_filenames)
    missing_in_db = sorted(disk_filenames - db_filenames)

    if verbose and missing_on_disk:
        samples.append(
            FindingSample(
                label="db rows missing on disk",
                items=missing_on_disk[:SAMPLE_LIMIT],
            )
        )
    if verbose and missing_in_db:
        samples.append(
            FindingSample(
                label="disk files missing in db",
                items=missing_in_db[:SAMPLE_LIMIT],
            )
        )

    return len(missing_on_disk), len(missing_in_db), samples


# --------------------------------------------------------------------------
# Top-level orchestration
# --------------------------------------------------------------------------

def run_doctor(
    db_path: Path = DEFAULT_DB_PATH,
    corpus_dir: Path = DEFAULT_CORPUS_DIR,
    verbose: bool = False,
) -> DoctorResult:
    """Run every check and return a populated DoctorResult.

    Doctor opens its own raw `sqlite3.connect` rather than going through
    `db.get_connection` because (a) it must not commit anything, and
    (b) we want a single read transaction across every check so the
    whole report is consistent. We do still enable FK enforcement for
    the `PRAGMA foreign_key_check` invocation — it works either way, but
    being explicit costs nothing.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"corpus.db not found at {db_path}")
    if not corpus_dir.exists():
        raise FileNotFoundError(f"corpus dir not found at {corpus_dir}")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")

        fk_violations = check_foreign_keys(conn)

        (
            active_files,
            signals_total,
            coverage_gap_total,
            coverage_gap_thin,
            coverage_gap_substantive,
            orphan_signal_rows,
            stale_signal_rows,
            signal_samples,
        ) = check_signal_coverage(conn, verbose=verbose)

        dependent_orphans, dep_samples = check_dependent_orphans(
            conn, verbose=verbose
        )

        missing_on_disk, missing_in_db, disk_samples = check_disk_reconciliation(
            conn, corpus_dir, verbose=verbose
        )
    finally:
        conn.close()

    return DoctorResult(
        timestamp=timestamp,
        db_path=db_path,
        corpus_dir=corpus_dir,
        fk_violations=fk_violations,
        active_files=active_files,
        signals_total=signals_total,
        coverage_gap_total=coverage_gap_total,
        coverage_gap_thin=coverage_gap_thin,
        coverage_gap_substantive=coverage_gap_substantive,
        orphan_signal_rows=orphan_signal_rows,
        stale_signal_rows=stale_signal_rows,
        algorithm_version=ALGORITHM_VERSION,
        dependent_orphans=dependent_orphans,
        db_rows_missing_on_disk=missing_on_disk,
        disk_files_missing_in_db=missing_in_db,
        samples=signal_samples + dep_samples + disk_samples,
    )


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def _format_check(label: str, status: str, detail: str = "") -> str:
    """Single uniform line: '  [OK] check name : detail' or '[FAIL]'."""
    bracketed = f"[{status}]"
    base = f"  {bracketed:<8} {label}"
    if detail:
        base = f"{base}  -  {detail}"
    return base


def render_report(result: DoctorResult) -> str:
    """Build the doctor report as a single string.

    Returned as a string (not printed) so callers like the MCP startup
    hook can write the same text to a sidecar file. The CLI's
    `print_report` is a thin wrapper that just prints this.

    Layout mirrors backup.py's `print_report`: a small header, a section
    per consumer, then a footer with the overall verdict and the
    optional --verbose samples.
    """
    lines: List[str] = []
    header = "DOCTOR" if result.is_healthy else "DOCTOR (issues found)"
    lines.append(header)
    lines.append(f"  timestamp:    {result.timestamp}")
    lines.append(f"  db file:      {result.db_path}")
    lines.append(f"  corpus dir:   {result.corpus_dir}")
    lines.append("")

    # ---- Foreign-key integrity ---------------------------------------
    lines.append("  [shared]")
    if result.fk_violations:
        lines.append(_format_check(
            "PRAGMA foreign_key_check", "FAIL",
            f"{len(result.fk_violations)} violation(s)",
        ))
        for table, rowid, parent, fkid in result.fk_violations[:SAMPLE_LIMIT]:
            lines.append(f"           - {table}.rowid={rowid} -> {parent} fk={fkid}")
    else:
        lines.append(_format_check("PRAGMA foreign_key_check", "OK"))

    lines.append(_format_check(
        "files <-> data/corpus/ reconciliation",
        "OK" if (result.db_rows_missing_on_disk == 0
                 and result.disk_files_missing_in_db == 0) else "FAIL",
        f"{result.db_rows_missing_on_disk} db rows missing on disk, "
        f"{result.disk_files_missing_in_db} disk files missing in db",
    ))
    lines.append("")

    # ---- MCP-side: signal layer --------------------------------------
    lines.append("  [mcp]")
    lines.append(_format_check(
        "algorithm version",
        "OK" if result.stale_signal_rows == 0 else "FAIL",
        f"{result.algorithm_version}"
        + (f"  ({result.stale_signal_rows} stale rows)"
           if result.stale_signal_rows else ""),
    ))

    cov_pct = (
        100.0 * result.signals_total / result.active_files
        if result.active_files else 0.0
    )
    lines.append(_format_check(
        "signal coverage",
        "OK" if result.coverage_gap_substantive == 0 else "FAIL",
        f"{result.signals_total}/{result.active_files} active "
        f"({cov_pct:.1f}%)",
    ))
    lines.append(
        f"             gap total:        {result.coverage_gap_total}"
    )
    lines.append(
        f"               thin (legit):   {result.coverage_gap_thin}  "
        f"(< {MIN_SUBSTANTIVE_TURNS_FOR_SIGNALS} substantive turns)"
    )
    lines.append(
        f"               substantive:    {result.coverage_gap_substantive}  "
        f"(real coverage hole)"
    )

    lines.append(_format_check(
        "orphan signal rows",
        "OK" if result.orphan_signal_rows == 0 else "FAIL",
        f"{result.orphan_signal_rows}",
    ))

    # MCP-side dependent table (annotations)
    for table, consumer in DEPENDENT_TABLES:
        if consumer != "mcp":
            continue
        if table not in result.dependent_orphans:
            continue
        n = result.dependent_orphans[table]
        lines.append(_format_check(
            f"orphan {table} rows",
            "OK" if n == 0 else "FAIL",
            f"{n}",
        ))
    lines.append("")

    # ---- Training-side dependents ------------------------------------
    lines.append("  [training]")
    training_tables = [
        (t, c) for (t, c) in DEPENDENT_TABLES if c == "training"
    ]
    for table, _consumer in training_tables:
        if table not in result.dependent_orphans:
            lines.append(_format_check(
                f"orphan {table} rows", "skip", "table not present",
            ))
            continue
        n = result.dependent_orphans[table]
        lines.append(_format_check(
            f"orphan {table} rows",
            "OK" if n == 0 else "FAIL",
            f"{n}",
        ))
    lines.append("")

    # ---- Verdict + samples -------------------------------------------
    if result.is_healthy:
        lines.append("  verdict:      OK")
    else:
        lines.append("  verdict:      ISSUES FOUND  (exit 1)")

    if result.samples:
        lines.append("")
        lines.append("  samples:")
        for sample in result.samples:
            lines.append(f"    {sample.label}:")
            for item in sample.items:
                lines.append(f"      - {item}")

    return "\n".join(lines)


def print_report(result: DoctorResult) -> None:
    """Print the doctor report to stdout."""
    print(render_report(result))


def write_report_file(result: DoctorResult, path: Path) -> None:
    """Atomically write the doctor report to `path`.

    Used by the MCP server startup hook so the warning lands somewhere
    the user can actually see — IDEs swallow stderr from MCP server
    subprocesses, so the only reliable way to surface a warning is to
    write it to a file the user is likely to look at.

    Atomic via `.tmp` + rename, mirroring backup.py's manifest write.
    """
    text = render_report(result) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(text)
    tmp.replace(path)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only health check for corpus.db (+ data/corpus/). "
                    "Exits non-zero if any invariant is broken.",
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
        "--verbose",
        "-v",
        action="store_true",
        help=f"Print up to {SAMPLE_LIMIT} sample rows for each non-zero "
             f"finding so you can chase a specific row.",
    )
    parser.add_argument(
        "--report-file",
        type=Path,
        default=None,
        help="Also atomically write a copy of the report to this path. "
             "Used by the MCP server startup hook to drop a sidecar that "
             "the user can read even when stderr is swallowed.",
    )
    args = parser.parse_args()

    try:
        result = run_doctor(
            db_path=args.db,
            corpus_dir=args.corpus,
            verbose=args.verbose,
        )
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    print_report(result)

    if args.report_file is not None:
        write_report_file(result, args.report_file)

    return 0 if result.is_healthy else 1


if __name__ == "__main__":
    sys.exit(main())
