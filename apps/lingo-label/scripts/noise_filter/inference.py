"""
Apply trained ML noise filter to unlabeled turns.

Scores each turn with the ML model and writes predictions to noise_predictions table.
Uncertain predictions (score between thresholds) can be queued for human review.

Usage:
    python inference.py --db /path/to/corpus.db --corpus /path/to/corpus/ --model model.pkl
    python inference.py --db /path/to/corpus.db --corpus /path/to/corpus/ --model model.pkl --queue-uncertain
"""

import argparse
import pickle
import sqlite3
from datetime import datetime
from pathlib import Path


def get_embedding_model(model_name: str):
    """Load sentence-transformers model."""
    try:
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(model_name)
    except ImportError:
        print("ERROR: sentence-transformers not installed")
        print("Run: pip install sentence-transformers")
        exit(1)


def parse_conversation(filepath: Path) -> list[dict]:
    """Parse a conversation file into turns."""
    content = filepath.read_text(encoding="utf-8", errors="replace")
    turns = []
    current_role = None
    current_content = []

    for line in content.split("\n"):
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

    if current_role and current_content:
        turns.append({
            "role": current_role,
            "content": "\n".join(current_content).strip()
        })

    return turns


def run_ml_inference(
    db_path: str,
    corpus_dir: str,
    model_path: str,
    low_threshold: float = 0.3,
    high_threshold: float = 0.7,
    queue_uncertain: bool = False,
    dry_run: bool = False
):
    """
    Run ML noise filter inference on all turns.

    Args:
        db_path: Path to corpus.db
        corpus_dir: Path to corpus/ directory
        model_path: Path to trained model pickle
        low_threshold: Below this = signal
        high_threshold: Above this = noise
        queue_uncertain: Add uncertain predictions to pending_labels
        dry_run: Don't write to database
    """
    # Load model
    print(f"Loading model from {model_path}...")
    with open(model_path, "rb") as f:
        model_data = pickle.load(f)

    classifier = model_data["classifier"]
    embedding_model_name = model_data["embedding_model_name"]

    print(f"Model trained on {model_data['training_examples']} examples")
    print(f"  Noise: {model_data['noise_examples']}")
    print(f"  Signal: {model_data['signal_examples']}")

    # Load embedding model
    print(f"\nLoading embedding model ({embedding_model_name})...")
    embed_model = get_embedding_model(embedding_model_name)

    # Connect to database. Schema authority lives in
    # python/qino_lingo/migrations/ — both noise_predictions and
    # pending_labels FK on filename after Chunk 1.
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()

    # Get all files
    cursor.execute("""
        SELECT filename, source_path
        FROM files
        WHERE status = 'active'
    """)
    files = cursor.fetchall()

    print(f"\nProcessing {len(files)} files...")

    stats = {
        "files_processed": 0,
        "turns_processed": 0,
        "noise_predicted": 0,
        "signal_predicted": 0,
        "uncertain": 0,
        "queued": 0,
    }

    for file_row in files:
        filename = file_row["filename"]
        source_path = file_row["source_path"]

        # Find the conversation file
        if source_path:
            filepath = Path(source_path)
        else:
            filepath = Path(corpus_dir) / filename

        if not filepath.exists():
            filepath = Path(corpus_dir) / filename
            if not filepath.exists():
                continue

        # Parse conversation
        turns = parse_conversation(filepath)
        if not turns:
            continue

        stats["files_processed"] += 1

        # Get turn contents
        turn_texts = [t["content"] for t in turns if t["content"].strip()]
        if not turn_texts:
            continue

        # Generate embeddings in batch
        embeddings = embed_model.encode(turn_texts, show_progress_bar=False)

        # Get predictions
        scores = classifier.predict_proba(embeddings)[:, 1]

        # Process each turn
        text_idx = 0
        uncertain_turns = []

        for turn_idx, turn in enumerate(turns):
            if not turn["content"].strip():
                continue

            score = float(scores[text_idx])
            text_idx += 1
            stats["turns_processed"] += 1

            # Classify based on thresholds
            if score < low_threshold:
                is_noise = False
                stats["signal_predicted"] += 1
            elif score > high_threshold:
                is_noise = True
                stats["noise_predicted"] += 1
            else:
                is_noise = None  # uncertain
                stats["uncertain"] += 1
                uncertain_turns.append(turn_idx)

            if not dry_run:
                # Insert or update prediction
                cursor.execute("""
                    INSERT INTO noise_predictions
                        (filename, turn_idx, ml_score, ml_is_noise, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(filename, turn_idx) DO UPDATE SET
                        ml_score = excluded.ml_score,
                        ml_is_noise = excluded.ml_is_noise,
                        updated_at = ?
                """, (
                    filename, turn_idx, score,
                    1 if is_noise else (0 if is_noise is False else None),
                    datetime.now().isoformat(),
                    datetime.now().isoformat()
                ))

        # Queue uncertain turns for review
        if queue_uncertain and uncertain_turns and not dry_run:
            # Check if already in queue
            cursor.execute("""
                SELECT filename FROM pending_labels WHERE filename = ?
            """, (filename,))
            if not cursor.fetchone():
                # Add to queue with context about uncertain turns
                start_turn = min(uncertain_turns)
                end_turn = max(uncertain_turns)
                cursor.execute("""
                    INSERT INTO pending_labels
                        (filename, turn_start, turn_end, source, context, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    filename, start_turn, end_turn,
                    "ml_uncertain",
                    f"ML uncertain on {len(uncertain_turns)} turns (scores {low_threshold}-{high_threshold})",
                    datetime.now().isoformat()
                ))
                stats["queued"] += 1

    if not dry_run:
        conn.commit()

    conn.close()

    # Print stats
    print("\n" + "=" * 50)
    print("ML Inference Results")
    print("=" * 50)
    print(f"Files processed: {stats['files_processed']}")
    print(f"Turns processed: {stats['turns_processed']}")
    print(f"Predicted noise: {stats['noise_predicted']} ({stats['noise_predicted']/max(stats['turns_processed'],1)*100:.1f}%)")
    print(f"Predicted signal: {stats['signal_predicted']} ({stats['signal_predicted']/max(stats['turns_processed'],1)*100:.1f}%)")
    print(f"Uncertain: {stats['uncertain']} ({stats['uncertain']/max(stats['turns_processed'],1)*100:.1f}%)")

    if queue_uncertain:
        print(f"\nConversations queued for review: {stats['queued']}")

    if dry_run:
        print("\n[DRY RUN - no changes written]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run ML noise filter inference")
    parser.add_argument("--db", required=True, help="Path to corpus.db")
    parser.add_argument("--corpus", required=True, help="Path to corpus/ directory")
    parser.add_argument("--model", required=True, help="Path to trained model")
    parser.add_argument("--low-threshold", type=float, default=0.3, help="Below = signal")
    parser.add_argument("--high-threshold", type=float, default=0.7, help="Above = noise")
    parser.add_argument("--queue-uncertain", action="store_true", help="Add uncertain to queue")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to database")

    args = parser.parse_args()
    run_ml_inference(
        args.db, args.corpus, args.model,
        args.low_threshold, args.high_threshold,
        args.queue_uncertain, args.dry_run
    )
