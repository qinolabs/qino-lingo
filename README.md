# Epistemological Signature Extraction

A data science project for discovering epistemological patterns in human-AI conversations.

## The Question

A month of Claude conversations holds something beyond the work that got done — it holds a pattern. The quality of inquiry, the shape of questions, the way ideas are held and released. If this could be extracted and made teachable, an AI system could work more autonomously while reflecting a personal cognitive style.

**Target:** Not conversation *content*, but *epistemic moves* — how thinking happens:
- How problems get framed before solving
- What follow-up questions emerge
- When suggestions are resisted vs integrated
- How ambiguity is held before collapsing to decision
- The self-documenting moments — when conversation flags its own richness

## Approach: Active Learning

Bottom-up discovery through human labeling, not top-down heuristics:

1. **Stochastic sampling** — surface random conversation fragments
2. **Human labeling** — mark rich/not-rich, annotate what creates richness
3. **Marker emergence** — annotations cluster into vocabulary
4. **Index growth** — markers link to examples, become searchable
5. **Semi-automation** — as patterns stabilize, detection becomes assistable

The system doesn't know what "rich" means. You teach it through noticing.

## Corpus

- **~1,000 active conversation files** (continuously growing)
- **~470K user words, ~650K Claude words**
- Dec 2, 2025 — present (continuous ingestion)
- Stored in `corpus/` (gitignored — large files)

## Quick Start

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Initialize/reset database
python3 -c "from lib.db import init_db; init_db()"

# Extract metadata from corpus files
python3 extract_metadata.py

# Import metadata to database
python3 -c "
from pathlib import Path
from lib.db import import_metadata
import_metadata(Path('metadata.json'))
"

# Launch Jupyter for exploration
jupyter notebook notebooks/01_exploration.ipynb
```

## Project Structure

```
qino-conversations/
├── corpus/               # Conversation files (gitignored)
│   ├── claude-conversation-*.md
│   └── _noise/          # Filtered noise files
├── lib/
│   ├── db.py            # Database operations
│   ├── parser.py        # Markdown → Turn objects
│   └── sampler.py       # Stratified sampling
├── notebooks/
│   └── 01_exploration.ipynb
├── docs/
│   ├── architecture.md
│   ├── schema.md
│   ├── labeling-workflow.md
│   └── labeler-concept-brief.md
├── ingest_conversations.py  # Extract from Claude Code storage
├── extract_metadata.py      # Corpus → metadata.json
├── filter_noise.py          # Move noise to _noise/
├── metadata.json            # Extracted file metadata
├── corpus.db                # SQLite database (gitignored)
└── requirements.txt
```

## Key Concepts

### Rich vs Not-Rich

A conversation (or segment) is "rich" when it exhibits epistemological qualities worth extracting — not based on topic, but on *how* thinking moves.

### Markers

An emergent vocabulary of epistemic patterns. Examples might include:
- "framing before solving"
- "productive uncertainty"
- "meta-awareness"
- "integrative synthesis"

Markers are discovered through labeling, not defined upfront.

### Labels

Human judgments on conversations: `is_rich` (boolean) + `notes` (what made it rich/not).

### Examples

Concrete excerpts linked to markers — the evidence for each pattern.

## Related Work

This inquiry lives alongside a research thread at:
`qino-research/inquiries/epistemological-signature/thread.md`

## Ingestion

New conversations can be pulled from Claude Code's local storage:

```bash
# Sync all new conversations since last import
python3 ingest_conversations.py

# Import only last N sessions (quick update)
python3 ingest_conversations.py --recent 20

# Preview without importing
python3 ingest_conversations.py --dry-run

# Import from specific date
python3 ingest_conversations.py --since 2026-01-04
```

Requires [claude-conversation-extractor](https://github.com/ZeroSumQuant/claude-conversation-extractor):
```bash
pipx install claude-conversation-extractor
```

## Next Steps

1. Develop labeling UI concept (see `docs/labeler-concept-brief.md`)
2. Implement React app for keyboard-driven labeling
3. Begin labeling to grow marker vocabulary
