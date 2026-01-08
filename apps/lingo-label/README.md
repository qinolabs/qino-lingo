# lingo-label

Turn-level text conversation labeling interface for epistemic signature extraction.

## Quick Start

```bash
# From qino-lingo root
pnpm install
pnpm dev

# Or directly
cd apps/lingo-label
pnpm dev
```

Runs on port 3008.

## Environment

Create `.env.local`:

```bash
CORPUS_DB_PATH=/path/to/qino-lingo/corpus.db
CORPUS_DIR=/path/to/qino-lingo/data/corpus
```

## Keyboard Controls

| Key | Action |
|-----|--------|
| `j/k` | Navigate turns |
| `Shift+j/k` | Extend selection |
| `1-5` | Rating |
| `n` | Mark noise |
| `Enter` | Submit and advance |

## See Also

- [qino-lingo README](../../README.md) — Full project documentation
- [Architecture](../../docs/architecture.md) — Technical details
- [Schema](../../docs/schema.md) — Database structure
