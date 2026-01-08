"""
Train ML noise filter on labeled data.

Uses:
- Labels with [NOISE] prefix as positive examples (noise)
- Labels with high richness rating as negative examples (signal)
- sentence-transformers for embeddings
- Logistic regression for classification

Usage:
    python train.py --db /path/to/corpus.db --corpus /path/to/corpus/ --output model.pkl
"""

import argparse
import pickle
import sqlite3
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix


def get_embedding_model():
    """Load sentence-transformers model."""
    try:
        from sentence_transformers import SentenceTransformer
        # all-MiniLM-L6-v2 is fast and good for this task
        return SentenceTransformer("all-MiniLM-L6-v2")
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


def load_training_data(db_path: str, corpus_dir: str) -> tuple[list[str], list[int]]:
    """
    Load training data from labels table.

    Returns:
        (texts, labels) where label=1 is noise, label=0 is signal
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    texts = []
    labels = []

    # Get noise labels (notes contains [NOISE])
    cursor.execute("""
        SELECT l.file_id, l.turn_start, l.turn_end, l.notes, f.filename, f.source_path
        FROM labels l
        JOIN files f ON l.file_id = f.id
        WHERE l.notes LIKE '%[NOISE]%'
    """)
    noise_labels = cursor.fetchall()
    print(f"Found {len(noise_labels)} noise-labeled ranges")

    # Get signal labels (rich conversations, rating >= 4 / is_rich = true)
    cursor.execute("""
        SELECT l.file_id, l.turn_start, l.turn_end, l.notes, f.filename, f.source_path
        FROM labels l
        JOIN files f ON l.file_id = f.id
        WHERE l.is_rich = 1 AND (l.notes IS NULL OR l.notes NOT LIKE '%[NOISE]%')
    """)
    signal_labels = cursor.fetchall()
    print(f"Found {len(signal_labels)} signal-labeled ranges")

    # Process noise labels
    for row in noise_labels:
        filepath = Path(row["source_path"]) if row["source_path"] else Path(corpus_dir) / row["filename"]
        if not filepath.exists():
            filepath = Path(corpus_dir) / row["filename"]
            if not filepath.exists():
                continue

        turns = parse_conversation(filepath)
        turn_start = row["turn_start"] if row["turn_start"] is not None else 0
        turn_end = row["turn_end"] if row["turn_end"] is not None else len(turns) - 1

        for idx in range(turn_start, min(turn_end + 1, len(turns))):
            content = turns[idx]["content"]
            if content.strip():
                texts.append(content)
                labels.append(1)  # noise

    # Process signal labels
    for row in signal_labels:
        filepath = Path(row["source_path"]) if row["source_path"] else Path(corpus_dir) / row["filename"]
        if not filepath.exists():
            filepath = Path(corpus_dir) / row["filename"]
            if not filepath.exists():
                continue

        turns = parse_conversation(filepath)
        turn_start = row["turn_start"] if row["turn_start"] is not None else 0
        turn_end = row["turn_end"] if row["turn_end"] is not None else len(turns) - 1

        for idx in range(turn_start, min(turn_end + 1, len(turns))):
            content = turns[idx]["content"]
            if content.strip():
                texts.append(content)
                labels.append(0)  # signal

    conn.close()
    return texts, labels


def train_noise_classifier(
    db_path: str,
    corpus_dir: str,
    output_path: str,
    test_size: float = 0.2
):
    """Train and save the noise classifier."""
    print("Loading training data...")
    texts, labels = load_training_data(db_path, corpus_dir)

    if len(texts) < 10:
        print(f"ERROR: Not enough training data ({len(texts)} examples)")
        print("Need at least 10 labeled examples to train.")
        print("\nTo add training data:")
        print("  1. Label conversations in qino-label")
        print("  2. Mark noise turns with 'n' key")
        print("  3. Mark rich content with high ratings (4-5)")
        return

    print(f"\nTotal examples: {len(texts)}")
    print(f"  Noise: {sum(labels)}")
    print(f"  Signal: {len(labels) - sum(labels)}")

    # Check class balance
    noise_ratio = sum(labels) / len(labels)
    if noise_ratio < 0.1 or noise_ratio > 0.9:
        print(f"\nWARNING: Class imbalance ({noise_ratio:.1%} noise)")
        print("Consider labeling more of the minority class.")

    # Load embedding model
    print("\nLoading embedding model...")
    embed_model = get_embedding_model()

    # Generate embeddings
    print("Generating embeddings...")
    embeddings = embed_model.encode(
        texts,
        show_progress_bar=True,
        batch_size=32
    )

    # Split data
    X_train, X_test, y_train, y_test = train_test_split(
        embeddings, labels,
        test_size=test_size,
        random_state=42,
        stratify=labels
    )

    print(f"\nTraining set: {len(X_train)} examples")
    print(f"Test set: {len(X_test)} examples")

    # Train classifier
    print("\nTraining classifier...")
    classifier = LogisticRegression(
        max_iter=1000,
        class_weight="balanced",  # Handle imbalance
        random_state=42
    )
    classifier.fit(X_train, y_train)

    # Evaluate
    print("\nEvaluating...")
    y_pred = classifier.predict(X_test)
    y_prob = classifier.predict_proba(X_test)[:, 1]

    print("\nClassification Report:")
    print(classification_report(y_test, y_pred, target_names=["signal", "noise"]))

    print("Confusion Matrix:")
    print(confusion_matrix(y_test, y_pred))

    # Save model
    print(f"\nSaving model to {output_path}...")
    model_data = {
        "classifier": classifier,
        "embedding_model_name": "all-MiniLM-L6-v2",
        "training_examples": len(texts),
        "noise_examples": sum(labels),
        "signal_examples": len(labels) - sum(labels),
    }

    with open(output_path, "wb") as f:
        pickle.dump(model_data, f)

    print("Done!")

    # Return metrics for reporting
    return {
        "accuracy": (y_pred == y_test).mean(),
        "noise_examples": sum(labels),
        "signal_examples": len(labels) - sum(labels),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train ML noise filter")
    parser.add_argument("--db", required=True, help="Path to corpus.db")
    parser.add_argument("--corpus", required=True, help="Path to corpus/ directory")
    parser.add_argument("--output", default="noise_model.pkl", help="Output model path")
    parser.add_argument("--test-size", type=float, default=0.2, help="Test set fraction")

    args = parser.parse_args()
    train_noise_classifier(args.db, args.corpus, args.output, args.test_size)
