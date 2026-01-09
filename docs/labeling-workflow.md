# Labeling Workflow

The intended process for building an epistemological signature through human labeling.

## Philosophy

This is **active learning** — the system starts knowing nothing about what makes a conversation "rich." That knowledge emerges through your labeling, not from predefined rules.

What you're noticing:
- Not topic or content
- The *quality* of epistemic moves
- How thinking happens, not what it's about

## The Core Loop

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
│  Mark (optional)│  ← Name the pattern if one emerges
└────────┬────────┘
         ▼
┌─────────────────┐
│  Repeat         │  ← Vocabulary grows through repetition
└─────────────────┘
```

## Phase 1: Binary Labeling

Start simple. For each conversation:

1. **Sample** — Use stratified sampling to get diverse examples
2. **Read** — Read the full conversation (or a segment)
3. **Judge** — Is this rich? Yes or no.
4. **Annotate** — Write 1-2 sentences about why

Don't overthink. Trust your gut. The goal is volume and diversity.

```python
from lib.sampler import sample_stratified
from lib.db import add_label, get_file

# Get samples
samples = sample_stratified(n_per_stratum=2)

# Review one
file = samples['high_engagement'][0]
# ... read the conversation ...

# Label it (rating: 1=thin, 2=functional, 3=rich)
add_label(
    file_id=file['id'],
    rating=3,  # rich
    tags=["framing-before-solving"],
    notes="Beautiful reframing at turn 4. Question held open before resolving."
)
```

## Phase 2: Marker Emergence

After labeling ~50 conversations, patterns will start appearing in your notes. When you notice the same quality recurring:

1. **Name it** — Create a marker
2. **Describe it** — What does this pattern look like?
3. **Exemplify it** — Link the specific excerpt

```python
from lib.db import add_marker, add_example

# Create marker
marker_id = add_marker(
    name="productive-uncertainty",
    description="Holding a question open, resisting premature resolution, exploring the space around ambiguity"
)

# Link example
add_example(
    marker_id=marker_id,
    file_id=file['id'],
    turn_start=3,
    turn_end=5,
    excerpt="The actual text here...",
    notes="Turn 4 shows the question being held without rushing to answer"
)
```

## Phase 3: Vocabulary Refinement

As markers accumulate:

- **Merge** similar markers (update examples to new marker)
- **Split** markers that are too broad
- **Rename** for clarity
- **Describe** more precisely based on examples

The vocabulary is living. It grows and refines through use.

## Labeling Signals

These signals help surface candidates, but **don't determine richness**:

| Signal | What it might indicate |
|--------|------------------------|
| High substantive turns | Extended dialogue, more opportunity for depth |
| Reflective language | Self-aware, meta-cognitive content |
| High dialogue density | Dense user input, engaged participation |
| Agent sessions | Complex multi-step tasks with decisions |

**Important:** A conversation with none of these signals can still be rich. A conversation with all of them can still be flat. Signals surface candidates; judgment determines richness.

## What "Rich" Might Mean

Not a definition, but hints from the original inquiry:

- **Framing before solving** — Problem space explored before solutions offered
- **Productive uncertainty** — Ambiguity held, not collapsed
- **Meta-awareness** — Conversation notices its own quality
- **Integrative synthesis** — Ideas combined in novel ways
- **Resistance and integration** — Suggestions tested before accepting
- **Follow-up depth** — Questions that go deeper, not sideways

These are starting intuitions. Your labeling will discover what richness actually means in this corpus.

## Practical Tips

### Speed over perfection

Label many conversations loosely rather than few precisely. Patterns emerge from volume.

### Trust disagreement with yourself

If you labeled something rich yesterday and similar content not-rich today, that's data. Notice what shifted.

### Annotate in the moment

Write notes immediately after judging. Don't reconstruct later — that's a different mind.

### Use the whole conversation

Full context matters. A segment might look flat in isolation but be brilliant in context.

### Name patterns tentatively

Markers can be renamed. Don't wait for the perfect name.

## Progress Tracking

```python
from lib.sampler import get_labeling_progress

progress = get_labeling_progress()
# {
#     'total': 999,
#     'labeled': 42,
#     'unlabeled': 957,
#     'thin': 8,
#     'functional': 16,
#     'rich': 18,
#     'progress_pct': 4.2
# }
```

## Milestones

| Milestone | What happens |
|-----------|--------------|
| 50 labels | First markers emerge from note patterns |
| 100 labels | Vocabulary stabilizes, inter-rater reliability possible |
| 200 labels | Pattern detection experiments viable |
| 500 labels | Semi-automated surfacing possible |
