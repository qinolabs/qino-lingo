# Hybrid Noise Filter

Two-layer noise filter for cleaning conversation corpus:

1. **Deterministic filter** — regex patterns, length checks, tag detection. Fast, catches obvious noise.
2. **ML filter** — embeddings + logistic regression trained on your labels. Catches subtle patterns.

## Setup

```bash
cd apps/qino-label/scripts/noise_filter
pip install -r requirements.txt
```

## Usage

### Full Pipeline

```bash
# Run both filters
python pipeline.py \
  --db /path/to/corpus.db \
  --corpus /path/to/corpus/ \
  --model noise_model.pkl

# With active learning (queue uncertain for review)
python pipeline.py \
  --db /path/to/corpus.db \
  --corpus /path/to/corpus/ \
  --model noise_model.pkl \
  --queue-uncertain
```

### Individual Scripts

```bash
# Deterministic filter only (no ML)
python deterministic.py --db corpus.db --corpus corpus/

# Train ML model
python train.py --db corpus.db --corpus corpus/ --output noise_model.pkl

# Run ML inference
python inference.py --db corpus.db --corpus corpus/ --model noise_model.pkl
```

### Check Statistics

```bash
python pipeline.py --db corpus.db --corpus corpus/ --stats
```

## Active Learning Loop

1. **Label in qino-label** — Rate conversations, mark noise with 'n' key
2. **Run pipeline** — `python pipeline.py --db ... --corpus ... --model ... --retrain`
3. **Review uncertain** — `--queue-uncertain` adds predictions to labeling queue
4. **Repeat** — More labels → better model → cleaner corpus

## Thresholds

The ML filter uses two thresholds:
- **< 0.3** → Signal (keep)
- **> 0.7** → Noise (filter)
- **0.3 - 0.7** → Uncertain (queue for human review)

Adjust with `--low-threshold` and `--high-threshold`.

## Noise Patterns (Deterministic)

| Pattern | Examples |
|---------|----------|
| `command_output` | Shell prompts, npm output, test results |
| `system_message` | `<system>` tags, tool results |
| `file_listing` | `ls -l` output, tree output |
| `minimal_acknowledgment` | "ok", "thanks", "got it" |
| `code_dump` | Large code blocks (>80% of content) |
| `empty` | Whitespace-only turns |

## Database Schema

Predictions stored in `noise_predictions` table:

| Column | Type | Description |
|--------|------|-------------|
| `file_id` | int | References files.id |
| `turn_idx` | int | Turn index in conversation |
| `deterministic_is_noise` | bool | Deterministic filter result |
| `deterministic_reason` | text | Why marked as noise |
| `ml_score` | float | 0.0 (signal) to 1.0 (noise) |
| `ml_is_noise` | bool | ML prediction (null if uncertain) |
| `human_label` | bool | Human override (null if unlabeled) |
