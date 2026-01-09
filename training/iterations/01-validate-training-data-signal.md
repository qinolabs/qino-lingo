# Iteration 01 — Validate Training Data Signal

**Status**: Pending
**Phase**: Validation
**Dependencies**: Minimum 30 labeled conversations (currently: 2)

## Hypothesis

Labeled conversation turns contain sufficient signal to train a model that:
1. Distinguishes rich from functional from thin content
2. Generalizes beyond specific training examples
3. Captures patterns that transfer to unseen conversations

## Why This Matters

If our labeled data doesn't contain distinguishable signal, model training is wasted compute. We'd be teaching a model to memorize noise rather than learn patterns.

This validation answers: **Is there something learnable in our labels?**

Better to discover insufficient signal with a 5-minute embedding experiment than after hours of fine-tuning.

## Experiment Design

### Phase 1: Data Distribution Analysis

**Goal**: Verify that different rating tiers have different characteristics.

**Method**:
1. Export all labeled turns by rating (1/2/3)
2. Compute per-tier statistics:
   - Average turn length (words)
   - Vocabulary richness (unique words / total words)
   - Question density (questions per turn)
   - Meta-cognitive markers (words like "notice", "wonder", "seems")
3. Visualize distributions

**Success Criteria**:
- At least 2 metrics show statistically significant differences between tiers
- Rich (3) tier has higher vocabulary richness than thin (1)
- Distributions don't completely overlap

**Output**: Distribution plots saved to `01-training-data-signal/distributions.png`

### Phase 2: Embedding Cluster Separation

**Goal**: Verify that turns embed into separable regions of semantic space.

**Method**:
1. Embed all labeled turns using sentence-transformers (all-MiniLM-L6-v2)
2. Color by rating tier
3. Compute silhouette score (cluster quality metric)
4. Visualize with UMAP/t-SNE reduction

**Success Criteria**:
- Silhouette score > 0.3 (moderate cluster quality)
- Visual inspection shows some separation
- Rich cluster is not randomly scattered

**Output**:
- Embedding visualization saved to `01-training-data-signal/embeddings.png`
- Silhouette score in `last-run.json`

### Phase 3: Probe Classifier

**Goal**: Verify that a simple classifier can learn to distinguish tiers.

**Method**:
1. Split labeled data: 80% train, 20% test
2. Train logistic regression on embeddings
3. Evaluate on held-out test set
4. Compute per-class precision/recall

**Success Criteria**:
- Overall accuracy > 70%
- No class has recall < 50% (model doesn't ignore any tier)
- Confusion matrix shows expected patterns (more confusion between adjacent tiers)

**Output**:
- Classification report in console and `last-run.json`
- Confusion matrix saved to `01-training-data-signal/confusion.png`

## Fixtures

Real labeled conversations from corpus.db, not synthetic data.

```python
# fixtures.py
from lib.export import export_labeled_turns

def load_fixtures(db_path: Path) -> dict:
    """Load real labeled turns grouped by rating."""
    turns = export_labeled_turns(db_path)
    return {
        "thin": [t for t in turns if t["rating"] == 1],
        "functional": [t for t in turns if t["rating"] == 2],
        "rich": [t for t in turns if t["rating"] == 3],
    }
```

## Reflection (Complete After Iteration)

### Verification Checks

Run these before marking complete:

- [ ] **Sufficient data**: At least 30 labeled turns total
- [ ] **Tier coverage**: At least 5 examples per tier
- [ ] **Distribution analysis**: Plots generated and reviewed
- [ ] **Embedding separation**: Silhouette score computed
- [ ] **Probe trained**: Classification metrics computed

### Results Summary

| Metric | Expected | Actual | Pass? |
|--------|----------|--------|-------|
| Labeled turns | ≥30 | — | |
| Silhouette score | >0.3 | — | |
| Probe accuracy | >70% | — | |
| Min class recall | >50% | — | |

### Hypothesis Verdict

- [ ] **Confirmed** — Data has learnable signal, proceed to iteration 02
- [ ] **Partial** — Signal exists but weak; document adjustments needed
- [ ] **Refuted** — Insufficient signal; labeling criteria may need revision

### Reflection Questions

1. **What surprised us?** (Unexpected patterns in the data)
2. **Which tier is hardest to distinguish?** (Functional often blurs)
3. **Are there labeling inconsistencies?** (Same content, different ratings)
4. **What would make signal stronger?** (More labels? Different criteria?)

### Plan Impact

- [ ] **Proceed to 02** — Signal sufficient, continue validation
- [ ] **Adjust labeling** — Refine criteria before more labeling
- [ ] **More data** — Need more labels before proceeding
- [ ] **Pause** — Fundamental issue with approach

### Technical Debt

(Document any shortcuts taken that should be addressed later)

---

## Implementation Notes

### Running the Validation

```bash
# From qino-lingo root
source .venv/bin/activate
python training/validations/01-training-data-signal/validate.py
```

### Dependencies

```
sentence-transformers
scikit-learn
matplotlib
umap-learn  # for visualization
```

### Estimated Duration

- Phase 1 (Distribution): ~1 minute
- Phase 2 (Embeddings): ~2 minutes (embedding generation)
- Phase 3 (Probe): ~1 minute

Total: ~5 minutes once data is available
