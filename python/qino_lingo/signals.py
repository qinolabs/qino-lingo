"""
Conversation signal extraction for the corpus explorer.

Pre-computes per-conversation signals: concept density, rich turns,
corrections, meta-awareness, trajectory shape, cross-referencing.

Usage:
    python -m qino_lingo.signals compute              # Full corpus
    python -m qino_lingo.signals compute --since 2026-04-01
    python -m qino_lingo.signals check                # Staleness check
    python -m qino_lingo.signals version              # Show algorithm info
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from .cleaning import clean_conversation, CleanedExchange
from .db import get_connection, DEFAULT_DB_PATH

ALGORITHM_VERSION = "v6"

PROJECT_DIR = Path(__file__).parent.parent.parent
CORPUS_DIR = PROJECT_DIR / "data" / "corpus"

# --- Signal vocabularies ---

CONCEPTUAL_KEYWORDS = [
    "essence", "emergence", "pattern", "tension", "resonance", "principle",
    "insight", "philosophy", "meaning", "quality", "relationship between",
    "what makes", "the nature of", "wondering", "deeper", "realization",
    "substrate", "encounter", "figure thread", "modality",
    "ecosystem", "attunement", "calibration", "epistemic", "abductive",
    "transcontextual", "bateson", "warm data", "recursive", "sensitivity",
    "disposition", "voicing", "contour", "awakening", "lineage",
    "what if we", "this reminds me", "this connects to", "the shape of",
    "there is something about", "the question is", "i noticed",
    "i realized", "it occurred to me", "the real", "the distinction",
    "what surprised", "the deeper", "fundamentally",
    "domain language", "design principle", "the potential",
    "porosity", "membrane", "tradition",
]

CORRECTION_PATTERNS = [
    r"(doesn't|does not|didn't|did not) (sit|feel|land) (right|well|good)",
    r"(that's |that is )not (what|how|the)",
    r"i think you (don't|do not) get",
    r"(skip|drop|stop|no[,.])",
    r"be (careful|aware)",
    r"the real (question|issue|point|problem)",
    r"not .{3,30} but ",
    r"^actually[,.]",
    r"my (concern|worry|sense) is",
    r"(i |we )(don't|shouldn't|should not) ",
    r"(this is off|this feels off|something.{0,10}off)",
    r"(let me|let's) (correct|clarify|push back)",
    r"(dangerous|misleading|wrong direction|misaligned)",
]

META_AWARENESS_PATTERNS = [
    r"i('m| am) noticing",
    r"let('s| us) pause",
    r"(the arc|an arc) (we|i|that)",
    r"(this|that|it) (is|feels) connected to",
    r"the thread (we|i|that|between)",
    r"what just happened",
    r"(we('re| are)|i('m| am)) (on|in the middle of|circling)",
    r"this conversation",
    r"looking back at (what|how|where)",
    r"(the same|exactly the) (tension|pattern|question|structure)",
    r"i (see|notice|recognize) (the|a) (pattern|arc|thread|connection|structure)",
]

MODALITY_FULLNAMES = [
    "qino-world", "qino-walk", "qino-drops", "qino-chronicles", "qino-journal",
    "qino-arc", "qino-frame", "qino-label", "lens-lab", "sound-lab",
]

BARE_MODALITY_NAMES = {
    "world": "world", "walk": "walk", "drops": "drops",
    "chronicles": "chronicles", "journal": "journal", "arc": "arc",
    "frame": "frame", "label": "label",
}


# --- Signal scoring functions ---


def score_conceptual(text: str) -> int:
    """Count conceptual keyword matches in text."""
    lower = text.lower()
    return sum(1 for kw in CONCEPTUAL_KEYWORDS if kw in lower)


def detect_correction(text: str) -> bool:
    """Detect user pushback/redirect patterns."""
    lower = text.lower()
    return any(re.search(p, lower) for p in CORRECTION_PATTERNS)


def detect_meta_awareness(text: str) -> bool:
    """Detect self-referential moments about the conversation's own structure."""
    lower = text.lower()
    return any(re.search(p, lower) for p in META_AWARENESS_PATTERNS)


