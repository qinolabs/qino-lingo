# lingo-label

Turn-level text conversation labeling interface for epistemic signature extraction.

## What This Is

A keyboard-first UI for marking conversation turns:
- **Epistemic signatures** — human turns embodying abductive thinking
- **Enabling responses** — AI turns that created generative conditions
- **Noise** — administrative, tool-only content
- **Neutral** — neither rich nor noise

## Architecture

- **TanStack Start** — Full-stack React with SSR
- **SQLite (corpus.db)** — Shared with Python code, no separate backend
- **Server Functions** — Direct DB access via Drizzle ORM
- **No Authentication** — Local-only tool

## Schema Authority

`corpus.db`'s schema is owned by `python/qino_lingo/migrations/` (applied
via `make migrate`). `src/server/schema.ts` is a hand-maintained mirror —
when the Python-side migrations change the schema, update `schema.ts` to
match and let the TypeScript compiler surface any consumer drift. Dependent
tables FK on `files.filename`, not `files.id`; `PRAGMA foreign_keys = ON`
must be enabled on every connection (already set in `src/server/db.ts`).
See `../../docs/schema.md` and
`../../implementations/persistence-layer/content/01-holistic-refactor.md`
for the full rationale.

## Development

```bash
pnpm dev          # Start on port 3008
pnpm typecheck    # Type check
pnpm check        # Typecheck + lint
```

## Environment

Create `.env.local`:
```bash
CORPUS_DB_PATH=/path/to/qino-lingo/corpus.db
CORPUS_DIR=/path/to/qino-lingo/data/corpus
```

## Key Files

- `src/server/db.ts` — Database connection
- `src/server/schema.ts` — Drizzle schema (mirrors corpus.db)
- `src/server/get-conversation.ts` — Load conversation with noise predictions
- `src/routes/label.$fileId.tsx` — Main labeling interface
- `src/components/conversation-turn.tsx` — Turn rendering with selection

## Keyboard Controls

- `j/k` — Navigate turns
- `Shift+j/k` — Extend selection
- `1-5` — Rating
- `n` — Mark noise
- `Enter` — Submit and advance
