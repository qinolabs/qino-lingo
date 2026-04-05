# MCP Server Evolution: From Training Data to Conversation Explorer

## Context

The qino-lingo MCP server currently exposes 4 tools for searching and retrieving conversations from the corpus. It was built for a single use case: epistemic signature extraction for model training.

A second use case has emerged: **metalogue sourcing** — discovering which conversations from the archive could serve as source material for metalogue chapters. This requires a fundamentally different mode of engagement with the corpus: not "is this turn epistemically rich?" but "does this conversation have an arc where thinking becomes visible through dialogue?"

Rather than building a separate tool, this design evolves the MCP server into a general-purpose conversation corpus explorer that serves both use cases — and any future use case that involves working with the conversation archive as material.

## Design Principles

**1. The corpus is material, not data.**
The conversations are not a dataset to be classified. They are material to be encountered — searched, read, cross-referenced, understood. The tools should feel like library tools (search, browse, annotate, discover connections) not data pipeline tools (filter, transform, export).

**2. Cleaned views are first-class.**
Raw conversation transcripts contain massive amounts of noise: context compaction summaries, skill expansions, console output, code blocks, terse commands. Every tool that returns conversation content should offer cleaned views by default. An agent reading a conversation should receive the 15% that carries thinking, not the 85% that carries execution.

**3. Pre-computation for expensive signals, live computation for cheap ones.**
The metalogue analysis (concept density, rich turns, corrections, meta-awareness, trajectory) takes ~30 seconds for the full corpus. Pre-compute these and store in the database. But noise filtering a single conversation is fast — do it on read.

**4. The exchange is the unit of meaning.**
A user turn and the assistant response it provoked form a unit. A correction without its antecedent is unintelligible. Tools that return conversation content should present exchanges (user-assistant pairs), not isolated turns. A user's thinking becomes visible *through* the interaction.

**5. Tools compose.**
The output of `candidates` (ranked list) feeds into `read_thinking` (cleaned content) which feeds into `tag` (annotation). An agent should be able to chain these naturally without intermediate translation.

**6. Both use cases share infrastructure.**
Noise filtering benefits training data labeling too. Concept density helps identify epistemically rich conversations. The metalogue signals table enriches the existing metadata. Don't build parallel systems — extend the existing one.

## Architecture

### Data layer evolution

```
corpus.db (existing tables preserved)
├── files              — conversation metadata (existing)
├── labels             — human judgments for training (existing)
├── markers            — epistemic vocabulary (existing)
├── examples           — marker excerpts (existing)
├── pending_labels     — labeling queue (existing)
├── noise_predictions  — ML noise scores (existing)
│
├── conversation_signals  — NEW: pre-computed analysis per conversation
│   ├── file_id (FK → files, UNIQUE)
│   ├── metalogue_score
│   ├── concept_density       (per 1k reflective words)
│   ├── reflective_turns      (count after noise filtering)
│   ├── reflective_words      (total after noise filtering)
│   ├── rich_turns            (100+ words AND concept >= 3)
│   ├── medium_rich_turns     (60+ words AND concept >= 2)
│   ├── very_rich_turns       (200+ words AND concept >= 3)
│   ├── corrections           (user pushback/redirect count)
│   ├── meta_awareness        (self-referential moment count)
│   ├── cross_diversity       (distinct modalities referenced)
│   ├── terse_ratio           (fraction of terse command turns)
│   ├── trajectory_shape      (SHIFT/SUSTAINED/DEEPENING/FADING/FLAT)
│   ├── concept_keywords      (JSON array of matched concept terms)
│   ├── best_preview          (highest-signal user turn excerpt, ~600 chars, sentence-bounded)
│   ├── computed_at           (timestamp)
│   └── algorithm_version    (e.g., "v6")
│
├── annotations        — NEW: general-purpose conversation annotations
│   ├── id (PK)
│   ├── file_id (FK → files)
│   ├── exchange_start        (nullable — null means whole-conversation)
│   ├── exchange_end          (nullable)
│   ├── kind                  (e.g., "metalogue_verdict", "provenance", "highlight")
│   ├── value                 (e.g., "Y", "M", "N", or free text)
│   ├── thread                (thematic grouping, nullable)
│   ├── notes                 (free text, nullable)
│   ├── source                (who annotated: "human", agent name)
│   └── created_at            (timestamp)
│
└── INDEX: idx_files_session ON files(session_id)  — NEW
```

