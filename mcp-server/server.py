"""
MCP server for qino-lingo conversation corpus.

Exposes search, retrieval, discovery, and annotation operations
via the Model Context Protocol.

Two use cases share this server:
1. Training data — epistemic signature labeling (original)
2. Conversation exploration — metalogue sourcing, provenance, discovery (new)
"""

import json
import sys
from pathlib import Path
from typing import Optional

from fastmcp import FastMCP

# Add parent directory to path so we can import qino_lingo
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from qino_lingo.db import (
    get_connection,
    add_annotation,
    get_annotations,
    get_file_by_session,
)
from qino_lingo.parser import parse_conversation
from qino_lingo.cleaning import clean_conversation, CleanedExchange
from qino_lingo.signals import (
    ALGORITHM_VERSION,
    check_staleness,
    score_conceptual,
    detect_correction,
    detect_meta_awareness,
)

# Paths
PROJECT_DIR = Path(__file__).parent.parent
DB_PATH = PROJECT_DIR / "corpus.db"
CORPUS_DIR = PROJECT_DIR / "data" / "corpus"

mcp = FastMCP(
    "qino-lingo",
    instructions=(
        "Conversation corpus explorer — search, analyze, and discover "
        "material from Claude conversation archives. "
        "Use candidates() to scan ranked conversations, read_thinking() to read "
        "cleaned exchanges, annotate() to mark findings."
    ),
)

# Schema is owned by python/qino_lingo/migrations/. The MCP server
# trusts it has been applied via `make migrate`. No defensive DDL here.

# Check staleness on startup
_staleness = check_staleness(DB_PATH)
if _staleness["is_stale"]:
    print(
        f"WARNING: {_staleness['stale_count']} conversation signals are stale "
        f"(stored: mixed, current: {ALGORITHM_VERSION}). "
        f"Run: python -m qino_lingo.signals compute",
        file=sys.stderr,
    )


# ============================================================
# Existing tools (enhanced)
# ============================================================


@mcp.tool()
def search(
    pattern: str,
    user_only: bool = False,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    min_turns: Optional[int] = None,
    has_reflective: Optional[bool] = None,
    min_concept_density: Optional[float] = None,
    limit: int = 20,
) -> list[dict]:
    """
    Search conversations by content pattern and metadata filters.

    Args:
        pattern: Text to search for (case-insensitive)
        user_only: Only search within user turns (ignores assistant content)
        date_from: Conversations on or after this date (YYYY-MM-DD)
        date_to: Conversations on or before this date (YYYY-MM-DD)
        min_turns: Minimum substantive user turns
        has_reflective: Filter for reflective language markers
        min_concept_density: Minimum concept density from signal analysis
        limit: Maximum results (default 20)

    Returns:
        Matching conversations with snippet, metadata, and signals if available
    """
    results = []
    pattern_lower = pattern.lower()

    query = "SELECT f.* FROM files f WHERE f.status = 'active'"
    params: list = []

    if date_from:
        query += " AND f.date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND f.date <= ?"
        params.append(date_to)
    if min_turns is not None:
        query += " AND f.substantive_user_turns >= ?"
        params.append(min_turns)
    if has_reflective is not None:
        query += " AND f.has_reflective_language = ?"
        params.append(has_reflective)

    if min_concept_density is not None:
        query += """
            AND f.filename IN (
                SELECT filename FROM conversation_signals
                WHERE concept_density >= ?
            )
        """
        params.append(min_concept_density)

    query += " ORDER BY f.date DESC"

    with get_connection(DB_PATH) as conn:
        rows = conn.execute(query, params).fetchall()

        for row in rows:
            file_info = dict(row)
            filepath = CORPUS_DIR / file_info["filename"]

            if not filepath.exists():
                continue

            content = filepath.read_text()

            if user_only:
                # Extract only user sections for searching
                import re

                user_sections = re.split(
                    r"^## 👤 User$", content, flags=re.MULTILINE
                )[1:]
                searchable = "\n".join(
                    s.split("## 🤖 Claude")[0] for s in user_sections
                )
            else:
                searchable = content

            if pattern_lower not in searchable.lower():
                continue

            # Extract snippet around match
            search_lower = searchable.lower()
            match_pos = search_lower.find(pattern_lower)
            start = max(0, match_pos - 150)
            end = min(len(searchable), match_pos + len(pattern) + 150)
            snippet = searchable[start:end].strip()
            if start > 0:
                snippet = "..." + snippet
            if end < len(searchable):
                snippet = snippet + "..."

            # Get signals if available
            signal_row = conn.execute(
                "SELECT metalogue_score, concept_density, trajectory_shape "
                "FROM conversation_signals WHERE filename = ?",
                (file_info["filename"],),
            ).fetchone()

            result = {
                "session_id": file_info["claude_session_id"],
                "filename": file_info["filename"],
                "date": file_info["date"],
                "snippet": snippet,
                "substantive_turns": file_info["substantive_user_turns"],
                "user_word_count": file_info["user_word_count"],
            }

            if signal_row:
                result["metalogue_score"] = signal_row[0]
                result["concept_density"] = signal_row[1]
                result["trajectory_shape"] = signal_row[2]

            results.append(result)

            if len(results) >= limit:
                break

    return results


