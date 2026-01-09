"""
MCP server for qino-lingo conversation corpus.

Exposes search, retrieval, and metadata operations over the corpus
via the Model Context Protocol.
"""

import sys
from pathlib import Path
from typing import Optional

from fastmcp import FastMCP

# Add parent directory to path so we can import qino_lingo
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from qino_lingo.db import get_connection
from qino_lingo.parser import parse_conversation

# Paths
PROJECT_DIR = Path(__file__).parent.parent
DB_PATH = PROJECT_DIR / "corpus.db"
CORPUS_DIR = PROJECT_DIR / "data" / "corpus"

mcp = FastMCP("qino-lingo")


@mcp.tool()
def search(
    pattern: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    min_turns: Optional[int] = None,
    has_reflective: Optional[bool] = None,
    limit: int = 20
) -> list[dict]:
    """
    Search conversations by content pattern and metadata filters.

    Args:
        pattern: Text pattern to search for in conversation content (case-insensitive)
        date_from: Filter conversations on or after this date (YYYY-MM-DD)
        date_to: Filter conversations on or before this date (YYYY-MM-DD)
        min_turns: Minimum number of substantive user turns
        has_reflective: Filter for conversations with reflective language markers
        limit: Maximum number of results to return (default 20)

    Returns:
        List of matching conversations with session_id, date, snippet, and metadata
    """
    results = []
    pattern_lower = pattern.lower()

    # Build SQL query for metadata filtering
    query = "SELECT * FROM files WHERE status = 'active'"
    params = []

    if date_from:
        query += " AND date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND date <= ?"
        params.append(date_to)
    if min_turns is not None:
        query += " AND substantive_user_turns >= ?"
        params.append(min_turns)
    if has_reflective is not None:
        query += " AND has_reflective_language = ?"
        params.append(has_reflective)

    query += " ORDER BY date DESC"

    with get_connection(DB_PATH) as conn:
        rows = conn.execute(query, params).fetchall()

        for row in rows:
            file_info = dict(row)
            filepath = CORPUS_DIR / file_info['filename']

            if not filepath.exists():
                continue

            # Search within file content
            content = filepath.read_text()
            if pattern_lower not in content.lower():
                continue

            # Extract snippet around first match
            content_lower = content.lower()
            match_pos = content_lower.find(pattern_lower)
            start = max(0, match_pos - 100)
            end = min(len(content), match_pos + len(pattern) + 100)
            snippet = content[start:end]
            if start > 0:
                snippet = "..." + snippet
            if end < len(content):
                snippet = snippet + "..."

            results.append({
                "session_id": file_info['session_id'],
                "filename": file_info['filename'],
                "date": file_info['date'],
                "snippet": snippet.strip(),
                "substantive_turns": file_info['substantive_user_turns'],
                "user_word_count": file_info['user_word_count'],
                "has_reflective_language": bool(file_info['has_reflective_language'])
            })

            if len(results) >= limit:
                break

    return results


@mcp.tool()
def get(session_id: str) -> dict:
    """
    Retrieve full conversation content by session ID.

    Args:
        session_id: The session identifier (from search results or filename)

    Returns:
        Conversation data including metadata and structured turns
    """
    # Find file by session_id
    with get_connection(DB_PATH) as conn:
        row = conn.execute(
            "SELECT * FROM files WHERE session_id = ?",
            (session_id,)
        ).fetchone()

    if not row:
        return {"error": f"Session not found: {session_id}"}

    file_info = dict(row)
    filepath = CORPUS_DIR / file_info['filename']

    if not filepath.exists():
        return {"error": f"Conversation file not found: {file_info['filename']}"}

    # Parse conversation into structured format
    try:
        conversation = parse_conversation(filepath)

        turns = []
        for turn in conversation.turns:
            turns.append({
                "index": turn.index,
                "role": turn.role,
                "content": turn.content,
                "word_count": turn.word_count,
                "is_command": turn.is_command,
                "has_substantive_content": turn.has_substantive_content
            })

        return {
            "session_id": conversation.session_id,
            "filename": conversation.filename,
            "date": conversation.date,
            "turns": turns,
            "metadata": {
                "user_turns": file_info['user_turns'],
                "claude_turns": file_info['claude_turns'],
                "substantive_user_turns": file_info['substantive_user_turns'],
                "user_word_count": file_info['user_word_count'],
                "claude_word_count": file_info['claude_word_count'],
                "dialogue_density": file_info['dialogue_density'],
                "has_reflective_language": bool(file_info['has_reflective_language']),
                "is_agent": bool(file_info['is_agent'])
            }
        }
    except Exception as e:
        return {"error": f"Failed to parse conversation: {str(e)}"}


