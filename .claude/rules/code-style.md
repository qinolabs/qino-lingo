# Code Style

## React

- Use kebab-case for component files
- Use `function` keyword for components
- No useMemo/useCallback (React Compiler handles optimization)
- Define props with `interface`

## TypeScript

- Never use `any` type
- Always use `??` instead of `||` for null/undefined checks
- Fix type errors at root cause, don't cast to any

## Tailwind

- This is a dark-mode-only app (no light mode)
- Use neutral color palette for backgrounds and text
- Use semantic accent colors: emerald (rich/success), amber (functional/warning), neutral (thin/default)

## Data Fetching

- Use TanStack Start server functions for database access
- Server functions are in `src/server/` directory
- Use Drizzle ORM for SQLite queries

## UI Components

- Shared components live in `packages/ui/`
- Import from `@qino-lingo/ui/components/*`
- Import cn utility from `@qino-lingo/ui/lib/utils`
