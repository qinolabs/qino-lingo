"""
Export labeled data for training and validation.
"""

import json
import sqlite3
from pathlib import Path
from typing import Iterator

from .types import LabeledTurn


# Default paths
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
DB_PATH = PROJECT_ROOT / "corpus.db"
CORPUS_DIR = PROJECT_ROOT / "data" / "corpus"


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Get database connection with row factory."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def parse_conversation(filepath: Path) -> list[dict]:
    """Parse a conversation file into turns."""
    content = filepath.read_text(encoding="utf-8", errors="replace")
    turns = []
    current_role = None
    current_content = []
    turn_index = 0

    for line in content.split("\n"):
        if line.startswith("## Human") or line.startswith("## User") or line.startswith("## 👤"):
            if current_role and current_content:
                turns.append({
                    "index": turn_index,
                    "role": current_role,
                    "content": "\n".join(current_content).strip()
                })
                turn_index += 1
            current_role = "human"
            current_content = []
        elif line.startswith("## Assistant") or line.startswith("## Claude") or line.startswith("## 🤖"):
            if current_role and current_content:
                turns.append({
                    "index": turn_index,
                    "role": current_role,
                    "content": "\n".join(current_content).strip()
                })
                turn_index += 1
            current_role = "assistant"
            current_content = []
        elif current_role:
            current_content.append(line)

    if current_role and current_content:
        turns.append({
            "index": turn_index,
            "role": current_role,
            "content": "\n".join(current_content).strip()
        })

    return turns


def export_labeled_turns(
    db_path: Path = DB_PATH,
    corpus_dir: Path = CORPUS_DIR,
    rating_filter: int | None = None,
    role_filter: str | None = None,
) -> list[LabeledTurn]:
    """
    Export labeled turns from the database.

    Args:
        db_path: Path to corpus.db
        corpus_dir: Path to conversation files
        rating_filter: Only include turns with this rating (1/2/3)
        role_filter: Only include turns with this role ("human"/"assistant")

    Returns:
        List of LabeledTurn objects
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    # Get all labels with file info
    query = """
        SELECT l.id, l.file_id, l.turn_start, l.turn_end, l.rating, l.tags, l.notes,
               f.filename, f.source_path
        FROM labels l
        JOIN files f ON l.file_id = f.id
    """
    if rating_filter is not None:
        query += f" WHERE l.rating = {rating_filter}"

    cursor.execute(query)
    labels = cursor.fetchall()
    conn.close()

    labeled_turns = []

    for label in labels:
        # Find the conversation file
        filepath = Path(label["source_path"]) if label["source_path"] else corpus_dir / label["filename"]
        if not filepath.exists():
            filepath = corpus_dir / label["filename"]
            if not filepath.exists():
                continue

        # Parse conversation
        turns = parse_conversation(filepath)

        # Get turn range
        turn_start = label["turn_start"] if label["turn_start"] is not None else 0
        turn_end = label["turn_end"] if label["turn_end"] is not None else len(turns) - 1

        # Parse tags
        tags = json.loads(label["tags"]) if label["tags"] else []

        # Extract each turn in the labeled range
        for idx in range(turn_start, min(turn_end + 1, len(turns))):
            turn = turns[idx]

            # Apply role filter
            if role_filter and turn["role"] != role_filter:
                continue

            labeled_turns.append(LabeledTurn(
                file_id=label["file_id"],
                filename=label["filename"],
                turn_index=idx,
                role=turn["role"],
                content=turn["content"],
                rating=label["rating"],
                tags=tags,
                notes=label["notes"],
            ))

    return labeled_turns


def export_by_rating(
    db_path: Path = DB_PATH,
    corpus_dir: Path = CORPUS_DIR,
) -> dict[str, list[LabeledTurn]]:
    """
    Export labeled turns grouped by rating.

    Returns:
        Dict with keys "thin", "functional", "rich" containing LabeledTurn lists
    """
    all_turns = export_labeled_turns(db_path, corpus_dir)

    return {
        "thin": [t for t in all_turns if t.rating == 1],
        "functional": [t for t in all_turns if t.rating == 2],
        "rich": [t for t in all_turns if t.rating == 3],
    }


def get_label_stats(db_path: Path = DB_PATH) -> dict:
    """Get statistics about current labels."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    # Total labels
    cursor.execute("SELECT COUNT(*) FROM labels")
    total = cursor.fetchone()[0]

    # By rating
    cursor.execute("SELECT rating, COUNT(*) FROM labels GROUP BY rating")
    by_rating = {row[0]: row[1] for row in cursor.fetchall()}

    conn.close()

    return {
        "total_labels": total,
        "thin": by_rating.get(1, 0),
        "functional": by_rating.get(2, 0),
        "rich": by_rating.get(3, 0),
    }


if __name__ == "__main__":
    # Quick test
    stats = get_label_stats()
    print(f"Label stats: {stats}")

    turns = export_labeled_turns()
    print(f"Exported {len(turns)} labeled turns")

    by_rating = export_by_rating()
    for tier, tier_turns in by_rating.items():
        print(f"  {tier}: {len(tier_turns)} turns")
