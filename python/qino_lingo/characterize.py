"""
AI characterization engine — epistemic analysis of conversations via LLM.

Samples conversations from corpus.db, sends them to an LLM for turn-level
epistemic analysis, and stores results in pending_labels for human review.

Usage:
    python -m python.qino_lingo.characterize --strategy signal --limit 5 --dry-run
    python -m python.qino_lingo.characterize --strategy signal --limit 20
    python -m python.qino_lingo.characterize --strategy calibration --min-rating 1
    python -m python.qino_lingo.characterize --model anthropic/claude-sonnet-4.5 --limit 5
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import List, Dict, Optional

from openrouter import OpenRouter

from .db import get_connection, DEFAULT_DB_PATH
from .parser import parse_conversation, Conversation, Turn


# --- Model tiers ---

DEFAULT_MODEL = "openai/gpt-4.1-mini"

CORPUS_DIR = Path(__file__).parent.parent.parent / "data" / "corpus"


# --- Sampling ---

STRATEGIES = {
    "signal": {
        "description": "Reflective language + high engagement — most likely rich",
        "query": """
            SELECT f.* FROM files f
            LEFT JOIN pending_labels pl ON f.filename = pl.filename AND pl.source = 'ai'
            LEFT JOIN labels l ON f.filename = l.filename
            WHERE pl.id IS NULL
              AND l.id IS NULL
              AND f.is_agent = 0
              AND f.has_reflective_language = 1
              AND f.substantive_user_turns >= 5
            ORDER BY f.substantive_user_turns DESC, f.user_word_count DESC
        """,
    },
    "edge": {
        "description": "Medium engagement, ambiguous quality — hard to classify",
        "query": """
            SELECT f.* FROM files f
            LEFT JOIN pending_labels pl ON f.filename = pl.filename AND pl.source = 'ai'
            LEFT JOIN labels l ON f.filename = l.filename
            WHERE pl.id IS NULL
              AND l.id IS NULL
              AND f.is_agent = 0
              AND f.substantive_user_turns BETWEEN 3 AND 8
              AND f.has_reflective_language = 0
              AND f.dialogue_density > 50
            ORDER BY RANDOM()
        """,
    },
    "calibration": {
        "description": "Clearly thin conversations — negative signal for calibration",
        "query": """
            SELECT f.* FROM files f
            LEFT JOIN pending_labels pl ON f.filename = pl.filename AND pl.source = 'ai'
            LEFT JOIN labels l ON f.filename = l.filename
            WHERE pl.id IS NULL
              AND l.id IS NULL
              AND f.is_agent = 0
              AND f.substantive_user_turns <= 2
              AND f.user_word_count < 200
            ORDER BY RANDOM()
        """,
    },
    "diversity": {
        "description": "Broad random coverage across the corpus",
        "query": """
            SELECT f.* FROM files f
            LEFT JOIN pending_labels pl ON f.filename = pl.filename AND pl.source = 'ai'
            LEFT JOIN labels l ON f.filename = l.filename
            WHERE pl.id IS NULL
              AND l.id IS NULL
              AND f.is_agent = 0
              AND f.substantive_user_turns >= 1
            ORDER BY RANDOM()
        """,
    },
}


def sample_conversations(
    strategy: str,
    limit: int,
    min_rating: Optional[int] = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> List[Dict]:
    """Sample conversations using a named strategy."""
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown strategy: {strategy}. Choose from: {list(STRATEGIES.keys())}")

    base_query = STRATEGIES[strategy]["query"]
    query = f"{base_query} LIMIT ?"
    params: list = [limit]

    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


# --- Windowing ---

MAX_WINDOWS = 5  # Cap windows for very long conversations


def window_turns(turns: List[Turn], window_size: int = 20, overlap: int = 4) -> List[List[Turn]]:
    """Split long conversations into overlapping windows.

    For conversations with many turns, caps at MAX_WINDOWS by sampling
    evenly through the conversation (start, middle, end coverage).
    """
    substantive = [t for t in turns if t.has_substantive_content or t.role == 'assistant']

    if len(substantive) <= window_size:
        return [substantive]

    # Generate all possible windows
    all_windows = []
    start = 0
    while start < len(substantive):
        end = min(start + window_size, len(substantive))
        all_windows.append(substantive[start:end])
        if end >= len(substantive):
            break
        start += window_size - overlap

    # If too many windows, sample evenly (start, middle sections, end)
    if len(all_windows) > MAX_WINDOWS:
        indices = [0]  # always include start
        step = (len(all_windows) - 1) / (MAX_WINDOWS - 1)
        for i in range(1, MAX_WINDOWS - 1):
            indices.append(round(i * step))
        indices.append(len(all_windows) - 1)  # always include end
        all_windows = [all_windows[i] for i in indices]

    return all_windows


# --- Prompt ---

SYSTEM_PROMPT = """\
You are an epistemic quality analyst. You evaluate conversations between a human and an AI assistant for epistemic depth — the quality of thinking, not just information exchange.

Your task: analyze the conversation and identify epistemic moves, then rate its overall quality.

