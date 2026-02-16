#!/usr/bin/env python3
"""
Ingest new conversations from Claude Code storage into the corpus.

Uses claude-conversation-extractor to pull conversations, deduplicates
against existing corpus, and runs the import pipeline.

Usage:
    python ingest_conversations.py                  # Sync all new conversations
    python ingest_conversations.py --recent 10     # Only last 10 sessions
    python ingest_conversations.py --dry-run       # Preview without importing
    python ingest_conversations.py --since 2026-01-04  # From specific date
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
CORPUS_DIR = PROJECT_DIR / "data" / "corpus"
METADATA_FILE = PROJECT_DIR / "metadata.json"
STATE_FILE = PROJECT_DIR / ".ingest_state.json"

# Project folders to extract from (relative to ~/Code/)
# These are matched as prefixes against decoded Claude project directory names.
# Claude encodes paths like /Users/picard/Code/qinolabs/qino-claude as
# -Users-picard-Code-qinolabs-qino-claude, and the filter decodes dashes back
# to slashes. A single "qinolabs" entry matches all qinolabs sub-projects
# via prefix matching, while excluding unrelated projects (e.g. malao).
INCLUDE_FOLDERS = [
    "qinolabs",
]


def get_session_id(filename: str) -> str | None:
    """Extract session ID from filename.

    Filename format: claude-conversation-YYYY-MM-DD-{session_id}.md
    """
    match = re.search(r'\d{4}-\d{2}-\d{2}-(.+)\.md$', filename)
    return match.group(1) if match else None


def get_existing_session_ids() -> set[str]:
    """Get set of session IDs already in corpus."""
    session_ids = set()
    for filepath in CORPUS_DIR.glob("claude-conversation-*.md"):
        session_id = get_session_id(filepath.name)
        if session_id:
            session_ids.add(session_id)
    # Also check _noise folder
    noise_dir = CORPUS_DIR / "_noise"
    if noise_dir.exists():
        for filepath in noise_dir.glob("claude-conversation-*.md"):
            session_id = get_session_id(filepath.name)
            if session_id:
                session_ids.add(session_id)
    return session_ids


def load_state() -> dict:
    """Load ingestion state (last run timestamp, etc.)."""
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state: dict):
    """Save ingestion state."""
    STATE_FILE.write_text(json.dumps(state, indent=2))


def extract_conversations(output_dir: Path, recent: int | None = None) -> list[Path]:
    """Run claude-extract to export conversations.

    Returns list of extracted file paths.
    """
    cmd = ["claude-extract", "--all", "--output", str(output_dir)]
    if recent:
        cmd = ["claude-extract", "--recent", str(recent), "--output", str(output_dir)]

    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"Error extracting: {result.stderr}")
        return []

    # Parse output to get extracted files
    extracted = list(output_dir.glob("claude-conversation-*.md"))
    return extracted


def filter_by_folder(files: list[Path], temp_dir: Path) -> list[Path]:
    """Filter extracted files to only include those from configured folders.

    We need to check the original file's project folder against INCLUDE_FOLDERS.
    Since claude-extract doesn't preserve this info, we check against Claude's storage.

    Note: claude-extract truncates UUIDs (e.g., 398f3f3a-3420-43f5-... -> 398f3f3a)
    so we match by prefix.
    """
    # Build lookup of session_id prefix -> project folder from Claude storage
    claude_projects_dir = Path.home() / ".claude" / "projects"
    session_prefix_to_folder: dict[str, str] = {}

    for project_dir in claude_projects_dir.iterdir():
        if not project_dir.is_dir() or not project_dir.name.startswith("-"):
            continue

        # Extract folder path from directory name (e.g., "-Users-picard-Code-qinolabs-qino-claude")
        folder_path = project_dir.name.replace("-", "/")[1:]  # Remove leading /
        # Simplify to relative path from ~/Code/
        if "/Code/" in folder_path:
            folder_path = folder_path.split("/Code/")[1]

        # Check if this folder is in our include list
        if not any(folder_path.startswith(inc) or inc.startswith(folder_path) for inc in INCLUDE_FOLDERS):
            continue

        # Map session ID prefixes from this project
        for session_file in project_dir.glob("*.jsonl"):
            full_id = session_file.stem
            # For UUIDs, take first segment; for agent-*, take first 8 chars after agent-
            if full_id.startswith("agent-"):
                prefix = full_id[:10]  # agent-xxxx
            else:
                prefix = full_id.split("-")[0]  # First UUID segment
            session_prefix_to_folder[prefix] = folder_path

    # Filter files by matching extracted session IDs to prefixes
    filtered = []
    for filepath in files:
        session_id = get_session_id(filepath.name)
        if session_id:
            # Try prefix match
            if session_id.startswith("agent-"):
                prefix = session_id[:10]
            else:
                prefix = session_id.split("-")[0] if "-" in session_id else session_id
            if prefix in session_prefix_to_folder:
                filtered.append(filepath)

    return filtered


def deduplicate(files: list[Path], existing_ids: set[str]) -> list[Path]:
    """Filter out files whose session IDs are already in corpus."""
    new_files = []
    for filepath in files:
        session_id = get_session_id(filepath.name)
        if session_id and session_id not in existing_ids:
            new_files.append(filepath)
    return new_files


def filter_by_date(files: list[Path], since: str) -> list[Path]:
    """Filter files to only those on or after the given date."""
    since_date = datetime.strptime(since, "%Y-%m-%d").date()
    filtered = []
    for filepath in files:
        # Extract date from filename
        match = re.search(r'(\d{4}-\d{2}-\d{2})', filepath.name)
        if match:
            file_date = datetime.strptime(match.group(1), "%Y-%m-%d").date()
            if file_date >= since_date:
                filtered.append(filepath)
    return filtered


def copy_to_corpus(files: list[Path]) -> int:
    """Copy new files to corpus directory."""
    count = 0
    for filepath in files:
        dest = CORPUS_DIR / filepath.name
        if not dest.exists():
            shutil.copy2(filepath, dest)
            count += 1
    return count


def run_pipeline():
    """Run the post-import pipeline: filter_noise, extract_metadata, import."""
    print("\n--- Running noise filter ---")
    subprocess.run(["python3", "filter_noise.py"], cwd=PROJECT_DIR)

    print("\n--- Extracting metadata ---")
    subprocess.run(["python3", "extract_metadata.py"], cwd=PROJECT_DIR)

    print("\n--- Importing to database ---")
    subprocess.run([
        "python3", "-c",
        "from pathlib import Path; from python.qino_lingo.db import import_metadata; import_metadata(Path('metadata.json'), db_path=Path('corpus.db'))"
    ], cwd=PROJECT_DIR)


def main():
    parser = argparse.ArgumentParser(description="Ingest new Claude conversations")
    parser.add_argument("--recent", type=int, help="Only extract last N sessions")
    parser.add_argument("--since", help="Only include conversations since date (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without importing")
    parser.add_argument("--skip-pipeline", action="store_true", help="Skip filter/metadata/import steps")
    args = parser.parse_args()

    # Get existing session IDs
    print("Scanning existing corpus...")
    existing_ids = get_existing_session_ids()
    print(f"Found {len(existing_ids)} existing sessions")

    # Extract to temp directory
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        print("\nExtracting conversations from Claude Code storage...")
        extracted = extract_conversations(temp_path, recent=args.recent)
        print(f"Extracted {len(extracted)} files")

        # Filter by folder
        print("\nFiltering to configured project folders...")
        filtered_by_folder = filter_by_folder(extracted, temp_path)
        print(f"Matched {len(filtered_by_folder)} files from included folders")

        # Filter by date if specified
        if args.since:
            print(f"\nFiltering to conversations since {args.since}...")
            filtered_by_folder = filter_by_date(filtered_by_folder, args.since)
            print(f"Matched {len(filtered_by_folder)} files from date filter")

        # Deduplicate
        print("\nDeduplicating against existing corpus...")
        new_files = deduplicate(filtered_by_folder, existing_ids)
        print(f"Found {len(new_files)} new conversations")

        if not new_files:
            print("\nNo new conversations to import.")
            return

        # Preview new files
        print("\nNew conversations to import:")
        for f in sorted(new_files, key=lambda x: x.name)[:20]:
            print(f"  {f.name}")
        if len(new_files) > 20:
            print(f"  ... and {len(new_files) - 20} more")

        if args.dry_run:
            print("\n[Dry run - no files copied]")
            return

        # Copy to corpus
        print(f"\nCopying {len(new_files)} files to corpus...")
        copied = copy_to_corpus(new_files)
        print(f"Copied {copied} files")

        # Update state
        state = load_state()
        state["last_ingest"] = datetime.now().isoformat()
        state["last_count"] = copied
        save_state(state)

    # Run pipeline
    if not args.skip_pipeline:
        run_pipeline()

    print("\nDone!")


if __name__ == "__main__":
    main()
