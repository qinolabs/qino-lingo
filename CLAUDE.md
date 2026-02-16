# qino-lingo

Model training ecosystem for capturing epistemic signature from Claude conversations.

## Repository Structure

```
qino-lingo/
├── apps/
│   └── lingo-label/        # Conversation labeling UI (TanStack Start)
├── packages/
│   └── ui/                 # Shared UI components
├── python/
│   └── qino_lingo/         # Python package
├── data/
│   └── corpus/             # Conversation markdown files (gitignored)
├── corpus.db               # SQLite database
├── package.json            # pnpm workspace root
├── pnpm-workspace.yaml     # apps/*, packages/*
└── turbo.json              # TypeScript task orchestration
```

## Rules

Code style guidelines: @.claude/rules/code-style.md

## Development Commands

```bash
# Install dependencies
pnpm install

# Run all apps in dev mode
pnpm dev

# Run specific app
pnpm -F @qino-lingo/lingo-label dev

# Typecheck all packages
pnpm typecheck

# Lint all packages
pnpm lint
```

## Apps

### lingo-label (apps/lingo-label/)
Turn-level labeling interface for text conversation analysis.

```bash
cd apps/lingo-label
pnpm dev              # Start dev server on port 3008
pnpm typecheck        # Type check
pnpm check            # Typecheck + lint
```

Environment variables (`.env.local`):
- `CORPUS_DB_PATH` - Path to corpus.db
- `CORPUS_DIR` - Path to data/corpus/

## Python

Python code lives in `python/qino_lingo/`. The Python code and TypeScript app share the same `corpus.db` SQLite database.

```bash
# Activate virtual environment (if not already)
source .venv/bin/activate

# Run database operations
python -c "from python.qino_lingo.db import get_stats; print(get_stats())"

# AI characterization — epistemic analysis via LLM
python -m python.qino_lingo.characterize --strategy signal --limit 5 --dry-run

# Calibration rounds — themed human labeling for ground truth
python -m python.qino_lingo.calibrate themes                        # list themes + eligible counts
python -m python.qino_lingo.calibrate round --theme broad_seeding   # create round
python -m python.qino_lingo.calibrate present --round 1             # show all items
python -m python.qino_lingo.calibrate present --round 1 --item 3    # show one item
python -m python.qino_lingo.calibrate label --round 1 --item 1 --rating 3
python -m python.qino_lingo.calibrate interpret --round 1           # analyze + suggest next
python -m python.qino_lingo.calibrate status                        # all rounds overview
```

### Python Modules

| Module | Purpose |
|--------|---------|
| `db.py` | Database operations, schema, label/marker CRUD |
| `parser.py` | Markdown conversation files → `Turn`/`Conversation` objects |
| `sampler.py` | Stratified sampling for labeling |
| `characterize.py` | AI epistemic analysis via OpenRouter (stores in `pending_labels`) |
| `calibrate.py` | Themed calibration rounds for human ground-truth labeling |

## Architecture

- **corpus.db as interface** - TypeScript and Python share via SQLite database
- **apps/** - TanStack Start applications (TypeScript)
- **python/** - Training, export, inference code (Python)
- **data/corpus/** - Conversation markdown files (gitignored)