@mcp.tool()
def get(
    session_id: str,
    view: str = "raw",
    range_start: Optional[int] = None,
    range_end: Optional[int] = None,
) -> dict:
    """
    Retrieve a conversation by session ID.

    Args:
        session_id: Session identifier (from search results or filename)
        view: "raw" (full transcript), "clean" (noise stripped),
              "thinking" (only rich/correction/meta exchanges),
              "exchanges" (all exchanges, numbered)
        range_start: First exchange index to include (works with any view)
        range_end: Last exchange index to include

    Returns:
        Conversation data. For non-raw views, returns exchange-level data
        with user and assistant content paired.
    """
    file_info = get_file_by_session(session_id, DB_PATH)
    if not file_info:
        return {"error": f"Session not found: {session_id}"}

    filepath = CORPUS_DIR / file_info["filename"]

    if not filepath.exists():
        return {"error": f"File not found: {file_info['filename']}"}

    # Raw view — original behavior
    if view == "raw":
        try:
            conversation = parse_conversation(filepath)
            turns = [
                {
                    "index": t.index,
                    "role": t.role,
                    "content": t.content,
                    "word_count": t.word_count,
                }
                for t in conversation.turns
            ]
            return {
                "session_id": file_info["claude_session_id"],
                "filename": file_info["filename"],
                "date": file_info["date"],
                "view": "raw",
                "turns": turns,
            }
        except Exception as e:
            return {"error": f"Parse failed: {e}"}

    # Exchange-level views
    try:
        exchanges = clean_conversation(filepath)
    except Exception as e:
        return {"error": f"Clean failed: {e}"}

    # Apply range filter
    if range_start is not None or range_end is not None:
        start = range_start if range_start is not None else 0
        end = (range_end if range_end is not None else len(exchanges) - 1) + 1
        exchanges = [e for e in exchanges if start <= e.index < end]

    def exchange_to_dict(
        ex: CleanedExchange, include_signals: bool = False
    ) -> dict:
        d: dict = {
            "index": ex.index,
            "user_text": ex.user_text,
            "user_words": ex.user_words,
        }
        if ex.assistant_text:
            d["assistant_text"] = ex.assistant_text
        if include_signals:
            signals = []
            concept = score_conceptual(ex.user_text)
            d["concept_score"] = concept
            if detect_correction(ex.user_text):
                signals.append("correction")
            if detect_meta_awareness(ex.user_text):
                signals.append("meta_awareness")
            if ex.user_words >= 200 and concept >= 3:
                signals.append("very_rich")
            elif ex.user_words >= 100 and concept >= 3:
                signals.append("rich")
            elif ex.user_words >= 60 and concept >= 2:
                signals.append("medium_rich")
            d["signals"] = signals
        return d

    if view == "exchanges":
        # All exchanges, numbered, no signal annotation
        filtered = [e for e in exchanges if not e.is_system]
        return {
            "session_id": file_info["claude_session_id"],
            "filename": file_info["filename"],
            "date": file_info["date"],
            "view": "exchanges",
            "total_exchanges": len(filtered),
            "exchanges": [exchange_to_dict(e) for e in filtered],
        }

    if view == "clean":
        # All non-system, non-terse exchanges
        filtered = [e for e in exchanges if not e.is_system and not e.is_terse]
        return {
            "session_id": file_info["claude_session_id"],
            "filename": file_info["filename"],
            "date": file_info["date"],
            "view": "clean",
            "total_exchanges": len(filtered),
            "exchanges": [exchange_to_dict(e) for e in filtered],
        }

    if view == "thinking":
        # Only exchanges with signals: rich, correction, or meta-awareness
        filtered = []
        for e in exchanges:
            if e.is_system or e.is_terse:
                continue
            concept = score_conceptual(e.user_text)
            is_rich = (e.user_words >= 60 and concept >= 2)
            is_correction = detect_correction(e.user_text)
            is_meta = detect_meta_awareness(e.user_text)
            if is_rich or is_correction or is_meta:
                filtered.append(e)

        # Get trajectory from DB
        trajectory = "unknown"
        density = None
        with get_connection(DB_PATH) as conn:
            sig_row = conn.execute(
                "SELECT trajectory_shape, concept_density FROM conversation_signals WHERE filename = ?",
                (file_info["filename"],),
            ).fetchone()
            if sig_row:
                trajectory = sig_row[0]
                density = sig_row[1]

        return {
            "session_id": file_info["claude_session_id"],
            "filename": file_info["filename"],
            "date": file_info["date"],
            "view": "thinking",
            "total_thinking_exchanges": len(filtered),
            "trajectory_shape": trajectory,
            "concept_density": density,
            "exchanges": [exchange_to_dict(e, include_signals=True) for e in filtered],
        }

    return {"error": f"Unknown view: {view}. Use: raw, clean, exchanges, thinking"}