**Key changes from v1 design (informed by review):**

- Renamed `metalogue_signals` → `conversation_signals`. The signals are generally useful, not metalogue-specific.
- Renamed `metalogue_tags` → `annotations`. General-purpose, supports multiple annotations per conversation from different sources without overwriting.
- Added `exchange_start`/`exchange_end` to annotations — enables marking specific passages, not just whole conversations.
- Added `kind` field to annotations — separates metalogue verdicts from provenance links, highlights, and future use cases.
- Added `concept_keywords` JSON column to `conversation_signals` — pre-computed vocabulary per conversation so `related` can work from DB without re-parsing.
- Added `session_id` index on `files` — every new tool resolves by session_id.
- `best_preview` truncated at sentence boundaries, not mid-word.

### Module structure

```
python/qino_lingo/
├── db.py              — existing + NEW: annotation CRUD
│   ├── (existing operations unchanged)
│   ├── add_annotation(file_id, kind, value, ...) → id
│   ├── get_annotations(file_id, kind?) → list
│   ├── list_annotations(kind?, thread?, source?) → list
│   └── update_annotation(id, ...) → None
│
├── parser.py          — existing markdown parser (unchanged)
├── sampler.py         — existing sampling (unchanged)
├── characterize.py    — existing AI analysis (unchanged)
├── calibrate.py       — existing calibration (unchanged)
│
├── cleaning.py        — NEW: noise filtering utilities
│   ├── is_system_content(text) → bool
│   ├── strip_code_blocks(text) → str
│   ├── strip_console_output(text) → str
│   ├── is_terse_command(text) → bool
│   ├── clean_user_turn(raw_text) → str
│   └── clean_conversation(filepath) → list[CleanedExchange]
│           (returns exchange-level data: user turn + assistant response)
│
├── signals.py         — NEW: conversation signal extraction
│   ├── ALGORITHM_VERSION: str
│   ├── CONCEPTUAL_KEYWORDS: list[str]
│   ├── CORRECTION_PATTERNS: list[str]
│   ├── META_AWARENESS_PATTERNS: list[str]
│   ├── score_conceptual(text) → int
│   ├── detect_corrections(text) → bool
│   ├── detect_meta_awareness(text) → bool
│   ├── analyze_conversation(filepath) → ConversationSignals
│   ├── compute_trajectory(exchanges) → TrajectoryShape
│   ├── compute_all(corpus_dir, db_path) → None
│   └── check_staleness(db_path) → bool  # compare stored vs current version
│
└── metalogue.py       — NEW: metalogue-specific queries
    ├── get_candidates(db, filters) → list[Candidate]
    ├── get_trajectory(db, session_id) → Trajectory
    └── find_related(db, session_id, top_n) → list[Related]
```

**Key changes from v1 design (informed by review):**

- Annotation CRUD lives in `db.py` — it's general infrastructure, not metalogue-specific.
- `cleaning.py` returns `CleanedExchange` (user + assistant pairs) not isolated turns.
- `signals.py` owns `ALGORITHM_VERSION` and a `check_staleness` function.
- `metalogue.py` is purely metalogue-specific queries — no tagging, no annotation.

### MCP server tools

The server file (`mcp-server/server.py`) registers tools from these modules. Tool names use a flat namespace.

#### Existing tools (enhanced)

**`search`** — Search conversations by content
```
Enhancements:
- New param: user_only (bool) — search only in user turns
- New param: min_concept_density (float) — filter by conversation signal
- Results include metalogue_score if signals are computed
- Snippet shows the surrounding exchange, not a raw text window
```