## Epistemic Moves (look for these)

- **productive-uncertainty**: Genuine not-knowing that opens exploration (not just "I'm not sure")
- **reframing**: Shifting perspective on the problem/question itself
- **abductive-leap**: Making a creative inference that connects disparate ideas
- **meta-reflection**: Thinking about the thinking process itself
- **scaffold-building**: Constructing conceptual frameworks collaboratively
- **synthesis**: Combining multiple threads into coherent understanding
- **boundary-testing**: Probing the limits of a concept or approach

## Rating Scale

- **1 (thin)**: Transactional exchange. Commands, lookups, copy-paste requests. No epistemic engagement beyond task completion. Most conversations are thin — this is the default.
- **2 (functional)**: Some back-and-forth with light exploration, but stays within established frameworks. Competent dialogue without genuine discovery.
- **3 (rich)**: Genuine epistemic moves present. Real uncertainty explored, perspectives shifted, new understanding constructed. This is RARE — maybe 10-15% of conversations.

## Anti-Inflation Guardrail

Be SKEPTICAL of richness. Most conversations are thin (rating 1) or functional (rating 2).

Signs a conversation is NOT rich even if it seems complex:
- Long technical discussions that never question assumptions → functional at best
- The human asks good questions but accepts answers without probing → functional
- Sophisticated vocabulary without genuine uncertainty → functional
- The AI produces impressive-sounding analysis but the human doesn't engage with it → thin

A conversation is rich ONLY when both participants contribute to epistemic movement.

## Output Format

Respond with valid JSON only, no markdown formatting:
{
  "rating": 1|2|3,
  "confidence": 0.0-1.0,
  "reasoning": "2-3 sentences explaining your assessment",
  "epistemic_moves": ["move1", "move2"],
  "suggested_tags": ["tag1", "tag2"],
  "notable_turns": [{"turn": 0, "move": "reframing", "brief": "one line"}]
}

For suggested_tags, use relevant descriptors like: "technical", "philosophical", "creative", "debugging", "design", "meta-cognitive", "exploratory", "conceptual".\
"""


def format_conversation_for_analysis(turns: List[Turn], window_index: Optional[int] = None) -> str:
    """Format conversation turns into a readable transcript for the LLM."""
    lines = []

    if window_index is not None:
        lines.append(f"[Window {window_index + 1} of a longer conversation]\n")

    for turn in turns:
        role_label = "HUMAN" if turn.role == "user" else "ASSISTANT"
        content = turn.content

        # Truncate very long individual turns (e.g. code dumps) to keep focus
        if len(content) > 3000:
            content = content[:2800] + "\n[... truncated ...]"

        lines.append(f"[Turn {turn.index}] {role_label}:\n{content}\n")

    return "\n".join(lines)


# --- API ---

def analyze_conversation(
    turns: List[Turn],
    model: str,
    window_index: Optional[int] = None,
    dry_run: bool = False,
) -> Optional[Dict]:
    """Send conversation to LLM for epistemic analysis."""
    transcript = format_conversation_for_analysis(turns, window_index)

    if dry_run:
        word_count = len(transcript.split())
        print(f"  [dry-run] Would send ~{word_count} words to {model}")
        return None

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("Error: OPENROUTER_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)

    with OpenRouter(api_key=api_key) as client:
        response = client.chat.send(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Analyze this conversation:\n\n{transcript}"},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )

    content = response.choices[0].message.content
    if not content:
        print("  Warning: empty response from model")
        return None

    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        print(f"  Warning: failed to parse JSON response: {e}")
        print(f"  Raw response: {content[:500]}")
        return None


# --- Storage ---

def store_result(
    filename: str,
    result: Dict,
    model: str,
    strategy: str,
    turn_start: Optional[int] = None,
    turn_end: Optional[int] = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> int:
    """Store characterization result in pending_labels."""
    context = json.dumps({
        "suggested_rating": result.get("rating"),
        "reasoning": result.get("reasoning"),
        "epistemic_moves": result.get("epistemic_moves", []),
        "confidence": result.get("confidence"),
        "suggested_tags": result.get("suggested_tags", []),
        "notable_turns": result.get("notable_turns", []),
        "model": model,
        "strategy": strategy,
    })

    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO pending_labels (filename, turn_start, turn_end, source, context)
            VALUES (?, ?, ?, 'ai', ?)
            """,
            (filename, turn_start, turn_end, context),
        )
        return cursor.lastrowid


# --- Main ---

