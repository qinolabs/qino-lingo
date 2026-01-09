"""
Validation 01: Training Data Signal

Hypothesis: Labeled conversation turns contain sufficient signal to train
a model that distinguishes quality tiers.

Experiments:
1. Data distribution analysis
2. Embedding cluster separation
3. Probe classifier accuracy
"""

import json
import sys
import time
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.types import ValidationResult, ValidationReport
from lib.export import export_by_rating, get_label_stats, DB_PATH, CORPUS_DIR

# Minimum requirements
MIN_TOTAL_LABELS = 30
MIN_PER_TIER = 5
MIN_SILHOUETTE = 0.3
MIN_ACCURACY = 0.70
MIN_CLASS_RECALL = 0.50


def check_data_sufficiency() -> ValidationResult:
    """Check if we have enough labeled data to proceed."""
    start = time.time()

    stats = get_label_stats()
    total = stats["total_labels"]
    thin = stats["thin"]
    functional = stats["functional"]
    rich = stats["rich"]

    passed = (
        total >= MIN_TOTAL_LABELS
        and thin >= MIN_PER_TIER
        and functional >= MIN_PER_TIER
        and rich >= MIN_PER_TIER
    )

    output = f"""Data Sufficiency Check
----------------------
Total labels: {total} (need ≥{MIN_TOTAL_LABELS})
Thin (1): {thin} (need ≥{MIN_PER_TIER})
Functional (2): {functional} (need ≥{MIN_PER_TIER})
Rich (3): {rich} (need ≥{MIN_PER_TIER})

Status: {"PASS" if passed else "FAIL - Need more labels"}
"""

    return ValidationResult(
        name="Data sufficiency",
        passed=passed,
        output=output,
        duration_ms=int((time.time() - start) * 1000),
        metadata=stats,
    )


def analyze_distributions() -> ValidationResult:
    """Analyze data distributions across tiers."""
    start = time.time()

    by_rating = export_by_rating()

    def compute_stats(turns):
        if not turns:
            return {"count": 0, "avg_length": 0, "avg_words": 0}

        lengths = [len(t.content) for t in turns]
        word_counts = [len(t.content.split()) for t in turns]

        return {
            "count": len(turns),
            "avg_length": sum(lengths) / len(lengths),
            "avg_words": sum(word_counts) / len(word_counts),
        }

    tier_stats = {
        "thin": compute_stats(by_rating["thin"]),
        "functional": compute_stats(by_rating["functional"]),
        "rich": compute_stats(by_rating["rich"]),
    }

    # Check for meaningful differences
    # Rich should generally be longer/more substantial than thin
    thin_words = tier_stats["thin"]["avg_words"]
    rich_words = tier_stats["rich"]["avg_words"]

    has_difference = (
        tier_stats["thin"]["count"] > 0
        and tier_stats["rich"]["count"] > 0
        and rich_words > thin_words * 1.2  # Rich at least 20% more words
    )

    output = f"""Distribution Analysis
---------------------
Thin (1):
  Count: {tier_stats['thin']['count']}
  Avg chars: {tier_stats['thin']['avg_length']:.0f}
  Avg words: {tier_stats['thin']['avg_words']:.0f}

Functional (2):
  Count: {tier_stats['functional']['count']}
  Avg chars: {tier_stats['functional']['avg_length']:.0f}
  Avg words: {tier_stats['functional']['avg_words']:.0f}

Rich (3):
  Count: {tier_stats['rich']['count']}
  Avg chars: {tier_stats['rich']['avg_length']:.0f}
  Avg words: {tier_stats['rich']['avg_words']:.0f}

Status: {"PASS - Meaningful differences found" if has_difference else "NEEDS REVIEW - Check distributions manually"}
"""

    return ValidationResult(
        name="Distribution analysis",
        passed=has_difference,
        output=output,
        duration_ms=int((time.time() - start) * 1000),
        metadata=tier_stats,
    )


def compute_embedding_separation() -> ValidationResult:
    """Compute embedding cluster separation using silhouette score."""
    start = time.time()

    try:
        from sentence_transformers import SentenceTransformer
        from sklearn.metrics import silhouette_score
        import numpy as np
    except ImportError as e:
        return ValidationResult(
            name="Embedding separation",
            passed=False,
            error=f"Missing dependency: {e}. Run: pip install sentence-transformers scikit-learn",
            duration_ms=int((time.time() - start) * 1000),
        )

    by_rating = export_by_rating()

    # Collect all turns with labels
    texts = []
    labels = []
    for rating, turns in [(1, by_rating["thin"]), (2, by_rating["functional"]), (3, by_rating["rich"])]:
        for turn in turns:
            if turn.content.strip():
                texts.append(turn.content)
                labels.append(rating)

    if len(texts) < 10:
        return ValidationResult(
            name="Embedding separation",
            passed=False,
            output=f"Not enough data: {len(texts)} turns (need ≥10)",
            duration_ms=int((time.time() - start) * 1000),
        )

    # Generate embeddings
    print("Loading embedding model...")
    model = SentenceTransformer("all-MiniLM-L6-v2")

    print(f"Embedding {len(texts)} turns...")
    embeddings = model.encode(texts, show_progress_bar=True)

    # Compute silhouette score
    labels_array = np.array(labels)
    score = silhouette_score(embeddings, labels_array)

    passed = score >= MIN_SILHOUETTE

    output = f"""Embedding Cluster Separation
----------------------------
Turns embedded: {len(texts)}
Unique labels: {len(set(labels))}

Silhouette score: {score:.3f} (need ≥{MIN_SILHOUETTE})

Interpretation:
  -1.0 to 0.0: Poor separation (clusters overlap)
  0.0 to 0.3:  Weak separation
  0.3 to 0.5:  Moderate separation
  0.5 to 1.0:  Strong separation

Status: {"PASS" if passed else "FAIL - Clusters not well separated"}
"""

    return ValidationResult(
        name="Embedding separation",
        passed=passed,
        output=output,
        duration_ms=int((time.time() - start) * 1000),
        metadata={
            "silhouette_score": float(score),
            "n_samples": len(texts),
            "n_clusters": len(set(labels)),
        },
    )


