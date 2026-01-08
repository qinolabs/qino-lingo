"""
Deterministic noise filter for conversation corpus.

Applies rule-based heuristics to identify noise turns:
- Command outputs (tool results, bash output)
- System messages
- Very short turns (acknowledgments)
- File path listings
- Error stacktraces
- Empty or whitespace-only turns

Usage:
    python deterministic.py --db /path/to/corpus.db --corpus /path/to/corpus/
"""

import argparse
import re
import sqlite3
from pathlib import Path
from datetime import datetime


# =============================================================================
# Noise Detection Patterns
# =============================================================================

COMMAND_OUTPUT_PATTERNS = [
    r"^```(?:bash|shell|console|terminal)",  # Code blocks with shell type
    r"^\$\s+\w+",  # Shell prompts
    r"^>\s+\w+",  # PowerShell/cmd prompts
    r"^npm\s+(warn|ERR!|notice)",  # npm output
    r"^(PASS|FAIL)\s+",  # Test output
    r"^\[\d+:\d+:\d+\]",  # Timestamp logs
    r"^(error|warning|info|debug):",  # Log levels
    r"^at\s+\w+.*\(.*:\d+:\d+\)",  # Stack traces
]

SYSTEM_MESSAGE_PATTERNS = [
    r"^<system",  # System tags
    r"^<",  # Anthropic internal tags
    r"^<function_",  # Function call markers
    r"^Tool result:",  # Tool results
    r"^Running command:",  # Command execution
]

FILE_LISTING_PATTERNS = [
    r"^[-drwx]{10}",  # Unix ls -l output
    r"^\s*\d+\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)",  # ls date format
    r"^[A-Z]:\\",  # Windows paths
    r"^(/[\w.-]+)+/?$",  # Unix absolute paths (line is just a path)
    r"^\s*├──\s+",  # Tree output
    r"^\s*└──\s+",  # Tree output
]

MINIMAL_CONTENT_PATTERNS = [
    r"^(ok|okay|yes|no|sure|thanks|thank you|got it|done|k|y|n)\.?$",
    r"^(understood|perfect|great|cool|nice|good|right|correct)\.?$",
    r"^\.\.\.$",  # Ellipsis only
    r"^[.!?]+$",  # Punctuation only
]


def is_noise_turn(content: str, role: str) -> tuple[bool, str | None]:
    """
    Check if a turn is noise based on deterministic rules.

    Returns:
        (is_noise, reason) - reason is None if not noise
    """
    # Normalize content
    content = content.strip()

    # Empty or whitespace-only
    if not content:
        return True, "empty"

    # Very short content (less than 10 chars, excluding punctuation)
    clean = re.sub(r"[^\w\s]", "", content)
    if len(clean) < 10:
        # Check if it's a minimal acknowledgment
        for pattern in MINIMAL_CONTENT_PATTERNS:
            if re.match(pattern, content.lower()):
                return True, "minimal_acknowledgment"

    # Command output patterns (check first few lines)
    lines = content.split("\n")
    first_lines = "\n".join(lines[:5])

    for pattern in COMMAND_OUTPUT_PATTERNS:
        if re.search(pattern, first_lines, re.MULTILINE | re.IGNORECASE):
            return True, "command_output"

    # System message patterns
    for pattern in SYSTEM_MESSAGE_PATTERNS:
        if re.search(pattern, first_lines, re.MULTILINE | re.IGNORECASE):
            return True, "system_message"

    # File listing patterns (if most lines match)
    file_listing_lines = 0
    for line in lines[:20]:  # Check first 20 lines
        for pattern in FILE_LISTING_PATTERNS:
            if re.match(pattern, line.strip()):
                file_listing_lines += 1
                break

    if len(lines) > 5 and file_listing_lines / min(len(lines), 20) > 0.5:
        return True, "file_listing"

    # Very long content that's mostly code/output (high line count, low word diversity)
    if len(lines) > 50:
        # Check if it's mostly a code dump
        code_block_count = content.count("```")
        if code_block_count >= 2:
            # Has code blocks - check ratio
            total_len = len(content)
            code_content = 0
            in_block = False
            for line in lines:
                if line.strip().startswith("```"):
                    in_block = not in_block
                elif in_block:
                    code_content += len(line) + 1

            if code_content / total_len > 0.8:
                return True, "code_dump"

    return False, None