@mcp.tool()
def metadata(session_id: str) -> dict:
    """
    Get metadata, signals, and annotations for a conversation.

    Args:
        session_id: Session identifier

    Returns:
        Full metadata including conversation signals and annotations
    """
    file_info = get_file_by_session(session_id, DB_PATH)
    if not file_info:
        return {"error": f"Session not found: {session_id}"}

    with get_connection(DB_PATH) as conn:
        # Labels
        labels = conn.execute(
            "SELECT rating, turn_start, turn_end, tags, notes FROM labels WHERE filename = ?",
            (file_info["filename"],),
        ).fetchall()

        # Signals
        sig_row = conn.execute(
            "SELECT * FROM conversation_signals WHERE filename = ?",
            (file_info["filename"],),
        ).fetchone()

        # Annotations
        ann_rows = conn.execute(
            "SELECT kind, value, thread, notes, exchange_start, exchange_end, source, created_at "
            "FROM annotations WHERE filename = ?",
            (file_info["filename"],),
        ).fetchall()

    result = {
        "session_id": file_info["claude_session_id"],
        "filename": file_info["filename"],
        "date": file_info["date"],
        "status": file_info["status"],
        "is_agent": bool(file_info["is_agent"]),
        "turn_counts": {
            "user": file_info["user_turns"],
            "claude": file_info["claude_turns"],
            "substantive_user": file_info["substantive_user_turns"],
        },
        "word_counts": {
            "user": file_info["user_word_count"],
            "claude": file_info["claude_word_count"],
        },
        "dialogue_density": file_info["dialogue_density"],
        "has_reflective_language": bool(file_info["has_reflective_language"]),
    }

    if labels:
        result["labels"] = [dict(l) for l in labels]

    if sig_row:
        sig = dict(sig_row)
        result["signals"] = {
            "metalogue_score": sig["metalogue_score"],
            "concept_density": sig["concept_density"],
            "trajectory_shape": sig["trajectory_shape"],
            "reflective_turns": sig["reflective_turns"],
            "rich_turns": sig["rich_turns"],
            "corrections": sig["corrections"],
            "meta_awareness": sig["meta_awareness"],
            "cross_diversity": sig["cross_diversity"],
            "best_preview": sig["best_preview"],
            "algorithm_version": sig["algorithm_version"],
        }

    if ann_rows:
        result["annotations"] = [dict(a) for a in ann_rows]

    return result


@mcp.tool()
def stats() -> dict:
    """
    Get corpus-level statistics including signal aggregates.

    Returns:
        File counts, word counts, labeling progress, signal distribution
    """
    with get_connection(DB_PATH) as conn:
        result: dict = {}

        result["total_files"] = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        result["labeled_files"] = conn.execute(
            "SELECT COUNT(DISTINCT filename) FROM labels"
        ).fetchone()[0]

        status_rows = conn.execute(
            "SELECT status, COUNT(*) FROM files GROUP BY status"
        ).fetchall()
        result["by_status"] = {r[0]: r[1] for r in status_rows}

        rating_rows = conn.execute(
            "SELECT rating, COUNT(*) FROM labels GROUP BY rating"
        ).fetchall()
        result["by_rating"] = {r[0]: r[1] for r in rating_rows}

        words = conn.execute(
            "SELECT SUM(user_word_count), SUM(claude_word_count) FROM files WHERE status = 'active'"
        ).fetchone()
        result["total_user_words"] = words[0] or 0
        result["total_claude_words"] = words[1] or 0

        date_row = conn.execute(
            "SELECT MIN(date), MAX(date) FROM files WHERE status = 'active'"
        ).fetchone()
        result["date_range"] = {"earliest": date_row[0], "latest": date_row[1]}

        # Signal aggregates
        sig_total = conn.execute("SELECT COUNT(*) FROM conversation_signals").fetchone()[0]
        result["signals"] = {"computed": sig_total}

        if sig_total > 0:
            for threshold in [50, 100, 150, 200]:
                count = conn.execute(
                    "SELECT COUNT(*) FROM conversation_signals WHERE metalogue_score >= ?",
                    (threshold,),
                ).fetchone()[0]
                result["signals"][f"score_gte_{threshold}"] = count

            shapes = conn.execute(
                "SELECT trajectory_shape, COUNT(*) FROM conversation_signals GROUP BY trajectory_shape"
            ).fetchall()
            result["signals"]["by_trajectory"] = {r[0]: r[1] for r in shapes}

            staleness = check_staleness(DB_PATH)
            result["signals"]["algorithm_version"] = staleness["current_version"]
            result["signals"]["stale"] = staleness["is_stale"]

        # Annotation aggregates
        ann_total = conn.execute("SELECT COUNT(*) FROM annotations").fetchone()[0]
        result["annotations"] = {"total": ann_total}
        if ann_total > 0:
            kinds = conn.execute(
                "SELECT kind, COUNT(*) FROM annotations GROUP BY kind"
            ).fetchall()
            result["annotations"]["by_kind"] = {r[0]: r[1] for r in kinds}

        return result