**`get`** — Retrieve a conversation
```
Enhancements:
- New param: view — "raw" (default), "clean" (noise stripped),
  "thinking" (only rich/correction/meta exchanges), "exchanges" (all, numbered)
- New param: range — "14-22" (exchange range, works with any view)
- All non-raw views return exchange-level data (user turn + assistant response)
- "thinking" view annotates each exchange: {index, user_words, concept_score,
  signals: ["correction", "meta_awareness", "rich", ...], user_text, assistant_text}
```

**`metadata`** — Get conversation metadata
```
Enhancements:
- Includes conversation signals (score, density, trajectory) if computed
- Includes annotations if present
```

**`stats`** — Corpus statistics
```
Enhancements:
- Signal section: candidate count, annotation progress, score distribution
- Concept density distribution (histogram buckets)
```

#### New tools — Discovery

**`candidates`** — List conversations ranked by metalogue score
```python
def candidates(
    top: int = 30,
    min_score: int = 0,
    min_density: float = 0.0,
    date_from: str | None = None,
    date_to: str | None = None,
    unannotated_only: bool = False,
    trajectory: str | None = None,
) -> list[dict]:
    """
    One-line-per-conversation: filename, date, score, key metrics,
    best_preview. Designed for scanning — an agent reads this to
    decide what to read deeper.
    """
```

**`read_thinking`** — Read the thinking exchanges from a conversation
```python
def read_thinking(
    session_id: str,
    min_concept: int = 0,
    include_corrections: bool = True,
    include_meta: bool = True,
    include_assistant: bool = True,
) -> dict:
    """
    Returns cleaned, signal-annotated exchanges that carry genuine thinking.
    Each exchange: {index, user_text, assistant_text (if include_assistant),
    user_words, concept_score, signals: [...]}.
    
    Conversation-level summary: total_thinking_exchanges, trajectory_shape,
    concept_density.
    
    This is the primary tool for assessing a conversation's quality —
    it shows the exchanges where thinking is visible.
    """
```

**`trajectory`** — Analyze a conversation's arc shape
```python
def trajectory(session_id: str) -> dict:
    """
    Divides the conversation into thirds (opening/middle/closing).
    For each third:
    - concept_density, correction_density, dominant_topics, exchange_count
    
    Also returns:
    - trajectory_shape: SHIFT / SUSTAINED / DEEPENING / FADING / FLAT
    - description: one-sentence natural language summary of the arc
    
    Computed over user turns (the human's thinking trajectory),
    not the full dialogue volume.
    """
```

**`related`** — Find conversations with shared conceptual terrain
```python
def related(
    session_id: str,
    top: int = 10,
) -> list[dict]:
    """
    Compares concept vocabulary (from pre-computed concept_keywords)
    against all other conversations. Returns top N by keyword overlap:
    - shared_keywords, similarity_score, key metrics
    
    Note: this is vocabulary overlap, not semantic similarity.
    Two conversations mentioning "encounter" may be about different things.
    Use as a discovery tool, not a classifier.
    """
```

**`nearby`** — Find temporally proximate conversations
```python
def nearby(
    session_id: str,
    days: int = 3,
) -> list[dict]:
    """
    Returns all conversations within +/- N days of the given conversation.
    Ordered by date. Includes key metrics and best_preview.
    
    Useful for context: "what was the human working on that week?"
    """
```

**`annotate`** — Add an annotation to a conversation
```python
def annotate(
    session_id: str,
    kind: str,                      # "metalogue_verdict", "highlight", "provenance", etc.
    value: str | None = None,       # "Y", "M", "N", or free text
    thread: str | None = None,
    notes: str | None = None,
    exchange_start: int | None = None,
    exchange_end: int | None = None,
    source: str = "human",
) -> dict:
    """
    Persists an annotation. Supports:
    - Whole-conversation (exchange_start/end both null)
    - Passage-level (exchange_start and exchange_end set)
    - Multiple annotations per conversation (from different sources or kinds)
    """
```