def count_cross_refs(text: str) -> tuple[int, list[str]]:
    """Count distinct modalities referenced. Returns (diversity, keyword_list)."""
    lower = text.lower()
    mentioned: set[str] = set()

    for term in MODALITY_FULLNAMES:
        if term in lower:
            mentioned.add(term.replace("qino-", "").replace("-lab", ""))

    # Bare names count only when 2+ appear
    bare_found: set[str] = set()
    for bare, canonical in BARE_MODALITY_NAMES.items():
        if re.search(rf"\b{bare}\b", lower):
            bare_found.add(canonical)

    if len(bare_found) >= 2:
        mentioned.update(bare_found)

    diversity = max(0, len(mentioned) - 1)
    return diversity, sorted(mentioned)


# --- Trajectory ---


def compute_trajectory(exchanges: list[CleanedExchange]) -> str:
    """Classify conversation trajectory shape from cleaned exchanges.

    Divides into thirds, compares concept density across them.
    Returns: SHIFT, SUSTAINED, DEEPENING, FADING, or FLAT.
    """
    if len(exchanges) < 3:
        return "FLAT"

    third = len(exchanges) // 3
    opening = exchanges[:third]
    middle = exchanges[third : 2 * third]
    closing = exchanges[2 * third :]

    def density(exs: list[CleanedExchange]) -> float:
        total_words = sum(e.user_words for e in exs)
        if total_words == 0:
            return 0.0
        total_concept = sum(score_conceptual(e.user_text) for e in exs)
        return total_concept / total_words * 1000

    d_open = density(opening)
    d_mid = density(middle)
    d_close = density(closing)

    # Technical opening that becomes conceptual
    if d_open < d_close * 0.6 and d_close > 5:
        return "SHIFT"
    # Conceptual throughout
    if d_open > 5 and d_close > 5 and abs(d_open - d_close) < max(d_open, d_close) * 0.4:
        return "SUSTAINED"
    # Gets more conceptual over time
    if d_close > d_open * 1.5 and d_close > 5:
        return "DEEPENING"
    # Starts conceptual, becomes execution
    if d_open > d_close * 1.5 and d_open > 5:
        return "FADING"

    return "FLAT"


# --- Per-conversation analysis ---


@dataclass
class ConversationSignals:
    """Complete signal profile for one conversation."""

    filename: str
    metalogue_score: int = 0
    concept_density: float = 0.0
    reflective_turns: int = 0
    reflective_words: int = 0
    rich_turns: int = 0
    medium_rich_turns: int = 0
    very_rich_turns: int = 0
    corrections: int = 0
    meta_awareness: int = 0
    cross_diversity: int = 0
    terse_ratio: float = 0.0
    trajectory_shape: str = "FLAT"
    concept_keywords: list[str] = field(default_factory=list)
    best_preview: str = ""
    algorithm_version: str = ALGORITHM_VERSION


