# qino-lingo Model Training Implementation

Training custom models to capture and reproduce epistemic signature from conversation data.

## Target Models

| Model | Purpose | Type |
|-------|---------|------|
| **qino-eval** | Classify conversation turn quality (thin/functional/rich) | Classifier |
| **qino-say** | Generate responses with epistemic signature | Generative |

## Layer Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     Training Pipeline                        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐   │
│  │   Labeling   │───▶│    Export    │───▶│   Training   │   │
│  │  (lingo-label)│    │   Pipeline   │    │   Pipeline   │   │
│  └──────────────┘    └──────────────┘    └──────────────┘   │
│         │                   │                   │            │
│         ▼                   ▼                   ▼            │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐   │
│  │  corpus.db   │    │ training/    │    │   models/    │   │
│  │  (labels)    │    │ data/*.jsonl │    │   *.gguf     │   │
│  └──────────────┘    └──────────────┘    └──────────────┘   │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│                     Inference Layer                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐   │
│  │  MCP Server  │    │ lingo-label  │    │   Claude     │   │
│  │  (qino-lingo)│    │  predictions │    │   enrichment │   │
│  └──────────────┘    └──────────────┘    └──────────────┘   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Iteration Overview

### Validation Phase (Before Training)

| # | Iteration | Hypothesis | Status |
|---|-----------|------------|--------|
| 01 | Validate Training Data Signal | Labeled data has enough signal to distinguish quality tiers | Pending |
| 02 | Validate Approach Differentiation | Different training approaches produce meaningfully different outputs | Pending |
| 03 | Validate Metric Correlation | Optimizing chosen metrics improves human-evaluated quality | Pending |

### Build Phase (After Validation)

| # | Iteration | Goal | Status |
|---|-----------|------|--------|
| 04 | Train qino-eval Classifier | Working quality classifier on labeled data | Pending |
| 05 | Active Labeling Loop | Use qino-eval predictions to accelerate labeling | Pending |
| 06 | Train qino-say Generative | Fine-tune generative model on rich examples | Pending |

## Dependencies

### Hardware
- Apple M2 Pro, 32GB RAM
- MLX framework for local training

### Data Requirements
| Iteration | Minimum Labels | Recommended |
|-----------|---------------|-------------|
| 01-03 (Validation) | 30 | 50 |
| 04 (qino-eval) | 50 | 100 |
| 05 (Active Loop) | 100 | 200 |
| 06 (qino-say) | 200 | 500 |

### Current State
- Corpus: 999 conversation files
- Labeled: 2 files (1 thin, 2 functional, 0 rich)
- **Blocking**: Need ~30 labels before validation can begin

## Boundaries

### Approved
- Local training with MLX on Apple Silicon
- Qwen 2.5 base models (7B or 14B depending on memory)
- Sentence-transformers for embeddings
- SQLite database for labels and metadata

### Restricted
- No cloud training in validation phase (too expensive for experiments)
- No changes to lingo-label schema (already validated)
- No synthetic training data (use real labeled conversations only)

### Consider Later
- Cloud fine-tuning for final production models
- LoRA vs full fine-tuning comparison
- Multi-task training (eval + say together)

## Related Work

- **lingo-label**: UI for conversation labeling (apps/lingo-label/)
- **MCP server**: Corpus access for Claude (mcp-server/)
- **noise_filter**: Existing ML pipeline for noise detection (apps/lingo-label/scripts/noise_filter/)

## Documentation Structure

```
training/
├── implementation.md          # This file (executive overview)
├── validations/
│   ├── README.md             # Validation philosophy, quick start
│   ├── run-all.py            # Pipeline orchestrator
│   ├── lib/                  # Shared utilities
│   └── 01-*/02-*/03-*/       # Individual validations
├── iterations/
│   ├── 01-validate-training-data-signal.md
│   ├── 02-validate-approach-differentiation.md
│   ├── 03-validate-metric-correlation.md
│   ├── 04-train-qino-eval.md
│   ├── 05-active-labeling-loop.md
│   └── 06-train-qino-say.md
└── data/                     # Exported training data (gitignored)
```