def parse_conversation(filepath: Path) -> list[dict]:
    """Parse a conversation file into turns."""
    content = filepath.read_text(encoding="utf-8", errors="replace")
    turns = []
    current_role = None
    current_content = []

    for line in content.split("\n"):
        # Detect role changes
        if (
            line.startswith("## Human")
            or line.startswith("## User")
            or line.startswith("## 👤")
        ):
            if current_role and current_content:
                turns.append({
                    "role": current_role,
                    "content": "\n".join(current_content).strip()
                })
            current_role = "human"
            current_content = []
        elif (
            line.startswith("## Assistant")
            or line.startswith("## Claude")
            or line.startswith("## 🤖")
        ):
            if current_role and current_content:
                turns.append({
                    "role": current_role,
                    "content": "\n".join(current_content).strip()
                })
            current_role = "assistant"
            current_content = []
        elif current_role:
            current_content.append(line)

    # Don't forget the last turn
    if current_role and current_content:
        turns.append({
            "role": current_role,
            "content": "\n".join(current_content).strip()
        })

    return turns


def run_deterministic_filter(db_path: str, corpus_dir: str, dry_run: bool = False):
    """
    Run the deterministic noise filter on all conversations.

    Args:
        db_path: Path to corpus.db
        corpus_dir: Path to corpus/ directory with conversation files
        dry_run: If True, don't write to database
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Ensure noise_predictions table exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS noise_predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL,
            turn_idx INTEGER NOT NULL,
            deterministic_is_noise INTEGER,
            deterministic_reason TEXT,
            ml_score REAL,
            ml_is_noise INTEGER,
            human_label INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT,
            FOREIGN KEY (file_id) REFERENCES files(id),
            UNIQUE(file_id, turn_idx)
        )
    """)

    # Get all files
    cursor.execute("""
        SELECT id, filename, source_path
        FROM files
        WHERE status = 'active'
    """)
    files = cursor.fetchall()

    print(f"Processing {len(files)} files...")

    stats = {
        "files_processed": 0,
        "turns_processed": 0,
        "noise_turns": 0,
        "reasons": {}
    }

    for file_row in files:
        file_id = file_row["id"]
        filename = file_row["filename"]
        source_path = file_row["source_path"]

        # Find the conversation file
        if source_path:
            filepath = Path(source_path)
        else:
            filepath = Path(corpus_dir) / filename

        if not filepath.exists():
            # Try without subdirectory
            filepath = Path(corpus_dir) / filename
            if not filepath.exists():
                print(f"  [SKIP] {filename} - file not found")
                continue

        # Parse conversation
        turns = parse_conversation(filepath)
        stats["files_processed"] += 1

        # Check each turn
        for turn_idx, turn in enumerate(turns):
            stats["turns_processed"] += 1
            is_noise, reason = is_noise_turn(turn["content"], turn["role"])

            if is_noise:
                stats["noise_turns"] += 1
                stats["reasons"][reason] = stats["reasons"].get(reason, 0) + 1

                if not dry_run:
                    # Insert or update prediction
                    cursor.execute("""
                        INSERT INTO noise_predictions
                            (file_id, turn_idx, deterministic_is_noise, deterministic_reason, created_at)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(file_id, turn_idx) DO UPDATE SET
                            deterministic_is_noise = excluded.deterministic_is_noise,
                            deterministic_reason = excluded.deterministic_reason,
                            updated_at = ?
                    """, (
                        file_id, turn_idx, 1, reason,
                        datetime.now().isoformat(),
                        datetime.now().isoformat()
                    ))

    if not dry_run:
        conn.commit()

    conn.close()

    # Print stats
    print("\n" + "=" * 50)
    print("Deterministic Filter Results")
    print("=" * 50)
    print(f"Files processed: {stats['files_processed']}")
    print(f"Turns processed: {stats['turns_processed']}")
    print(f"Noise turns found: {stats['noise_turns']} ({stats['noise_turns']/max(stats['turns_processed'],1)*100:.1f}%)")
    print("\nNoise by reason:")
    for reason, count in sorted(stats["reasons"].items(), key=lambda x: -x[1]):
        print(f"  {reason}: {count}")

    if dry_run:
        print("\n[DRY RUN - no changes written]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run deterministic noise filter")
    parser.add_argument("--db", required=True, help="Path to corpus.db")
    parser.add_argument("--corpus", required=True, help="Path to corpus/ directory")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to database")

    args = parser.parse_args()
    run_deterministic_filter(args.db, args.corpus, args.dry_run)