# ============================================================
# New tools — Discovery
# ============================================================


@mcp.tool()
def candidates(
    top: int = 30,
    min_score: int = 0,
    min_density: float = 0.0,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    unannotated_only: bool = False,
    trajectory: Optional[str] = None,
) -> list[dict]:
    """
    List conversations ranked by metalogue score.

    Designed for scanning: one line per conversation with key metrics
    and a preview of the highest-signal user turn.

    Args:
        top: Maximum results (default 30)
        min_score: Minimum metalogue score
        min_density: Minimum concept density
        date_from: Conversations on or after this date
        date_to: Conversations on or before this date
        unannotated_only: Exclude conversations with metalogue_verdict annotations
        trajectory: Filter by trajectory shape (SHIFT, SUSTAINED, DEEPENING, FADING, FLAT)

    Returns:
        Ranked list with score, metrics, and best_preview per conversation
    """
    query = """
        SELECT cs.*, f.claude_session_id, f.date, f.user_word_count
        FROM conversation_signals cs
        JOIN files f ON cs.filename = f.filename
        WHERE f.status = 'active'
        AND cs.metalogue_score >= ?
        AND cs.concept_density >= ?
    """
    params: list = [min_score, min_density]

    if date_from:
        query += " AND f.date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND f.date <= ?"
        params.append(date_to)
    if trajectory:
        query += " AND cs.trajectory_shape = ?"
        params.append(trajectory)
    if unannotated_only:
        query += """
            AND f.filename NOT IN (
                SELECT filename FROM annotations WHERE kind = 'metalogue_verdict'
            )
        """

    query += " ORDER BY cs.metalogue_score DESC LIMIT ?"
    params.append(top)

    with get_connection(DB_PATH) as conn:
        rows = conn.execute(query, params).fetchall()

    return [
        {
            "session_id": r["claude_session_id"],
            "filename": r["filename"],
            "date": r["date"],
            "metalogue_score": r["metalogue_score"],
            "concept_density": r["concept_density"],
            "trajectory_shape": r["trajectory_shape"],
            "rich_turns": r["rich_turns"],
            "corrections": r["corrections"],
            "meta_awareness": r["meta_awareness"],
            "reflective_turns": r["reflective_turns"],
            "user_word_count": r["user_word_count"],
            "best_preview": r["best_preview"],
        }
        for r in rows
    ]