def train_probe_classifier() -> ValidationResult:
    """Train a simple classifier to test if tiers are learnable."""
    start = time.time()

    try:
        from sentence_transformers import SentenceTransformer
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import classification_report, accuracy_score
        import numpy as np
    except ImportError as e:
        return ValidationResult(
            name="Probe classifier",
            passed=False,
            error=f"Missing dependency: {e}",
            duration_ms=int((time.time() - start) * 1000),
        )

    by_rating = export_by_rating()

    # Collect all turns with labels
    texts = []
    labels = []
    for rating, turns in [(1, by_rating["thin"]), (2, by_rating["functional"]), (3, by_rating["rich"])]:
        for turn in turns:
            if turn.content.strip():
                texts.append(turn.content)
                labels.append(rating)

    if len(texts) < 15:
        return ValidationResult(
            name="Probe classifier",
            passed=False,
            output=f"Not enough data: {len(texts)} turns (need ≥15 for train/test split)",
            duration_ms=int((time.time() - start) * 1000),
        )

    # Generate embeddings
    print("Loading embedding model...")
    model = SentenceTransformer("all-MiniLM-L6-v2")

    print(f"Embedding {len(texts)} turns...")
    embeddings = model.encode(texts, show_progress_bar=True)

    # Train/test split
    X_train, X_test, y_train, y_test = train_test_split(
        embeddings, labels, test_size=0.2, random_state=42, stratify=labels
    )

    # Train classifier
    print("Training classifier...")
    clf = LogisticRegression(max_iter=1000, random_state=42)
    clf.fit(X_train, y_train)

    # Evaluate
    y_pred = clf.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)
    report = classification_report(y_test, y_pred, target_names=["thin", "functional", "rich"], output_dict=True)

    # Check per-class recall
    min_recall = min(
        report.get("thin", {}).get("recall", 0),
        report.get("functional", {}).get("recall", 0),
        report.get("rich", {}).get("recall", 0),
    )

    passed = accuracy >= MIN_ACCURACY and min_recall >= MIN_CLASS_RECALL

    report_str = classification_report(y_test, y_pred, target_names=["thin", "functional", "rich"])

    output = f"""Probe Classifier
----------------
Training samples: {len(X_train)}
Test samples: {len(X_test)}

Accuracy: {accuracy:.1%} (need ≥{MIN_ACCURACY:.0%})
Min class recall: {min_recall:.1%} (need ≥{MIN_CLASS_RECALL:.0%})

Classification Report:
{report_str}

Status: {"PASS" if passed else "FAIL - Accuracy or recall too low"}
"""

    return ValidationResult(
        name="Probe classifier",
        passed=passed,
        output=output,
        duration_ms=int((time.time() - start) * 1000),
        metadata={
            "accuracy": float(accuracy),
            "min_recall": float(min_recall),
            "train_size": len(X_train),
            "test_size": len(X_test),
        },
    )


def run_validation() -> ValidationReport:
    """Run all validation experiments."""
    results = []

    # Phase 0: Check data sufficiency first
    print("\n" + "=" * 60)
    print("Phase 0: Data Sufficiency Check")
    print("=" * 60)
    sufficiency = check_data_sufficiency()
    results.append(sufficiency)
    print(sufficiency.output)

    if not sufficiency.passed:
        print("\n⚠️  Not enough labeled data to proceed with validation.")
        print("   Label more conversations in lingo-label before continuing.")
        return ValidationReport.create("01", results)

    # Phase 1: Distribution analysis
    print("\n" + "=" * 60)
    print("Phase 1: Distribution Analysis")
    print("=" * 60)
    distribution = analyze_distributions()
    results.append(distribution)
    print(distribution.output)

    # Phase 2: Embedding separation
    print("\n" + "=" * 60)
    print("Phase 2: Embedding Cluster Separation")
    print("=" * 60)
    embedding = compute_embedding_separation()
    results.append(embedding)
    print(embedding.output)

    # Phase 3: Probe classifier
    print("\n" + "=" * 60)
    print("Phase 3: Probe Classifier")
    print("=" * 60)
    probe = train_probe_classifier()
    results.append(probe)
    print(probe.output)

    return ValidationReport.create("01", results)


def main():
    print("=" * 60)
    print("Validation 01: Training Data Signal")
    print("=" * 60)

    report = run_validation()

    # Save report
    output_path = Path(__file__).parent / "last-run.json"
    with open(output_path, "w") as f:
        json.dump(report.to_dict(), f, indent=2)
    print(f"\nReport saved to: {output_path}")

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"Total: {report.summary.total}")
    print(f"Passed: {report.summary.passed}")
    print(f"Failed: {report.summary.failed}")

    if report.summary.all_passed:
        print("\n✅ All checks passed. Proceed to iteration 02.")
    else:
        print("\n❌ Some checks failed. Review results before proceeding.")

    return 0 if report.summary.all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