def analyze_conversation(filepath: Path) -> Optional[ConversationSignals]:
    """Run full signal analysis on a single conversation file.

    Returns None if the conversation has insufficient content.
    """
    try:
        exchanges = clean_conversation(filepath)
    except Exception:
        return None

    # Filter to reflective exchanges (not system, not terse)
    reflective = [e for e in exchanges if not e.is_system and not e.is_terse]
    if len(reflective) < 2:
        return None

    total_user_turns = len(exchanges)
    terse_count = sum(1 for e in exchanges if e.is_terse)
    system_count = sum(1 for e in exchanges if e.is_system)
    terse_ratio = terse_count / total_user_turns if total_user_turns > 0 else 0.0

    # Per-turn signals
    total_words = 0
    total_concept = 0
    very_rich = 0
    rich = 0
    medium_rich = 0
    correction_count = 0
    meta_count = 0
    all_concept_keywords: set[str] = set()
    best_turn_score = -1
    best_turn_text = ""

    for ex in reflective:
        total_words += ex.user_words
        concept = score_conceptual(ex.user_text)
        total_concept += concept

        # Track matched keywords
        lower = ex.user_text.lower()
        for kw in CONCEPTUAL_KEYWORDS:
            if kw in lower:
                all_concept_keywords.add(kw)

        # Rich turn tiers
        if ex.user_words >= 200 and concept >= 3:
            very_rich += 1
        if ex.user_words >= 100 and concept >= 3:
            rich += 1
        elif ex.user_words >= 60 and concept >= 2:
            medium_rich += 1

        # Correction and meta signals
        if detect_correction(ex.user_text):
            correction_count += 1
        if detect_meta_awareness(ex.user_text):
            meta_count += 1

        # Track best preview (richest turn)
        turn_score = concept * 10 + ex.user_words
        if turn_score > best_turn_score and concept >= 1:
            best_turn_score = turn_score
            best_turn_text = ex.user_text

    concept_per_1k = (total_concept / total_words * 1000) if total_words > 0 else 0.0

    # Cross-referencing
    all_text = " ".join(e.user_text for e in reflective)
    cross_diversity, _ = count_cross_refs(all_text)

    # Trajectory
    trajectory_shape = compute_trajectory(reflective)

    # Best preview: truncate at sentence boundary
    preview = best_turn_text[:700]
    if len(best_turn_text) > 700:
        cut = preview.rfind(". ")
        if cut > 400:
            preview = preview[: cut + 1]
        preview += " [...]"

    # --- Scoring (v6 algorithm) ---
    score = 0.0

    # Rich turns — three tiers
    score += very_rich * 20
    score += rich * 10
    score += medium_rich * 5

    # Bare long turns (long but not conceptual) — minimal signal
    bare_long = sum(1 for e in reflective if e.user_words >= 100) - rich
    score += max(0, bare_long) * 1

    # Concept density — strong signal with bonus tiers
    score += min(concept_per_1k * 6, 60)
    if concept_per_1k >= 10:
        score += 30
    elif concept_per_1k >= 8:
        score += 15

    # Correction/pushback signal (capped)
    score += min(correction_count * 3, 15)

    # Meta-awareness signal (capped, high value)
    score += min(meta_count * 8, 24)

    # Cross-referencing
    score += cross_diversity * 4

    # Low-density penalty
    if concept_per_1k < 4.0:
        score *= 0.5

    # Terse penalty
    if terse_ratio > 0.5:
        score *= 0.4
    elif terse_ratio > 0.3:
        score *= 0.7

    # Volume penalty for very long sessions
    if total_user_turns > 150:
        score *= 0.7
    elif total_user_turns > 100:
        score *= 0.85

    return ConversationSignals(
        filename=filepath.name,
        metalogue_score=round(score),
        concept_density=round(concept_per_1k, 1),
        reflective_turns=len(reflective),
        reflective_words=total_words,
        rich_turns=rich,
        medium_rich_turns=medium_rich,
        very_rich_turns=very_rich,
        corrections=correction_count,
        meta_awareness=meta_count,
        cross_diversity=cross_diversity,
        terse_ratio=round(terse_ratio, 2),
        trajectory_shape=trajectory_shape,
        concept_keywords=sorted(all_concept_keywords),
        best_preview=preview,
    )


# --- Database storage ---


def init_signal_tables(db_path: Path = DEFAULT_DB_PATH):
    """No-op retained for backwards compatibility.

    After Chunk 1 the canonical schema lives in
    python/qino_lingo/migrations/02-rebuild-fk-tables.sql. Both
    conversation_signals and annotations tables are created (and FK-
    rebuilt) by the migration runner. Callers like the MCP server still
    invoke this function on startup as a defensive no-op.
    """
    return None


def store_signals(
    signals: ConversationSignals,
    db_path: Path = DEFAULT_DB_PATH,
) -> bool:
    """Store or update signals for a conversation. Returns True if stored.

    Uses UPSERT on the filename FK target. After Chunk 1 the
    conversation_signals.filename column has UNIQUE NOT NULL with a
    cascade-update FK to files(filename), so the upsert is the natural
    write pattern: it preserves the existing row's id (which has no
    semantic meaning) while replacing all signal fields.
    """
    with get_connection(db_path) as conn:
        # Verify the parent file exists. After Chunk 1, FK enforcement
        # would refuse the insert anyway, but checking here lets us
        # return False gracefully instead of raising IntegrityError.
        row = conn.execute(
            "SELECT 1 FROM files WHERE filename = ?", (signals.filename,)
        ).fetchone()
        if not row:
            return False

        conn.execute(
            """
            INSERT INTO conversation_signals (
                filename, metalogue_score, concept_density,
                reflective_turns, reflective_words,
                rich_turns, medium_rich_turns, very_rich_turns,
                corrections, meta_awareness, cross_diversity,
                terse_ratio, trajectory_shape, concept_keywords,
                best_preview, computed_at, algorithm_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
            ON CONFLICT(filename) DO UPDATE SET
                metalogue_score = excluded.metalogue_score,
                concept_density = excluded.concept_density,
                reflective_turns = excluded.reflective_turns,
                reflective_words = excluded.reflective_words,
                rich_turns = excluded.rich_turns,
                medium_rich_turns = excluded.medium_rich_turns,
                very_rich_turns = excluded.very_rich_turns,
                corrections = excluded.corrections,
                meta_awareness = excluded.meta_awareness,
                cross_diversity = excluded.cross_diversity,
                terse_ratio = excluded.terse_ratio,
                trajectory_shape = excluded.trajectory_shape,
                concept_keywords = excluded.concept_keywords,
                best_preview = excluded.best_preview,
                computed_at = CURRENT_TIMESTAMP,
                algorithm_version = excluded.algorithm_version
            """,
            (
                signals.filename,
                signals.metalogue_score,
                signals.concept_density,
                signals.reflective_turns,
                signals.reflective_words,
                signals.rich_turns,
                signals.medium_rich_turns,
                signals.very_rich_turns,
                signals.corrections,
                signals.meta_awareness,
                signals.cross_diversity,
                signals.terse_ratio,
                signals.trajectory_shape,
                json.dumps(signals.concept_keywords),
                signals.best_preview,
                signals.algorithm_version,
            ),
        )
        return True


