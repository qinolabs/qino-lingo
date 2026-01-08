"""
Hybrid noise filter pipeline.

Orchestrates the two-layer filtering:
1. Deterministic filter (fast, catches obvious noise)
2. ML filter (trained on labels, catches subtle patterns)

Usage:
    # Run full pipeline
    python pipeline.py --db corpus.db --corpus corpus/ --model model.pkl

    # Just deterministic filter
    python pipeline.py --db corpus.db --corpus corpus/ --deterministic-only

    # Retrain and run ML filter
    python pipeline.py --db corpus.db --corpus corpus/ --model model.pkl --retrain

    # Queue uncertain for active learning
    python pipeline.py --db corpus.db --corpus corpus/ --model model.pkl --queue-uncertain
"""

import argparse
import sqlite3
from pathlib import Path


def check_training_data(db_path: str) -> dict:
    """Check available training data."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Count noise labels
    cursor.execute("""
        SELECT COUNT(*) FROM labels WHERE notes LIKE '%[NOISE]%'
    """)
    noise_count = cursor.fetchone()[0]

    # Count signal labels (rich)
    cursor.execute("""
        SELECT COUNT(*) FROM labels WHERE is_rich = 1 AND (notes IS NULL OR notes NOT LIKE '%[NOISE]%')
    """)
    signal_count = cursor.fetchone()[0]

    conn.close()

    return {
        "noise_labels": noise_count,
        "signal_labels": signal_count,
        "total": noise_count + signal_count,
    }


def run_pipeline(
    db_path: str,
    corpus_dir: str,
    model_path: str | None = None,
    deterministic_only: bool = False,
    retrain: bool = False,
    queue_uncertain: bool = False,
    dry_run: bool = False,
):
    """Run the hybrid noise filter pipeline."""
    print("=" * 60)
    print("Hybrid Noise Filter Pipeline")
    print("=" * 60)

    # Step 1: Check training data status
    print("\n[1/4] Checking training data...")
    data_status = check_training_data(db_path)
    print(f"  Noise labels: {data_status['noise_labels']}")
    print(f"  Signal labels: {data_status['signal_labels']}")
    print(f"  Total: {data_status['total']}")

    # Step 2: Run deterministic filter
    print("\n[2/4] Running deterministic filter...")
    from deterministic import run_deterministic_filter
    run_deterministic_filter(db_path, corpus_dir, dry_run)

    if deterministic_only:
        print("\n[DONE] Deterministic filter complete (--deterministic-only)")
        return

    # Step 3: Train or load ML model
    if model_path:
        model_file = Path(model_path)

        if retrain or not model_file.exists():
            print("\n[3/4] Training ML filter...")

            if data_status["total"] < 20:
                print(f"  WARNING: Only {data_status['total']} labeled examples")
                print("  Recommend at least 50 examples for reliable training")
                print("  Skipping ML filter for now")
                print("\n  To add training data:")
                print("    1. Open qino-label at http://localhost:3008")
                print("    2. Label conversations with richness ratings")
                print("    3. Mark noise turns with 'n' key")
                return

            from train import train_noise_classifier
            metrics = train_noise_classifier(
                db_path, corpus_dir, model_path,
                test_size=0.2
            )

            if metrics is None:
                print("  Training failed - not enough data")
                return

        else:
            print(f"\n[3/4] Using existing model: {model_path}")
            print("  (Use --retrain to retrain on latest labels)")

        # Step 4: Run ML inference
        print("\n[4/4] Running ML inference...")
        from inference import run_ml_inference
        run_ml_inference(
            db_path, corpus_dir, model_path,
            low_threshold=0.3,
            high_threshold=0.7,
            queue_uncertain=queue_uncertain,
            dry_run=dry_run
        )

    else:
        print("\n[3/4] Skipping ML filter (no --model specified)")
        print("[4/4] Skipping ML inference")

    print("\n" + "=" * 60)
    print("Pipeline Complete")
    print("=" * 60)

    # Summary
    print("\nNext steps:")
    print("  1. Open qino-label to review uncertain predictions")
    print("  2. Label more examples to improve ML accuracy")
    print("  3. Re-run with --retrain after adding labels")

    if queue_uncertain:
        print("\n  Uncertain predictions have been added to the labeling queue.")


def show_stats(db_path: str):
    """Show current noise filter statistics."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("=" * 50)
    print("Noise Filter Statistics")
    print("=" * 50)

    # Training data
    data_status = check_training_data(db_path)
    print(f"\nTraining Data:")
    print(f"  Noise labels: {data_status['noise_labels']}")
    print(f"  Signal labels: {data_status['signal_labels']}")

    # Predictions
    cursor.execute("SELECT COUNT(*) FROM noise_predictions")
    total_predictions = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM noise_predictions WHERE deterministic_is_noise = 1")
    deterministic_noise = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM noise_predictions WHERE ml_is_noise = 1")
    ml_noise = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM noise_predictions WHERE ml_is_noise IS NULL AND ml_score IS NOT NULL")
    ml_uncertain = cursor.fetchone()[0]

    print(f"\nPredictions:")
    print(f"  Total turns scored: {total_predictions}")
    print(f"  Deterministic noise: {deterministic_noise}")
    print(f"  ML noise: {ml_noise}")
    print(f"  ML uncertain: {ml_uncertain}")

    # Queue
    cursor.execute("SELECT COUNT(*) FROM pending_labels WHERE source = 'ml_uncertain'")
    queued = cursor.fetchone()[0]
    print(f"\nQueued for review: {queued}")

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hybrid noise filter pipeline")
    parser.add_argument("--db", required=True, help="Path to corpus.db")
    parser.add_argument("--corpus", required=True, help="Path to corpus/ directory")
    parser.add_argument("--model", help="Path to ML model (pkl file)")
    parser.add_argument("--deterministic-only", action="store_true", help="Only run deterministic filter")
    parser.add_argument("--retrain", action="store_true", help="Retrain ML model on latest labels")
    parser.add_argument("--queue-uncertain", action="store_true", help="Add uncertain predictions to queue")
    parser.add_argument("--stats", action="store_true", help="Show statistics and exit")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to database")

    args = parser.parse_args()

    if args.stats:
        show_stats(args.db)
    else:
        run_pipeline(
            args.db, args.corpus,
            model_path=args.model,
            deterministic_only=args.deterministic_only,
            retrain=args.retrain,
            queue_uncertain=args.queue_uncertain,
            dry_run=args.dry_run
        )