def run(
    strategy: str,
    limit: int,
    model: str = DEFAULT_MODEL,
    min_rating: Optional[int] = None,
    dry_run: bool = False,
    corpus_dir: Path = CORPUS_DIR,
    db_path: Path = DEFAULT_DB_PATH,
):
    """Run the characterization pipeline."""
    print(f"Strategy: {strategy} — {STRATEGIES[strategy]['description']}")
    print(f"Model: {model}")
    print(f"Limit: {limit}")
    if dry_run:
        print("Mode: DRY RUN (no API calls, no database writes)\n")
    print()

    # Sample conversations
    candidates = sample_conversations(strategy, limit, min_rating, db_path)
    print(f"Sampled {len(candidates)} conversations\n")

    if not candidates:
        print("No candidates found. All conversations may already be characterized.")
        return

    results_summary = {"total": len(candidates), "analyzed": 0, "errors": 0, "ratings": {}}

    for i, file_row in enumerate(candidates, 1):
        filename = file_row["filename"]
        filepath = corpus_dir / filename

        print(f"[{i}/{len(candidates)}] {filename}")
        print(f"  substantive_turns={file_row['substantive_user_turns']}  "
              f"words={file_row['user_word_count']}  "
              f"reflective={bool(file_row['has_reflective_language'])}")

        if not filepath.exists():
            print(f"  Skipping: file not found at {filepath}")
            results_summary["errors"] += 1
            continue

        # Parse conversation
        try:
            conv = parse_conversation(filepath)
        except Exception as e:
            print(f"  Skipping: parse error — {e}")
            results_summary["errors"] += 1
            continue

        substantive_turns = [t for t in conv.turns if t.has_substantive_content or t.role == 'assistant']

        if len(substantive_turns) < 2:
            print(f"  Skipping: too few substantive turns ({len(substantive_turns)})")
            results_summary["errors"] += 1
            continue

        # Window long conversations
        windows = window_turns(substantive_turns)

        for wi, window in enumerate(windows):
            window_label = f" (window {wi + 1}/{len(windows)})" if len(windows) > 1 else ""
            print(f"  Analyzing{window_label}: {len(window)} turns...")

            result = analyze_conversation(
                window,
                model=model,
                window_index=wi if len(windows) > 1 else None,
                dry_run=dry_run,
            )

            if result and not dry_run:
                rating = result.get("rating", "?")
                confidence = result.get("confidence", "?")
                moves = result.get("epistemic_moves", [])
                reasoning = result.get("reasoning", "")

                # Determine turn range for windowed conversations
                turn_start = window[0].index if len(windows) > 1 else None
                turn_end = window[-1].index if len(windows) > 1 else None

                label_id = store_result(
                    filename=filename,
                    result=result,
                    model=model,
                    strategy=strategy,
                    turn_start=turn_start,
                    turn_end=turn_end,
                    db_path=db_path,
                )

                print(f"  → rating={rating}  confidence={confidence}  moves={moves}")
                print(f"    {reasoning[:120]}")
                print(f"    stored as pending_label #{label_id}")

                # Track summary
                results_summary["analyzed"] += 1
                rating_key = str(rating)
                results_summary["ratings"][rating_key] = results_summary["ratings"].get(rating_key, 0) + 1

            elif dry_run:
                results_summary["analyzed"] += 1

            # Rate limiting between API calls
            if not dry_run and (i < len(candidates) or wi < len(windows) - 1):
                time.sleep(0.5)

        print()

    # Summary
    print("=" * 50)
    print("Summary:")
    print(f"  Candidates: {results_summary['total']}")
    print(f"  Analyzed:   {results_summary['analyzed']}")
    print(f"  Errors:     {results_summary['errors']}")
    if results_summary["ratings"]:
        print(f"  Ratings:    {results_summary['ratings']}")


def main():
    parser = argparse.ArgumentParser(
        description="AI characterization engine for conversation epistemic analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
strategies:
  signal        Reflective language + high engagement (most likely rich)
  edge          Medium engagement, ambiguous quality (hard cases)
  calibration   Clearly thin conversations (negative signal)
  diversity     Broad random coverage

examples:
  %(prog)s --strategy signal --limit 5 --dry-run
  %(prog)s --strategy signal --limit 20
  %(prog)s --strategy calibration --limit 10
  %(prog)s --model anthropic/claude-sonnet-4.5 --limit 5
        """,
    )
    parser.add_argument(
        "--strategy", "-s",
        choices=list(STRATEGIES.keys()),
        default="signal",
        help="Sampling strategy (default: signal)",
    )
    parser.add_argument(
        "--limit", "-n",
        type=int,
        default=10,
        help="Maximum conversations to process (default: 10)",
    )
    parser.add_argument(
        "--model", "-m",
        default=DEFAULT_MODEL,
        help=f"OpenRouter model ID (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--min-rating",
        type=int,
        choices=[1, 2, 3],
        help="Only include conversations with existing labels at or above this rating",
    )
    parser.add_argument(
        "--dry-run", "-d",
        action="store_true",
        help="Show what would be analyzed without making API calls",
    )
    parser.add_argument(
        "--corpus-dir",
        type=Path,
        default=CORPUS_DIR,
        help=f"Path to conversation files (default: {CORPUS_DIR})",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Path to corpus.db (default: {DEFAULT_DB_PATH})",
    )

    args = parser.parse_args()

    run(
        strategy=args.strategy,
        limit=args.limit,
        model=args.model,
        min_rating=args.min_rating,
        dry_run=args.dry_run,
        corpus_dir=args.corpus_dir,
        db_path=args.db,
    )


if __name__ == "__main__":
    main()
