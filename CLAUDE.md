# qino-lingo

Model training ecosystem for capturing epistemic signature from Claude conversations.

## Repository Structure

```
qino-lingo/
├── apps/
│   └── label/              # qino-label (TanStack Start)
│       └── src/
├── python/
│   └── qino_lingo/         # Python package
│       ├── db.py           # Database operations
│       ├── parser.py       # Conversation parsing
│       └── sampler.py      # Sample selection
├── data/
│   └── corpus/             # Conversation markdown files (gitignored)
├── corpus.db               # SQLite database
├── package.json            # pnpm workspace root
├── pnpm-workspace.yaml     # apps/*
└── turbo.json              # TypeScript task orchestration
```

## Development Commands

```bash
# Install dependencies
pnpm install

# Run all apps in dev mode
pnpm dev

# Run specific app
pnpm -F @qino-lingo/label dev

# Typecheck all packages
pnpm typecheck

# Lint all packages
pnpm lint
```

## Apps

### qino-label (apps/label/)
Turn-level labeling interface for conversation analysis.

```bash
cd apps/label
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
```

## Architecture

- **corpus.db as interface** - TypeScript and Python share via SQLite database
- **apps/** - TanStack Start applications (TypeScript)
- **python/** - Training, export, inference code (Python)
- **data/corpus/** - Conversation markdown files (gitignored)