def check_staleness(db_path: Path = DEFAULT_DB_PATH) -> dict:
    """Check the signal layer's health.

    Originally this only caught algorithm-version drift. Chunk 4 widened
    it to surface every shape of "the signal layer is out of date with
    the file layer" the iteration cares about, so callers like the MCP
    server's startup hook get a single answer to "is this corpus
    healthy enough to serve?":

    - `stale_count` — signal rows whose `algorithm_version` != current.
      Fix: `python -m python.qino_lingo.signals compute`.
    - `coverage_gap` — `status='active'` files with no `conversation_signals`
      row. After Chunk 4 these should normally be zero because
      `compute_all` flips unscorable files to `status='empty'`. A
      non-zero value is a real signal that `make signals` needs to run.
    - `orphan_signal_rows` — signal rows whose filename does not resolve
      to a `files` row. With FK enforcement on (Chunk 1) this should be
      zero; surfacing it lets the MCP server prove its joins are clean.

    The boolean `is_stale` flips on for ANY of the three. Existing
    callers that only branch on `is_stale` continue to work; new
    callers can read the per-finding counts to render a useful warning.

    The function name is preserved for backwards compatibility — at
    this point "staleness" has stretched to mean "signal layer health"
    rather than just "algorithm version drift," but renaming it would
    churn callers without payoff. The companion `doctor` module is the
    home for richer health reporting.
    """
    with get_connection(db_path) as conn:
        stale = conn.execute(
            "SELECT COUNT(*) FROM conversation_signals WHERE algorithm_version != ?",
            (ALGORITHM_VERSION,),
        ).fetchone()[0]

        total = conn.execute(
            "SELECT COUNT(*) FROM conversation_signals"
        ).fetchone()[0]

        coverage_gap = conn.execute(
            """
            SELECT COUNT(*) FROM files f
            WHERE f.status = 'active'
            AND f.filename NOT IN (SELECT filename FROM conversation_signals)
            """
        ).fetchone()[0]

        orphan_signal_rows = conn.execute(
            """
            SELECT COUNT(*) FROM conversation_signals cs
            WHERE cs.filename NOT IN (SELECT filename FROM files)
            """
        ).fetchone()[0]

        return {
            "current_version": ALGORITHM_VERSION,
            "total_computed": total,
            "stale_count": stale,
            "coverage_gap": coverage_gap,
            "orphan_signal_rows": orphan_signal_rows,
            "is_stale": (
                stale > 0
                or coverage_gap > 0
                or orphan_signal_rows > 0
            ),
        }


def mark_status(filename: str, status: str, db_path: Path = DEFAULT_DB_PATH) -> None:
    """Update files.status for one filename. Internal helper.

    Used by compute_all to flip files into `empty` (when the v6 algorithm
    refuses to score them) or `missing` (when the markdown file is gone
    from disk). Both are recorded reasons that doctor reads to distinguish
    "real coverage hole" from "expected baseline."
    """
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE files SET status = ? WHERE filename = ?",
            (status, filename),
        )