@mcp.tool()
def metadata(session_id: str) -> dict:
    """
    Get statistics and metadata for a conversation.

    Args:
        session_id: The session identifier

    Returns:
        Metadata including turn counts, word counts, dates, and status
    """
    with get_connection(DB_PATH) as conn:
        row = conn.execute(
            "SELECT * FROM files WHERE session_id = ?",
            (session_id,)
        ).fetchone()

        if not row:
            return {"error": f"Session not found: {session_id}"}

        file_info = dict(row)

        # Get label info if available
        labels = conn.execute(
            "SELECT * FROM labels WHERE file_id = ?",
            (file_info['id'],)
        ).fetchall()

    label_info = None
    if labels:
        label_info = [
            {
                "rating": l['rating'],
                "turn_start": l['turn_start'],
                "turn_end": l['turn_end'],
                "tags": l['tags'],
                "notes": l['notes']
            }
            for l in labels
        ]

    return {
        "session_id": file_info['session_id'],
        "filename": file_info['filename'],
        "date": file_info['date'],
        "status": file_info['status'],
        "is_agent": bool(file_info['is_agent']),
        "turn_counts": {
            "user": file_info['user_turns'],
            "claude": file_info['claude_turns'],
            "substantive_user": file_info['substantive_user_turns']
        },
        "word_counts": {
            "user": file_info['user_word_count'],
            "claude": file_info['claude_word_count']
        },
        "dialogue_density": file_info['dialogue_density'],
        "has_reflective_language": bool(file_info['has_reflective_language']),
        "has_command_expansion": bool(file_info['has_command_expansion']),
        "labels": label_info,
        "imported_at": file_info['imported_at']
    }


@mcp.tool()
def stats() -> dict:
    """
    Get corpus-level statistics.

    Returns:
        Overall corpus stats including file counts, word counts, and labeling progress
    """
    with get_connection(DB_PATH) as conn:
        result = {}

        # File counts
        result['total_files'] = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        result['labeled_files'] = conn.execute(
            "SELECT COUNT(DISTINCT file_id) FROM labels"
        ).fetchone()[0]

        # Status breakdown
        status_rows = conn.execute(
            "SELECT status, COUNT(*) FROM files GROUP BY status"
        ).fetchall()
        result['by_status'] = {row[0]: row[1] for row in status_rows}

        # Rating distribution (if labels exist)
        rating_rows = conn.execute(
            "SELECT rating, COUNT(*) FROM labels GROUP BY rating"
        ).fetchall()
        result['by_rating'] = {row[0]: row[1] for row in rating_rows}

        # Word counts
        row = conn.execute("""
            SELECT SUM(user_word_count), SUM(claude_word_count)
            FROM files WHERE status = 'active'
        """).fetchone()
        result['total_user_words'] = row[0] or 0
        result['total_claude_words'] = row[1] or 0

        # Date range
        date_row = conn.execute(
            "SELECT MIN(date), MAX(date) FROM files WHERE status = 'active'"
        ).fetchone()
        result['date_range'] = {
            "earliest": date_row[0],
            "latest": date_row[1]
        }

        return result


if __name__ == "__main__":
    mcp.run()
