#!/usr/bin/env python3
"""Filter obvious noise from conversation files.

Walks the active subset of the corpus and reclassifies obvious noise
by setting files.status = 'noise' in the db. After Chunk 2, files are
no longer physically moved into a _noise/ subdirectory — every
conversation lives at the top level of data/corpus/ and the
active/noise distinction is purely a db column.

Usage:
    python filter_noise.py              # apply
    python filter_noise.py --dry-run    # report what would be reclassified
"""

import argparse
import re
import sys
from pathlib import Path

# Bring the package on the path so we can use the project's db helpers.
PROJECT_DIR = Path(__file__).parent
sys.path.insert(0, str(PROJECT_DIR))

from python.qino_lingo.db import get_connection, DEFAULT_DB_PATH  # noqa: E402

CORPUS_DIR = PROJECT_DIR / "data" / "corpus"


def count_pattern(text: str, pattern: str) -> int:
    return len(re.findall(pattern, text, re.MULTILINE))


def is_noise(filepath: Path) -> tuple[bool, str | None]:
    """Determine if a file is clearly noise.

    Returns (is_noise, reason). The reason string is used for digest
    output and not stored in the db (status='noise' is the only
    persistent classification).
    """
    text = filepath.read_text()
    size = filepath.stat().st_size

    user_turns = count_pattern(text, r'^## 👤 User$')
    claude_turns = count_pattern(text, r'^## 🤖 Claude$')

    # Count substantive user content (not just command tags)
    user_sections = re.split(r'^## 👤 User$', text, flags=re.MULTILINE)[1:]
    substantive_user = 0
    for section in user_sections:
        lines = section.strip().split('\n')
        for line in lines:
            line = line.strip()
            if line and not line.startswith('<') and not line.startswith('---') and line != 'Caveat:':
                if len(line) > 20 and not line.startswith('Caveat:'):
                    substantive_user += 1
                    break

    # 1. Very small files with no Claude response
    if size < 1000 and claude_turns == 0:
        return True, "under 1KB, no Claude response"

    # 2. Files with only /clear or /exit commands
    if '<command-name>/clear</command-name>' in text or '<command-name>/exit</command-name>' in text:
        if substantive_user == 0 and claude_turns <= 1:
            return True, "only clear/exit commands"

    # 3. Agent warmup files with minimal exchange
    if 'agent-' in filepath.name and size < 1500:
        if user_turns <= 2 and claude_turns <= 1:
            if 'Warmup' in text or "I'm ready to help" in text:
                if substantive_user == 0:
                    return True, "agent warmup only"

    # 4. No substantive user input (only commands, no real dialogue)
    if substantive_user == 0 and claude_turns > 0:
        return True, "no substantive user input"

    # 5. Pure transactional: only "commit" commands with no conceptual exchange
    if size < 3000:
        transactional_patterns = [
            r'commit (all|the|these|changes)',
            r'^commit\s*$',
            r'/update-qino-tools',
            r'git (add|commit|push|status)',
        ]
        is_transactional = any(re.search(p, text, re.IGNORECASE | re.MULTILINE) for p in transactional_patterns)

        conceptual_markers = [
            r'what (makes|does|is|should|would|could)',
            r'how (can|do|should|would|could)',
            r'why (does|is|should|would)',
            r'the essence of',
            r'something about',
            r'i\'ve been thinking',
            r'let\'s (explore|think|consider)',
        ]
        has_conceptual = any(re.search(p, text, re.IGNORECASE) for p in conceptual_markers)

        if is_transactional and not has_conceptual and claude_turns <= 3:
            return True, "pure transactional"

    return False, None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reclassify obvious noise in the corpus by setting files.status='noise'.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be reclassified without modifying the db.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Path to corpus.db (default: {DEFAULT_DB_PATH})",
    )
    args = parser.parse_args()

    # Walk the active subset only — noise files are already classified.
    with get_connection(args.db) as conn:
        rows = conn.execute(
            "SELECT filename FROM files WHERE status = 'active'"
        ).fetchall()
        active_filenames = [r[0] for r in rows]

    print(f"Scanning {len(active_filenames)} active files...")

    reclassified = []
    reasons: dict[str, int] = {}
    missing = 0

    for filename in active_filenames:
        filepath = CORPUS_DIR / filename
        if not filepath.exists():
            missing += 1
            continue
        try:
            is_noise_file, reason = is_noise(filepath)
        except Exception as e:
            print(f"  [ERROR] {filename}: {e}")
            continue
        if is_noise_file:
            reclassified.append((filename, reason))
            reasons[reason or "unknown"] = reasons.get(reason or "unknown", 0) + 1

    if args.dry_run:
        print(f"\nDRY RUN — would reclassify {len(reclassified)} files as noise")
    else:
        with get_connection(args.db) as conn:
            for filename, _reason in reclassified:
                conn.execute(
                    "UPDATE files SET status = 'noise' WHERE filename = ?",
                    (filename,),
                )
        print(f"\nReclassified {len(reclassified)} files as noise")

    if reasons:
        print("\nBreakdown:")
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"  {reason}: {count}")

    if missing:
        print(f"\n{missing} active db rows have no file on disk (Chunk 4 will reconcile these as 'missing')")

    return 0


if __name__ == "__main__":
    sys.exit(main())
