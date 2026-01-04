# Labeler Concept Brief

Design brief for the conversation labeling UI — source material for concept development.

## Context

We have 900 conversation files to label for epistemological richness. The current infrastructure (Python library, SQLite database, Jupyter notebooks) supports the data operations. What's missing: a fast, pleasant interface for the human labeling loop.

## The Job To Be Done

**As a labeler, I need to:**
1. See a conversation (or segment) clearly
2. Make a judgment quickly (rich/not-rich)
3. Annotate my reasoning briefly
4. Optionally: link to emerging markers
5. Move to the next sample immediately

**The bottleneck:** Reading and judging. Everything else should be instant.

## Design Principles

### 1. Keyboard-First

The labeling loop happens hundreds of times. Every mouse movement is friction.

- `j/k` — Scroll through conversation
- `r` — Mark rich
- `n` — Mark not-rich
- `m` — Open marker assignment
- `Enter` — Submit and advance
- `Tab` — Move between panels

### 2. Minimal Chrome

The conversation is the content. Everything else is annotation.

- No sidebars when not needed
- No modals for simple actions
- No confirmations for non-destructive operations

### 3. Context Preservation

Labeling happens in flow. Interruptions break the sensing.

- Auto-save annotations
- No page reloads between samples
- Undo available but rarely needed

### 4. Progressive Disclosure

Start simple, reveal complexity as needed.

- Phase 1: Just rich/not-rich + notes
- Phase 2: Marker assignment appears as markers exist
- Phase 3: Example excerpting when linking to markers

## Views

### Main View: Labeling

```
┌─────────────────────────────────────────────────────────────────┐
│ [progress: 42/900 ████░░░░░░ 4.7%]              [file: abc123] │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ## 👤 User                                                     │
│                                                                 │
│  I've been thinking about how this system handles errors.      │
│  What makes a good error boundary?                             │
│                                                                 │
│  ---                                                            │
│                                                                 │
│  ## 🤖 Claude                                                   │
│                                                                 │
│  That's a great question to explore before implementing...     │
│                                                                 │
│  [conversation continues...]                                   │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│ Notes: ________________________________________________        │
│                                                                 │
│        [r] Rich    [n] Not Rich    [s] Skip    [?] Help        │
└─────────────────────────────────────────────────────────────────┘
```

### Marker Panel (when invoked)

```
┌─────────────────────────────────────────────────────────────────┐
│  Markers                                              [Esc] ✕  │
├─────────────────────────────────────────────────────────────────┤
│  [1] productive-uncertainty (12 examples)                      │
│  [2] framing-before-solving (8 examples)                       │
│  [3] meta-awareness (5 examples)                               │
│  [+] Create new marker...                                      │
└─────────────────────────────────────────────────────────────────┘
```

### Stats View

```
┌─────────────────────────────────────────────────────────────────┐
│  Labeling Progress                                              │
├─────────────────────────────────────────────────────────────────┤
│  Total files:     900                                          │
│  Labeled:         42 (4.7%)                                    │
│  Rich:            18 (43% of labeled)                          │
│  Not rich:        24 (57% of labeled)                          │
│                                                                 │
│  Markers:         5                                            │
│  Examples:        28                                           │
│                                                                 │
│  By stratum:                                                   │
│    high_engagement:    8/156  (5.1%)                          │
│    medium_engagement: 12/312  (3.8%)                          │
│    low_engagement:     6/280  (2.1%)                          │
│    reflective:        10/198  (5.1%)                          │
│    agent_sessions:     6/54   (11.1%)                         │
└─────────────────────────────────────────────────────────────────┘
```

## Technical Stack

The UI will live in **qinolabs-repo** (React + TypeScript + Tailwind).

### Backend

FastAPI server in qino-conversations or qinolabs-repo/apps:

```python
# Endpoints
GET  /api/samples           # Get next batch of samples
GET  /api/files/:id         # Get file with full content
POST /api/labels            # Create/update label
GET  /api/markers           # List markers
POST /api/markers           # Create marker
POST /api/examples          # Link example to marker
GET  /api/stats             # Labeling progress
```

### Frontend

React app consuming the API:

- Single page, multiple views via state (not routing)
- Local state for current sample, notes
- Optimistic updates with background sync
- Keyboard event handling at app level

## Open Questions

1. **Segment granularity** — Label whole conversations or turn ranges?
   - Start with whole conversations
   - Add segment selection when needed

2. **Marker hierarchy** — Flat list or nested categories?
   - Start flat
   - Consider clustering as vocabulary grows

3. **Multi-labeler** — Single user or collaborative?
   - Single user for now
   - Schema supports multiple labelers (add user_id to labels)

4. **Offline support** — Work without network?
   - SQLite is local, so possible
   - React app could cache samples

## Success Criteria

- **Time per label:** <30 seconds for binary judgment + brief note
- **Session length:** Comfortable to label 20-30 in a sitting
- **Zero friction:** Keyboard flow never interrupted by UI

## Prior Art

- [Label Studio](https://labelstud.io/) — Full-featured but heavy
- [Prodigy](https://prodi.gy/) — Excellent UX, commercial
- [Argilla](https://argilla.io/) — Open source, team-focused

We need something lighter and more opinionated for this specific task.

## Next Step

Use `/qino-concept:explore` to develop this concept further — exploring the interaction model, visual design, and technical architecture through dialogue.
