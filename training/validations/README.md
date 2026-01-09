# Validations

Hypothesis-driven experiments to validate assumptions before investing in model training.

## Philosophy

**Validate before building.** Model training is expensive—hours of compute, careful hyperparameter tuning, debugging mysterious failures. Before committing to that, we validate three core assumptions:

1. **Training data has signal** — Can we distinguish quality tiers in embeddings? Does a simple probe work?
2. **Approaches differentiate** — Do different training methods produce meaningfully different outputs?
3. **Metrics matter** — Does optimizing our chosen metrics actually improve human-evaluated quality?

If any of these fail, we save ourselves wasted compute and adjust our approach.

## Quick Start

```bash
# Activate virtual environment
source .venv/bin/activate

# Run all validations
python training/validations/run-all.py

# Run specific validation
python training/validations/run-all.py --validation 01

# Dry run (see what would execute)
python training/validations/run-all.py --dry-run
```

## Validation Structure

Each validation follows the same pattern:

```
NN-validation-name/
├── fixtures.py      # Test data (real labeled conversations)
├── validate.py      # Validation script
└── last-run.json    # Most recent results
```

### Validation Script Pattern

```python
# validate.py structure

def run_validation() -> ValidationReport:
    """
    1. Load fixtures (real data, not synthetic)
    2. Run experiment
    3. Evaluate results (human-reviewable, not just pass/fail)
    4. Return structured report
    """

    results = []
    for case in TEST_CASES:
        result = run_case(case)
        results.append(result)

    return ValidationReport(
        validation_id="01",
        timestamp=datetime.now().isoformat(),
        results=results,
        summary=compute_summary(results)
    )

if __name__ == "__main__":
    report = run_validation()
    save_report(report, "last-run.json")
    sys.exit(0 if report.summary.failed == 0 else 1)
```

### Result Format

```json
{
  "validation_id": "01",
  "timestamp": "2026-01-09T...",
  "results": [
    {
      "name": "Embedding cluster separation",
      "passed": true,
      "output": "Silhouette score: 0.42",
      "duration_ms": 1200,
      "metadata": {
        "silhouette_score": 0.42,
        "n_samples": 30,
        "n_clusters": 3
      }
    }
  ],
  "summary": {
    "total": 3,
    "passed": 3,
    "failed": 0
  }
}
```

## Validations

### 01 — Training Data Signal

**Hypothesis**: Labeled conversation turns contain sufficient signal to train a model that distinguishes quality tiers.

**Experiments**:
- Data distribution analysis (length, vocabulary by tier)
- Embedding cluster separation (silhouette score)
- Simple probe classifier (accuracy on held-out)

**Success Criteria**:
- Clear distribution differences between tiers
- Silhouette score > 0.3
- Probe accuracy > 70%

**Prerequisites**: ~30 labeled conversations

### 02 — Approach Differentiation

**Hypothesis**: Different training approaches (embedding-based vs fine-tuned, different architectures) produce meaningfully different outputs.

**Experiments**:
- Train 2-3 variants on same data
- Generate outputs for test prompts
- Compare outputs (embedding similarity, human evaluation)

**Success Criteria**:
- Output embedding similarity < 0.85 between approaches
- Human can distinguish outputs without labels
- Each approach shows distinct strengths

**Prerequisites**: Validation 01 passing

### 03 — Metric Correlation

**Hypothesis**: Optimizing for chosen metrics (perplexity, classification accuracy) correlates with human-evaluated quality.

**Experiments**:
- Train variants optimizing different metrics
- Human-evaluate output samples (blind)
- Measure correlation between metrics and human scores

**Success Criteria**:
- Spearman correlation > 0.5 between metric and human evaluation
- No metric-gaming artifacts (high metric, low quality)

**Prerequisites**: Validation 02 passing

## Shared Utilities (lib/)

```
lib/
├── types.py        # ValidationResult, ValidationReport, etc.
├── export.py       # Export labeled data for training
├── evaluate.py     # Model evaluation utilities
├── metrics.py      # Quality metrics (embedding, classification)
└── fixtures.py     # Load real labeled data as fixtures
```

## Go/No-Go Gates

After each validation:

| Verdict | Action |
|---------|--------|
| **Confirmed** | Proceed to next validation |
| **Partial** | Document adjustments, then proceed |
| **Refuted** | Stop, reassess approach |

Only proceed to build phase (iterations 04-06) after all three validations pass.
