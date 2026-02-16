# qino-lingo

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

## The Source

The conversation material comes from daily work with Claude Code — the same sessions where concepts are developed, research is conducted, and code is implemented. There is no separate data collection step. The data isn't just *from* the process — it *is* the process.

Every conversation is automatically extracted and ingested into the corpus. The source material is authentic — real work, not examples staged for data collection. The curation happens through labeling.

## Native to Process

Data labeling for training a fine-tuned qino model is native to the process itself. Labeling is integrated in the tools used for concept development, research, and implementation.

**"What would qino say?"**

A response from the personal model is displayed inline (via MCP server). When Claude and I are in a flow, I can call `/label` and it provides a link to open the current conversation in the browser.

The web-based labeler shows the current conversation turns where I can efficiently mark turns or sequences:

- **Epistemic signatures** — human turns that embody the particular biases of abduction-oriented thinking
- **Enabling responses** — AI turns that created effective conditions for generative thinking

## Two Models, One Loop

**The qino chat model** responds when asked "what would qino say?" The aim is for it to show similar characteristics to my own biases — my epistemic signature in action.

**The qino labeler model** attempts to identify epistemic signatures, enabling responses, and other markers (noise, neutral, etc). It runs automatically when `/label` is called, and results overlay the conversation turns in the labeler UI.

The meta-learning happens when the labeler model's predictions don't match my manual markers.

## Two Layers of Data

We generate two layers:

1. **Content-level markers** — messages and sequences that exemplify the desired quality
2. **Quality content detection errors** — where qino labeler identified quality that wasn't there, or missed sequences that had it

The data flows back into the next training cycle:

- Next time I ask "What would qino say?" — the response might be of different quality
- Next time I run `/label` — the labeler model might identify quality content more accurately

I can use labeling confidence to:
- Create a queue with **low confidence** ratings to efficiently improve the labeler
- Create a queue with **high density of quality content** to add more good examples to the chat model training data

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

The labeling interface is keyboard-first, minimal chrome, designed for flow:

- `j/k` — Navigate turns
- `Shift+j/k` — Extend selection (because richness often spans multiple turns)
- `1-5` — Richness rating
- `n` — Mark as noise
- `m` — Open marker assignment
- `Enter` — Submit and advance

The bottleneck is reading and judging. Everything else should be instant.

When the labeler model has predictions, the rating panel shows its suggestion: "likely noise (0.82)" or "uncertain (0.45)". Confirm or override with a keystroke. Your correction becomes training signal. Active learning closing the loop.

## The Corpus

- **~1,500 conversation files** (1,100+ non-agent, continuously growing)
- **~1.9M user words, ~2.1M Claude words**
- Dec 2, 2025 — present (continuous ingestion from Claude Code sessions)
- Stored in `data/corpus/` (gitignored — large files)

Conversations are extracted from Claude Code's local storage using [claude-conversation-extractor](https://github.com/ZeroSumQuant/claude-conversation-extractor).

## Project Structure

```
qino-lingo/
├── apps/
│   └── lingo-label/         # Text conversation labeling UI (TanStack Start)
│       └── src/
│           ├── routes/      # Pages and layouts
│           ├── server/      # Server functions, DB access
│           ├── components/  # Turn rendering, controls
│           └── ui/          # Shared UI components
├── python/
│   └── qino_lingo/          # Python package
│       ├── db.py            # Database operations
│       ├── parser.py        # Markdown → Turn objects
│       ├── sampler.py       # Stratified sampling
│       ├── characterize.py  # AI epistemic analysis via LLM
│       └── calibrate.py     # Themed calibration rounds for human labeling
├── data/
│   └── corpus/              # Conversation files (gitignored)
│       ├── claude-conversation-*.md
│       └── _noise/          # Filtered noise files
├── docs/
│   ├── architecture.md
│   └── labeler-concept-brief.md
├── corpus.db                # SQLite database (shared interface)
├── package.json             # pnpm workspace root
├── pnpm-workspace.yaml
└── turbo.json
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

### Turn-Level Labels

- **Epistemic signature** — human turns embodying abductive thinking biases
- **Enabling response** — AI turns that created generative conditions
- **Noise** — administrative, tool-only, or low-signal content
- **Neutral** — neither particularly rich nor noise

### Meta-Labels (Layer 2)

When labeler predictions exist:
- Was the prediction correct?
- Was surfacing this item useful?
- Do the current categories fit what I'm seeing?

Layer 2 creates a calibration flywheel — the labeling system improves itself.

## Quick Start

```bash
# Install dependencies
pnpm install

# Start the labeler app
pnpm dev

# Or run directly
cd apps/label && pnpm dev
```

The app runs on port 3008. Configure paths in `apps/label/.env.local`:

```bash
CORPUS_DB_PATH=/path/to/qino-lingo/corpus.db
CORPUS_DIR=/path/to/qino-lingo/data/corpus
```

## Python Tools

```bash
# Activate virtual environment
source .venv/bin/activate

# Initialize database
python3 -c "from python.qino_lingo.db import init_db; init_db()"

# View corpus stats
python3 -c "from python.qino_lingo.db import get_stats; print(get_stats())"
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
