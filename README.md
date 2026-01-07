# qino-conversations

Teaching a model to think like you.

---

A month of Claude conversations holds something beyond the work accomplished — the shape of questions, how ideas are held and released, when suggestions are resisted versus integrated. This isn't content to extract but *epistemic signature* — the moves of thinking itself.

This repository is the corpus and infrastructure for discovering those patterns through human labeling. The act of labeling becomes a practice of self-recognition: sitting with a fragment and asking *does this feel like me? what makes it so?* Through noticing, a vocabulary emerges — markers that name what you already know but haven't articulated.

The labeled corpus becomes training data. A fine-tuned model that responds the way you would. And when that model is invoked — *how would qino respond?* — you're invited to judge: close enough? what's missing? The feedback loop closes, and the signature deepens.

## The Question

**Not conversation *content*, but *epistemic moves* — how thinking happens:**

- How problems get framed before solving
- What follow-up questions emerge
- When suggestions are resisted vs integrated
- How ambiguity is held before collapsing to decision
- The self-documenting moments — when a conversation flags its own richness

These patterns can't be extracted by rules. They emerge through attention.

## Why This Matters

This work reflects a way of thinking that found its seed in Gregory and Nora Bateson's work on the *pattern that connects*. Gregory asked: what connects the crab to the lobster and the orchid to the primrose, and all four of them to me? He defined information not as data, but as *a difference which makes a difference* — something relational, emerging from the gap between contexts.

Nora extended this into **warm data**: "transcontextual information about the interrelationships that integrate a complex system." Not cold data extracted from context, but living information that shifts within the mutual learning of systems.

The epistemological signature is warm data about thinking itself. It can't be captured in a checklist or defined in advance. It accumulates through noticing — through labeling that is attention, not categorization.

## The Labeling Flow

The system starts knowing nothing about what makes a conversation "rich." That knowledge emerges through human judgment, not predefined rules.

```
┌─────────────────┐
│  Sample         │  ← Stratified sampling surfaces diverse examples
└────────┬────────┘
         ▼
┌─────────────────┐
│  Read           │  ← Read the conversation, feel its quality
└────────┬────────┘
         ▼
┌─────────────────┐
│  Judge          │  ← Rich or not rich?
└────────┬────────┘
         ▼
┌─────────────────┐
│  Annotate       │  ← What made it so? (notes)
└────────┬────────┘
         ▼
┌─────────────────┐
│  Mark           │  ← Name the pattern if one emerges
└────────┬────────┘
         ▼
┌─────────────────┐
│  Repeat         │  ← Vocabulary grows through repetition
└─────────────────┘
```

After ~50 labels, patterns start appearing in the notes. When the same quality recurs, it gets a name: *productive-uncertainty*, *framing-before-solving*, *meta-awareness*. Each marker links to concrete examples, becomes a reference for what that pattern actually looks like.

## Richness Is Relational

A sequence of AI-only turns — reading files, running commands, exploring — isn't "rich" on its own. It's execution. Richness emerges from the *exchange* between human and AI: the prompt that opens something, the response that meets it, the follow-up that deepens.

The unit of meaning is the dialogue pattern, not the individual message.

## The Labeling UI

This repository contains the corpus and data infrastructure. The labeling interface lives in a separate app — keyboard-first, minimal chrome, designed for flow:

- `j/k` — Navigate turns
- `Shift+j/k` — Extend selection (because richness often spans multiple turns)
- `1-5` — Richness rating
- `n` — Mark as noise
- `m` — Open marker assignment
- `Enter` — Submit and advance

The bottleneck is reading and judging. Everything else should be instant.

When a trained model exists, the rating panel shows its suggestion: "likely noise (0.82)" or "uncertain (0.45)". Confirm or override with a keystroke. Your correction becomes training signal. Active learning closing the loop.

See [`docs/labeler-concept-brief.md`](docs/labeler-concept-brief.md) for the full design.

## The Corpus

- **~900+ active conversation files** (continuously growing)
- **~470K user words, ~650K Claude words**
- Dec 2, 2025 — present (continuous ingestion from Claude Code sessions)
- Stored in `corpus/` (gitignored — large files)

Conversations are extracted from Claude Code's local storage using [claude-conversation-extractor](https://github.com/ZeroSumQuant/claude-conversation-extractor).

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
├── corpus.db                # SQLite database
└── requirements.txt
```

## Key Concepts

### Markers

An emergent vocabulary of epistemic patterns, discovered through labeling:

- *framing-before-solving* — problem space explored before solutions offered
- *productive-uncertainty* — ambiguity held, not collapsed
- *meta-awareness* — conversation notices its own quality
- *integrative-synthesis* — ideas combined in novel ways
- *resistance-and-integration* — suggestions tested before accepting

Markers aren't defined upfront. They crystallize from repeated noticing.

### Labels

Human judgments on conversations: `is_rich` (boolean) + `notes` (what made it rich/not).

### Examples

Concrete excerpts linked to markers — the evidence for each pattern.

## Quick Start

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Initialize database
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

## The Larger Ecosystem

This project is part of [qino-claude](https://github.com/qinolabs/qino-claude) — tools for working with ideas in Claude Code. The tools don't just manage knowledge; they participate in a system that is learning.

The same philosophy runs through the ecosystem:

- **Abduction** — finding the pattern that connects, not proving true/false
- **Transcontextuality** — ideas meander across contexts, preserving the living thread
- **Aphanipoiesis** — the change before the change, what coalesces prior to emergence
- **Warm Data** — context kept attached, not extracted into cold facts

The epistemological signature work is the most personal expression of this: discovering how *your* thinking moves, so it can be reflected back to you — and eventually, taught to a model.

---

*What you couldn't explain, you can now teach. What you could only feel, you can now protect.*