@mcp.tool()
def read_thinking(
    session_id: str,
    min_concept: int = 0,
    include_assistant: bool = True,
) -> dict:
    """
    Read the thinking exchanges from a conversation.

    Returns only exchanges where genuine thinking is visible: rich turns,
    corrections, meta-awareness moments. Each exchange includes user text,
    assistant text, and signal annotations.

    Args:
        session_id: Session identifier
        min_concept: Minimum concept score per exchange (0 = include all signal turns)
        include_assistant: Include assistant response in each exchange (default True)

    Returns:
        Signal-annotated exchanges with conversation-level summary
    """
    file_info = get_file_by_session(session_id, DB_PATH)
    if not file_info:
        return {"error": f"Session not found: {session_id}"}

    filepath = CORPUS_DIR / file_info["filename"]
    if not filepath.exists():
        return {"error": f"File not found: {file_info['filename']}"}

    try:
        exchanges = clean_conversation(filepath)
    except Exception as e:
        return {"error": f"Clean failed: {e}"}

    # Filter to thinking exchanges
    thinking: list[dict] = []
    for ex in exchanges:
        if ex.is_system or ex.is_terse:
            continue

        concept = score_conceptual(ex.user_text)
        if concept < min_concept:
            is_correction = detect_correction(ex.user_text)
            is_meta = detect_meta_awareness(ex.user_text)
            is_rich = ex.user_words >= 60 and concept >= 2
            if not (is_correction or is_meta or is_rich):
                continue
        else:
            is_correction = detect_correction(ex.user_text)
            is_meta = detect_meta_awareness(ex.user_text)
            is_rich = ex.user_words >= 60 and concept >= 2

        signals = []
        if is_correction:
            signals.append("correction")
        if is_meta:
            signals.append("meta_awareness")
        if ex.user_words >= 200 and concept >= 3:
            signals.append("very_rich")
        elif ex.user_words >= 100 and concept >= 3:
            signals.append("rich")
        elif is_rich:
            signals.append("medium_rich")

        if not signals and concept < min_concept:
            continue

        entry: dict = {
            "index": ex.index,
            "user_text": ex.user_text,
            "user_words": ex.user_words,
            "concept_score": concept,
            "signals": signals,
        }
        if include_assistant and ex.assistant_text:
            entry["assistant_text"] = ex.assistant_text

        thinking.append(entry)

    # Get signals from DB
    trajectory = "unknown"
    density = None
    with get_connection(DB_PATH) as conn:
        sig_row = conn.execute(
            "SELECT trajectory_shape, concept_density, metalogue_score "
            "FROM conversation_signals WHERE filename = ?",
            (file_info["filename"],),
        ).fetchone()
        if sig_row:
            trajectory = sig_row[0]
            density = sig_row[1]

    return {
        "session_id": file_info["claude_session_id"],
        "filename": file_info["filename"],
        "date": file_info["date"],
        "total_thinking_exchanges": len(thinking),
        "trajectory_shape": trajectory,
        "concept_density": density,
        "metalogue_score": sig_row[2] if sig_row else None,
        "exchanges": thinking,
    }


@mcp.tool()
def annotate(
    session_id: str,
    kind: str,
    value: Optional[str] = None,
    thread: Optional[str] = None,
    notes: Optional[str] = None,
    exchange_start: Optional[int] = None,
    exchange_end: Optional[int] = None,
    source: str = "human",
) -> dict:
    """
    Add an annotation to a conversation.

    Supports whole-conversation and passage-level annotations.
    Multiple annotations per conversation are allowed.

    Common kinds:
    - "metalogue_verdict": value is "Y", "M", or "N"
    - "highlight": mark a notable passage (use exchange_start/end)
    - "provenance": note what concept/decision emerged from this conversation

    Args:
        session_id: Session identifier
        kind: Annotation type (e.g., "metalogue_verdict", "highlight", "provenance")
        value: Annotation value (e.g., "Y" for verdict, free text for others)
        thread: Thematic grouping (e.g., "porosity", "encounter")
        notes: Free-text notes
        exchange_start: Start of passage (null = whole conversation)
        exchange_end: End of passage
        source: Who annotated ("human", agent name)
    """
    file_info = get_file_by_session(session_id, DB_PATH)
    if not file_info:
        return {"error": f"Session not found: {session_id}"}

    ann_id = add_annotation(
        filename=file_info["filename"],
        kind=kind,
        value=value,
        thread=thread,
        notes=notes,
        exchange_start=exchange_start,
        exchange_end=exchange_end,
        source=source,
        db_path=DB_PATH,
    )

    return {
        "id": ann_id,
        "session_id": file_info["claude_session_id"],
        "filename": file_info["filename"],
        "kind": kind,
        "value": value,
        "thread": thread,
        "saved": True,
    }


@mcp.tool()
def annotations(
    kind: Optional[str] = None,
    thread: Optional[str] = None,
    source: Optional[str] = None,
    verdict: Optional[str] = None,
) -> list[dict]:
    """
    List annotations, optionally filtered.

    Args:
        kind: Filter by annotation kind
        thread: Filter by thematic thread
        source: Filter by who annotated
        verdict: Shortcut for kind="metalogue_verdict" with this value

    Returns:
        Annotations with their conversation metadata
    """
    if verdict:
        kind = "metalogue_verdict"

    results = get_annotations(
        kind=kind,
        thread=thread,
        source=source,
        db_path=DB_PATH,
    )

    if verdict:
        results = [r for r in results if r.get("value") == verdict]

    return results


if __name__ == "__main__":
    mcp.run()