def compute_all(
    corpus_dir: Path = CORPUS_DIR,
    db_path: Path = DEFAULT_DB_PATH,
    since: Optional[str] = None,
):
    """Compute signals for all active conversations and store in DB.

    After Chunk 2, the noise/active distinction lives in files.status,
    not in filesystem location. This function queries the db for
    status='active' rows instead of globbing the corpus directory —
    that way noise files (which now physically live alongside active
    files at the top level of data/corpus/) are correctly skipped.

    Chunk 4 addition: when `analyze_conversation` returns None for an
    active file (the v6 algorithm refused to score it because the
    cleaned exchange list has fewer than 2 non-system non-terse turns),
    flip the file's status from 'active' to 'empty'. The 'empty' enum
    value was added in migration 03-extend-status-enum.sql precisely so
    that doctor's signal-coverage audit can distinguish "no signal row
    because the file is legitimately too thin to score" from "no signal
    row because something is broken." Without this flip, every fresh
    pass through compute_all rebuilds the same hidden bucket of 300+
    files that look like coverage holes but aren't.

    Likewise, files that are 'active' in db but missing on disk are
    flipped to 'missing' so the next doctor run sees a clean
    reconciliation rather than the same drift surfaced over and over.

    The query walks BOTH `status='active'` AND `status='empty'`. The
    asymmetry — empty walked but noise/missing not — exists so an
    algorithm bump (v6 -> v7) can rehydrate previously-empty files
    automatically: if a file that was unscorable under v6 produces a
    result under v7, compute_all promotes it back to 'active' and
    stores the signals. Without this, a `mark_status('empty')` would
    be a one-way trip and the empty bucket would gradually pollute
    with files that are only "empty" relative to a stale algorithm.

    Args:
        corpus_dir: Directory containing conversation markdown files
                    (used to resolve filenames to filepaths)
        db_path: Database path
        since: Only compute for files dated on or after this date (YYYY-MM-DD)
    """
    query = "SELECT filename, status FROM files WHERE status IN ('active', 'empty')"
    params: tuple = ()
    if since:
        query += " AND date >= ?"
        params = (since,)
    query += " ORDER BY filename"

    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        candidates = [(r[0], r[1]) for r in rows]

    print(f"Computing signals for {len(candidates)} candidate conversations "
          f"(active + empty)...")
    computed = 0
    promoted = 0
    marked_empty = 0
    marked_missing = 0
    skipped = 0

    for filename, current_status in candidates:
        filepath = corpus_dir / filename
        if not filepath.exists():
            mark_status(filename, "missing", db_path)
            marked_missing += 1
            continue
        signals = analyze_conversation(filepath)
        if signals:
            if store_signals(signals, db_path):
                computed += 1
                if current_status == "empty":
                    mark_status(filename, "active", db_path)
                    promoted += 1
            else:
                skipped += 1
        else:
            if current_status != "empty":
                mark_status(filename, "empty", db_path)
                marked_empty += 1

    msg = f"Done: {computed} computed"
    if promoted:
        msg += f", {promoted} promoted empty -> active"
    if marked_empty:
        msg += f", {marked_empty} marked empty"
    if marked_missing:
        msg += f", {marked_missing} marked missing"
    if skipped:
        msg += f", {skipped} skipped"
    print(msg)
    return computed


# --- CLI ---


def main():
    parser = argparse.ArgumentParser(description="Conversation signal analysis")
    sub = parser.add_subparsers(dest="command")

    compute_cmd = sub.add_parser("compute", help="Compute signals for corpus")
    compute_cmd.add_argument("--since", help="Only files since date (YYYY-MM-DD)")
    compute_cmd.add_argument("--db", default=str(DEFAULT_DB_PATH))
    compute_cmd.add_argument("--corpus", default=str(CORPUS_DIR))

    check_cmd = sub.add_parser("check", help="Check for stale signals")
    check_cmd.add_argument("--db", default=str(DEFAULT_DB_PATH))

    sub.add_parser("version", help="Show algorithm version")

    args = parser.parse_args()

    if args.command == "compute":
        compute_all(
            corpus_dir=Path(args.corpus),
            db_path=Path(args.db),
            since=args.since,
        )
    elif args.command == "check":
        result = check_staleness(Path(args.db))
        print(f"Algorithm version: {result['current_version']}")
        print(f"Computed signals:  {result['total_computed']}")
        print(f"Stale rows:        {result['stale_count']}")
        print(f"Coverage gap:      {result['coverage_gap']}")
        print(f"Orphan signal rows:{result['orphan_signal_rows']}")
        if result["is_stale"]:
            print()
            print(
                "WARNING: signal layer is out of date — run "
                "'python -m python.qino_lingo.signals compute' "
                "or 'make doctor' for the full report"
            )
        else:
            print()
            print("All signals up to date")
    elif args.command == "version":
        print(f"Algorithm version: {ALGORITHM_VERSION}")
        print(f"Changelog: docs/signal-algorithm-changelog.md")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