**`annotations`** — List annotations
```python
def annotations(
    kind: str | None = None,
    thread: str | None = None,
    source: str | None = None,
    verdict: str | None = None,     # shortcut: kind="metalogue_verdict", value=verdict
) -> list[dict]:
    """
    Returns annotations with their conversation metadata.
    Filterable by any combination of kind, thread, source, verdict.
    """
```

## Pre-computation pipeline

```bash
# Compute signals for all conversations (~30s)
python -m qino_lingo.signals compute

# Recompute since a date (for newly ingested conversations)
python -m qino_lingo.signals compute --since 2026-04-01

# Check staleness (warns if stored version != current)
python -m qino_lingo.signals check

# Show algorithm version + changelog
python -m qino_lingo.signals version
```

**Staleness guard:** On server startup, `check_staleness()` runs. If stored `algorithm_version` doesn't match current, the server logs a warning. Tools still return data (stale is better than nothing) but include a `stale: true` flag in responses.

**Ingestion integration:**
```
filter_noise → extract_metadata → db import → compute_signals (NEW)
```

**Algorithm changelog:** Lives at `docs/signal-algorithm-changelog.md`. Each version records: what changed, why, and validation results against manually-assessed samples.

## Implementation plan

### Phase 1: Data layer + core modules
1. Create `cleaning.py` — extract noise filtering from the analysis scripts
2. Create `signals.py` — signal computation + pre-computation to DB
3. Extend `db.py` — annotation CRUD, session_id index, new table creation
4. Run initial computation for the full corpus
5. Integrate into ingestion pipeline

### Phase 2: MCP server — essential tools
6. Add `candidates` tool
7. Add `read_thinking` tool (exchange-level, with assistant responses)
8. Add `annotate` and `annotations` tools
9. Enhance `get` with view modes and range parameter
10. Enhance `metadata` with conversation signals

### Phase 3: MCP server — exploration tools
11. Add `trajectory` tool
12. Add `related` tool (using pre-computed concept_keywords)
13. Add `nearby` tool
14. Enhance `search` with user-only and density filters
15. Enhance `stats` with signal aggregates

### Phase 4: Documentation + polish
16. Update `docs/architecture.md`
17. Create `docs/signal-algorithm-changelog.md`
18. Update MCP server description

## Decided questions

1. **`read_thinking` includes assistant responses** by default. The exchange is the unit of meaning. A correction without its antecedent is unintelligible. Users can pass `include_assistant=False` to see user turns only.

2. **Trajectory computed over user turns.** The human's thinking trajectory is what matters for metalogue assessment. The assistant's volume is relatively uniform and dilutes the signal.

3. **`related` uses keyword overlap from pre-computed `concept_keywords`.** Honest about its limitations — vocabulary overlap, not semantic similarity. Sufficient for v1 discovery. TF-IDF is the first upgrade path; embeddings are deferred.

4. **Server name stays `qino-lingo`.** It's the repo name and already established.

5. **Algorithm changelog** lives at `docs/signal-algorithm-changelog.md`.

6. **Annotations replace tags.** General-purpose, multiple per conversation, passage-level, kind-typed. Tagging CRUD lives in `db.py` — not metalogue-specific.

7. **Signals tool deferred.** Low demand from primary consumers. May be added in Phase 3 if needed for debugging.

## Future directions (noted, not designed)

- **Graph edges from corpus to concept nodes.** Conversations should be referenceable from qino-os — an edge from a concept node to a conversation with a label like "first articulation." Requires protocol-level decisions about how the corpus maps to the knowledge graph.
- **Longitudinal trajectory.** "How has my thinking about X changed over months?" Requires cross-conversation analysis, not per-conversation signals.
- **FTS5 for search.** The current full-text search reads every matching file from disk. At 750 files this is tolerable. When the corpus doubles, build an FTS5 virtual table on user turn content.
- **Provenance tracing.** "When was concept X first discussed?" Requires temporal ordering of search results and the ability to trace a concept forward through sessions.
