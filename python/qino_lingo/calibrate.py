"""
Calibration rounds — themed human labeling for ground truth.

Presents conversations through epistemic lenses for labeling,
building calibration data to correct AI rating inflation.

Usage:
    python -m python.qino_lingo.calibrate themes
    python -m python.qino_lingo.calibrate round --theme broad_seeding
    python -m python.qino_lingo.calibrate present --round 1
    python -m python.qino_lingo.calibrate present --round 1 --item 3
    python -m python.qino_lingo.calibrate label --round 1 --item 1 --rating 3 --tags "philosophical"
    python -m python.qino_lingo.calibrate interpret --round 1
    python -m python.qino_lingo.calibrate status
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown

from .db import get_connection, add_label, DEFAULT_DB_PATH
from .parser import parse_conversation, Conversation

console = Console()

CORPUS_DIR = Path(__file__).parent.parent.parent / "data" / "corpus"


# --- Schema ---

def ensure_tables(db_path: Path = DEFAULT_DB_PATH):
    """No-op retained for backwards compatibility.

    After Chunk 1 the canonical schema for calibration_rounds and
    calibration_items lives in python/qino_lingo/migrations/. The
    rebuild migration switched calibration_items.file_id to
    calibration_items.filename. Callers retained for compatibility.
    """
    return None


# --- Theme Registry ---

@dataclass
class ThemePool:
    """A sub-query pool for composite themes like broad_seeding."""
    where_clause: str
    order_by: str
    limit: int


@dataclass
class Theme:
    """A sampling theme for calibration rounds."""
    key: str
    name: str
    description: str
    where_clause: str = ""
    order_by: str = "RANDOM()"
    sample_size: int = 6
    pools: Optional[List[ThemePool]] = None

    @property
    def is_composite(self) -> bool:
        return self.pools is not None


THEMES: Dict[str, Theme] = {}


def _register(*themes: Theme):
    for t in themes:
        THEMES[t.key] = t


_register(
    Theme(
        key="broad_seeding",
        name="Broad seeding",
        description="Diverse initial sample: reflective+engaged, non-reflective+engaged, and short",
        pools=[
            ThemePool(
                where_clause="f.has_reflective_language = 1 AND f.substantive_user_turns >= 5",
                order_by="f.substantive_user_turns DESC",
                limit=2,
            ),
            ThemePool(
                where_clause="f.has_reflective_language = 0 AND f.substantive_user_turns >= 5",
                order_by="f.dialogue_density DESC",
                limit=2,
            ),
            ThemePool(
                where_clause="f.substantive_user_turns BETWEEN 1 AND 3 AND f.user_word_count BETWEEN 20 AND 300",
                order_by="RANDOM()",
                limit=2,
            ),
        ],
    ),
    Theme(
        key="the_short_ones",
        name="The short ones",
        description="1-3 substantive turns, 20-300 user words — can brevity be rich?",
        where_clause="f.substantive_user_turns BETWEEN 1 AND 3 AND f.user_word_count BETWEEN 20 AND 300",
        order_by="RANDOM()",
    ),
    Theme(
        key="hidden_richness",
        name="Quiet surface, hidden depth?",
        description="No reflective markers, 3-8 substantive turns — richness without obvious signals",
        where_clause="f.has_reflective_language = 0 AND f.substantive_user_turns BETWEEN 3 AND 8",
        order_by="RANDOM()",
    ),
    Theme(
        key="dense_exchanges",
        name="Dense back-and-forth",
        description="High dialogue density, 5+ substantive turns — concentrated exchange",
        where_clause="f.dialogue_density > 150 AND f.substantive_user_turns >= 5",
        order_by="f.dialogue_density DESC",
    ),
    Theme(
        key="the_epics",
        name="The epics",
        description="2000+ user words, 10+ substantive turns — the long ones",
        where_clause="f.user_word_count >= 2000 AND f.substantive_user_turns >= 10",
        order_by="f.user_word_count DESC",
    ),
    Theme(
        key="reflective_surface",
        name="Reflective language = rich?",
        description="Has reflective language, 3+ substantive turns — does surface reflection predict depth?",
        where_clause="f.has_reflective_language = 1 AND f.substantive_user_turns >= 3",
        order_by="RANDOM()",
    ),
    Theme(
        key="early_corpus",
        name="The early days",
        description="December 2025 conversations — how did it start?",
        where_clause="f.date LIKE '2025-12%'",
        order_by="RANDOM()",
    ),
    Theme(
        key="recent_corpus",
        name="The recent ones",
        description="February 2026 conversations — where are we now?",
        where_clause="f.date LIKE '2026-02%'",
        order_by="RANDOM()",
    ),
    Theme(
        key="random_baseline",
        name="Random baseline",
        description="Unbiased random sample — the control group",
        where_clause="f.substantive_user_turns >= 1",
        order_by="RANDOM()",
    ),
)


# --- Sampling ---

BASE_WHERE = (
    "ci.id IS NULL AND l.id IS NULL "
    "AND f.is_agent = 0 AND f.status = 'active'"
)

BASE_QUERY = """
    SELECT f.* FROM files f
    LEFT JOIN calibration_items ci ON f.filename = ci.filename
    LEFT JOIN labels l ON f.filename = l.filename
    WHERE {base_where}
      AND {where_clause}
    ORDER BY {order_by}
    LIMIT ?
"""


def sample_for_theme(
    theme: Theme,
    db_path: Path = DEFAULT_DB_PATH,
) -> Tuple[List[Dict], str]:
    """Sample conversations for a theme. Returns (rows, query_used)."""
    if theme.is_composite:
        return _sample_composite(theme, db_path)

    query = BASE_QUERY.format(
        base_where=BASE_WHERE,
        where_clause=theme.where_clause,
        order_by=theme.order_by,
    )
    with get_connection(db_path) as conn:
        rows = conn.execute(query, (theme.sample_size,)).fetchall()
        return [dict(r) for r in rows], query


def _sample_composite(
    theme: Theme,
    db_path: Path,
) -> Tuple[List[Dict], str]:
    """Sample from multiple pools and combine."""
    all_rows = []
    seen_ids: set = set()
    queries = []

    with get_connection(db_path) as conn:
        for pool in theme.pools:
            query = BASE_QUERY.format(
                base_where=BASE_WHERE,
                where_clause=pool.where_clause,
                order_by=pool.order_by,
            )
            queries.append(query.strip())
            rows = conn.execute(query, (pool.limit,)).fetchall()
            for r in rows:
                row = dict(r)
                if row['filename'] not in seen_ids:
                    all_rows.append(row)
                    seen_ids.add(row['filename'])

    return all_rows, "\n---\n".join(queries)


def count_eligible(theme: Theme, db_path: Path = DEFAULT_DB_PATH) -> int:
    """Count eligible conversations for a theme."""
    count_template = """
        SELECT COUNT(*) FROM files f
        LEFT JOIN calibration_items ci ON f.filename = ci.filename
        LEFT JOIN labels l ON f.filename = l.filename
        WHERE {base_where}
          AND {where_clause}
    """

    if theme.is_composite:
        total = 0
        with get_connection(db_path) as conn:
            for pool in theme.pools:
                query = count_template.format(
                    base_where=BASE_WHERE,
                    where_clause=pool.where_clause,
                )
                total += conn.execute(query).fetchone()[0]
        return total

    query = count_template.format(
        base_where=BASE_WHERE,
        where_clause=theme.where_clause,
    )
    with get_connection(db_path) as conn:
        return conn.execute(query).fetchone()[0]


# --- Excerpt extraction ---

def extract_excerpt(
    conv: Conversation,
    max_turns: int = 10,
    max_words_per_turn: int = 150,
) -> str:
    """Extract a condensed excerpt from a conversation.

    Strategy:
    - Filter to substantive turn pairs (user + assistant)
    - If <= max_turns: include all
    - If > max_turns: bookend + middle peak approach
      - First 3 exchanges (opening)
      - Last 3 exchanges (resolution)
      - 4 densest exchanges from the middle (peak engagement)
    - Truncate individual turns to max_words_per_turn
    """
    pairs = conv.turn_pairs
    substantive_pairs = [p for p in pairs if p.user_turn.has_substantive_content]

    if not substantive_pairs:
        substantive_pairs = pairs[:max_turns]

    if len(substantive_pairs) <= max_turns:
        selected = substantive_pairs
    else:
        first_n = 3
        last_n = 3
        middle_n = max_turns - first_n - last_n

        first = substantive_pairs[:first_n]
        last = substantive_pairs[-last_n:]
        middle_candidates = substantive_pairs[first_n:-last_n]

        # Pick densest/longest from the middle
        middle_candidates.sort(
            key=lambda p: p.user_turn.word_count + (
                p.assistant_turn.word_count if p.assistant_turn else 0
            ),
            reverse=True,
        )
        middle = sorted(
            middle_candidates[:middle_n],
            key=lambda p: p.user_turn.index,
        )

        selected = first + middle + last

    lines = []
    prev_index = -1

    for pair in selected:
        # Mark omissions
        if prev_index >= 0 and pair.user_turn.index > prev_index + 2:
            gap = (pair.user_turn.index - prev_index) // 2
            lines.append(f"\n[--- {gap} exchanges omitted ---]\n")

        # User turn
        user_text = _truncate_words(pair.user_turn.content, max_words_per_turn)
        lines.append(f"USER: {user_text}")

        # Assistant turn
        if pair.assistant_turn:
            asst_text = _truncate_words(
                pair.assistant_turn.content, max_words_per_turn,
            )
            lines.append(f"CLAUDE: {asst_text}")

        lines.append("")

        prev_index = pair.user_turn.index + (1 if pair.assistant_turn else 0)

    return "\n".join(lines).strip()


def _truncate_words(text: str, max_words: int) -> str:
    """Truncate text to max_words, appending [...]."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + " [...]"


# --- Round operations ---

def create_round(
    theme_key: str,
    db_path: Path = DEFAULT_DB_PATH,
    corpus_dir: Path = CORPUS_DIR,
) -> int:
    """Create a new calibration round: sample, parse, excerpt, store."""
    ensure_tables(db_path)

    if theme_key not in THEMES:
        console.print(f"[red]Unknown theme: {theme_key}[/red]")
        console.print(f"Available: {', '.join(THEMES.keys())}")
        sys.exit(1)

    theme = THEMES[theme_key]
    rows, query_used = sample_for_theme(theme, db_path)

    if not rows:
        console.print(
            f"[yellow]No eligible conversations for theme "
            f"'{theme.name}'[/yellow]"
        )
        sys.exit(1)

    with get_connection(db_path) as conn:
        cursor = conn.execute("""
            INSERT INTO calibration_rounds
                (theme_key, theme_name, theme_description, sample_query, status)
            VALUES (?, ?, ?, ?, 'labeling')
        """, (theme.key, theme.name, theme.description, query_used))
        round_id = cursor.lastrowid

        for position, file_row in enumerate(rows, 1):
            filepath = corpus_dir / file_row['filename']
            excerpt = ""

            if filepath.exists():
                try:
                    conv = parse_conversation(filepath)
                    excerpt = extract_excerpt(conv)
                except Exception as e:
                    excerpt = f"[parse error: {e}]"
            else:
                excerpt = "[file not found]"

            conn.execute("""
                INSERT INTO calibration_items
                    (round_id, filename, position, excerpt)
                VALUES (?, ?, ?, ?)
            """, (round_id, file_row['filename'], position, excerpt))

    console.print(f"\n[green]Created round #{round_id}[/green]: {theme.name}")
    console.print(f"  {len(rows)} conversations sampled\n")

    present_round(round_id, db_path=db_path)

    return round_id


# --- Presentation ---

def present_round(
    round_id: int,
    item_position: Optional[int] = None,
    db_path: Path = DEFAULT_DB_PATH,
):
    """Display round items in the terminal."""
    ensure_tables(db_path)

    with get_connection(db_path) as conn:
        round_row = conn.execute(
            "SELECT * FROM calibration_rounds WHERE id = ?", (round_id,)
        ).fetchone()

        if not round_row:
            console.print(f"[red]Round #{round_id} not found[/red]")
            return

        round_row = dict(round_row)

        if item_position is not None:
            items = conn.execute("""
                SELECT ci.*, f.filename, f.substantive_user_turns,
                       f.user_word_count, f.has_reflective_language,
                       f.dialogue_density, f.date,
                       l.rating as label_rating
                FROM calibration_items ci
                JOIN files f ON ci.filename = f.filename
                LEFT JOIN labels l ON ci.label_id = l.id
                WHERE ci.round_id = ? AND ci.position = ?
            """, (round_id, item_position)).fetchall()
        else:
            items = conn.execute("""
                SELECT ci.*, f.filename, f.substantive_user_turns,
                       f.user_word_count, f.has_reflective_language,
                       f.dialogue_density, f.date,
                       l.rating as label_rating
                FROM calibration_items ci
                JOIN files f ON ci.filename = f.filename
                LEFT JOIN labels l ON ci.label_id = l.id
                WHERE ci.round_id = ?
                ORDER BY ci.position
            """, (round_id,)).fetchall()

    items = [dict(i) for i in items]

    # Round header
    console.print(Panel(
        f"[bold]{round_row['theme_name']}[/bold]\n"
        f"{round_row['theme_description'] or ''}",
        title=f"Round #{round_id}",
        subtitle=f"Status: {round_row['status']}",
    ))

    rating_names = {1: "thin", 2: "functional", 3: "rich"}

    for item in items:
        labeled = "[green]#[/green]" if item['label_id'] else "[dim]o[/dim]"
        label_info = ""

        if item['label_rating'] is not None:
            r = item['label_rating']
            label_info = f" -> {r} ({rating_names.get(r, '?')})"

        header = (
            f"{labeled} Item {item['position']}  |  "
            f"{item['filename']}  |  "
            f"turns={item['substantive_user_turns']}  "
            f"words={item['user_word_count']}  "
            f"reflective={'yes' if item['has_reflective_language'] else 'no'}  "
            f"density={item['dialogue_density']:.0f}"
            f"{label_info}"
        )

        if item_position is not None:
            # Full excerpt for single item
            console.print(Panel(
                item['excerpt'] or "[no excerpt]",
                title=header,
                border_style="dim",
            ))
        else:
            # Compact view for all items
            excerpt_preview = (item['excerpt'] or "")[:200]
            if len(item['excerpt'] or "") > 200:
                excerpt_preview += "..."
            console.print(f"\n  {header}")
            console.print(f"    [dim]{excerpt_preview}[/dim]")

    labeled_count = sum(1 for i in items if i['label_id'])
    total = len(items)
    console.print(f"\n  Labeled: {labeled_count}/{total}")


# --- Labeling ---

def label_conversation(
    round_id: int,
    item_position: int,
    rating: int,
    tags: Optional[str] = None,
    notes: str = "",
    db_path: Path = DEFAULT_DB_PATH,
):
    """Label a conversation item. Stores in both labels and calibration_items."""
    ensure_tables(db_path)

    with get_connection(db_path) as conn:
        item = conn.execute("""
            SELECT ci.*, cr.theme_key
            FROM calibration_items ci
            JOIN calibration_rounds cr ON ci.round_id = cr.id
            WHERE ci.round_id = ? AND ci.position = ?
        """, (round_id, item_position)).fetchone()

        if not item:
            console.print(
                f"[red]Item {item_position} not found in "
                f"round #{round_id}[/red]"
            )
            return

        item = dict(item)

    # Build tags list
    tag_list = []
    if tags:
        tag_list.extend(t.strip() for t in tags.split(","))
    tag_list.append(f"round:{round_id}")
    tag_list.append(item['theme_key'])

    # Add label via db.add_label (idempotent)
    label_id = add_label(
        filename=item['filename'],
        rating=rating,
        tags=tag_list,
        notes=notes,
        db_path=db_path,
    )

    # Link back to calibration_items
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE calibration_items SET label_id = ? WHERE id = ?",
            (label_id, item['id']),
        )

        # Check if all items in round are labeled
        unlabeled = conn.execute("""
            SELECT COUNT(*) FROM calibration_items
            WHERE round_id = ? AND label_id IS NULL
        """, (round_id,)).fetchone()[0]

        if unlabeled == 0:
            conn.execute("""
                UPDATE calibration_rounds
                SET status = 'complete', completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (round_id,))
            console.print(
                f"[green]Round #{round_id} complete![/green] "
                f"All items labeled."
            )
        else:
            console.print(f"  {unlabeled} items remaining in round #{round_id}")

    rating_names = {1: "thin", 2: "functional", 3: "rich"}
    console.print(
        f"[green]Labeled item {item_position}[/green]: "
        f"rating={rating} ({rating_names.get(rating, '?')}), "
        f"tags={tag_list}"
    )


# --- Interpretation ---

def interpret_round(round_id: int, db_path: Path = DEFAULT_DB_PATH):
    """Analyze a completed round and suggest next theme."""
    ensure_tables(db_path)

    with get_connection(db_path) as conn:
        round_row = conn.execute(
            "SELECT * FROM calibration_rounds WHERE id = ?", (round_id,)
        ).fetchone()

        if not round_row:
            console.print(f"[red]Round #{round_id} not found[/red]")
            return

        round_row = dict(round_row)

        # Items with file metadata and label info
        items = conn.execute("""
            SELECT ci.*, f.substantive_user_turns, f.user_word_count,
                   f.has_reflective_language, f.dialogue_density,
                   l.rating, l.tags
            FROM calibration_items ci
            JOIN files f ON ci.filename = f.filename
            LEFT JOIN labels l ON ci.label_id = l.id
            WHERE ci.round_id = ?
            ORDER BY ci.position
        """, (round_id,)).fetchall()
        items = [dict(i) for i in items]

        unlabeled = [i for i in items if i['rating'] is None]
        if unlabeled:
            console.print(
                f"[yellow]Warning: {len(unlabeled)} items unlabeled. "
                f"Interpretation works best on complete rounds.[/yellow]"
            )

        labeled_items = [i for i in items if i['rating'] is not None]
        if not labeled_items:
            console.print("[red]No labeled items to interpret.[/red]")
            return

        # 1. Rating distribution
        ratings = [i['rating'] for i in labeled_items]
        dist = {1: ratings.count(1), 2: ratings.count(2), 3: ratings.count(3)}

        # 2. Metric averages by rating
        def _avg_by_rating(
            label: str,
            values: List[Tuple[float, int]],
        ) -> str:
            if not values:
                return f"  {label}: no data"
            by_rating: Dict[int, List[float]] = {1: [], 2: [], 3: []}
            for val, r in values:
                by_rating[r].append(val)
            parts = []
            for r in [1, 2, 3]:
                if by_rating[r]:
                    avg = sum(by_rating[r]) / len(by_rating[r])
                    parts.append(f"r{r}={avg:.0f}")
            return f"  {label}: {', '.join(parts)}"

        word_data = [
            (i['user_word_count'], i['rating']) for i in labeled_items
        ]
        turn_data = [
            (i['substantive_user_turns'], i['rating']) for i in labeled_items
        ]
        refl_data = [
            (i['has_reflective_language'], i['rating']) for i in labeled_items
        ]
        dens_data = [
            (i['dialogue_density'], i['rating']) for i in labeled_items
        ]

        # 3. Cross-round coverage
        all_rounds = conn.execute("""
            SELECT cr.id, cr.theme_key, cr.theme_name, cr.status,
                   COUNT(ci.id) as item_count,
                   COUNT(ci.label_id) as labeled_count
            FROM calibration_rounds cr
            LEFT JOIN calibration_items ci ON cr.id = ci.round_id
            GROUP BY cr.id
            ORDER BY cr.id
        """).fetchall()
        all_rounds = [dict(r) for r in all_rounds]

        all_labeled = conn.execute("""
            SELECT cr.theme_key, l.rating
            FROM calibration_items ci
            JOIN calibration_rounds cr ON ci.round_id = cr.id
            JOIN labels l ON ci.label_id = l.id
        """).fetchall()
        all_labeled = [dict(r) for r in all_labeled]

        covered_themes = {r['theme_key'] for r in all_rounds}
        uncovered_themes = [k for k in THEMES if k not in covered_themes]

    # 4. Next theme suggestion
    suggested = None
    if uncovered_themes:
        suggested = uncovered_themes[0]
    else:
        # Look for themes with uniform results (might benefit from re-sampling)
        theme_ratings: Dict[str, List[int]] = {}
        for row in all_labeled:
            theme_ratings.setdefault(row['theme_key'], []).append(row['rating'])
        for key, ratings_list in theme_ratings.items():
            if len(set(ratings_list)) == 1 and len(ratings_list) >= 3:
                suggested = key
                break

    # Build markdown interpretation
    md_lines = [
        f"# Round #{round_id}: {round_row['theme_name']}",
        "",
        f"**Theme**: {round_row['theme_description']}",
        f"**Items**: {len(labeled_items)} labeled / {len(items)} total",
        "",
        "## Rating Distribution",
        "",
        f"- Thin (1): {dist[1]}",
        f"- Functional (2): {dist[2]}",
        f"- Rich (3): {dist[3]}",
        "",
        "## Metric Averages by Rating",
        "",
        _avg_by_rating("Word count", word_data),
        _avg_by_rating("Substantive turns", turn_data),
        _avg_by_rating("Reflective flag", refl_data),
        _avg_by_rating("Dialogue density", dens_data),
        "",
        "## Coverage",
        "",
        f"- Themes used: {len(covered_themes)}/{len(THEMES)}",
        f"- Uncovered: {', '.join(uncovered_themes) if uncovered_themes else 'none'}",
        f"- Total labeled across all rounds: {len(all_labeled)}",
        "",
    ]

    if suggested:
        theme = THEMES[suggested]
        md_lines.extend([
            "## Suggested Next Theme",
            "",
            f"**{suggested}**: {theme.name}",
            f"  {theme.description}",
        ])

    interpretation = "\n".join(md_lines)

    # Store interpretation
    with get_connection(db_path) as conn:
        conn.execute("""
            UPDATE calibration_rounds
            SET interpretation = ?, next_theme_suggestion = ?
            WHERE id = ?
        """, (interpretation, suggested, round_id))

    console.print(Markdown(interpretation))
    return interpretation


# --- Status & Themes ---

def show_status(db_path: Path = DEFAULT_DB_PATH):
    """Show overview of all calibration rounds."""
    ensure_tables(db_path)

    with get_connection(db_path) as conn:
        rounds = conn.execute("""
            SELECT cr.*,
                   COUNT(ci.id) as item_count,
                   COUNT(ci.label_id) as labeled_count
            FROM calibration_rounds cr
            LEFT JOIN calibration_items ci ON cr.id = ci.round_id
            GROUP BY cr.id
            ORDER BY cr.id
        """).fetchall()

    if not rounds:
        console.print("[dim]No calibration rounds yet.[/dim]")
        console.print("Create one with: calibrate round --theme broad_seeding")
        return

    table = Table(title="Calibration Rounds")
    table.add_column("#", style="bold")
    table.add_column("Theme")
    table.add_column("Status")
    table.add_column("Progress")
    table.add_column("Created")

    for r in rounds:
        r = dict(r)
        status_style = {
            'open': 'dim',
            'labeling': 'yellow',
            'complete': 'green',
        }.get(r['status'], 'white')

        table.add_row(
            str(r['id']),
            r['theme_name'],
            f"[{status_style}]{r['status']}[/{status_style}]",
            f"{r['labeled_count']}/{r['item_count']}",
            r['created_at'][:10] if r['created_at'] else "",
        )

    console.print(table)

    with get_connection(db_path) as conn:
        total = conn.execute("""
            SELECT COUNT(*) FROM calibration_items WHERE label_id IS NOT NULL
        """).fetchone()[0]

    console.print(f"\n  Total calibration labels: {total}")


def list_themes(db_path: Path = DEFAULT_DB_PATH):
    """List available themes with eligible conversation counts."""
    ensure_tables(db_path)

    table = Table(title="Calibration Themes")
    table.add_column("Key", style="bold")
    table.add_column("Name")
    table.add_column("Description")
    table.add_column("Eligible", justify="right")

    for theme in THEMES.values():
        eligible = count_eligible(theme, db_path)
        table.add_row(
            theme.key,
            theme.name,
            theme.description or "",
            str(eligible),
        )

    console.print(table)


# --- CLI ---

def main():
    parser = argparse.ArgumentParser(
        description="Calibration rounds — themed human labeling for ground truth",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # themes
    themes_p = subparsers.add_parser("themes", help="List themes with eligible counts")
    themes_p.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)

    # round
    round_p = subparsers.add_parser("round", help="Create a new calibration round")
    round_p.add_argument("--theme", "-t", required=True, help="Theme key")
    round_p.add_argument("--corpus-dir", type=Path, default=CORPUS_DIR)
    round_p.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)

    # present
    present_p = subparsers.add_parser("present", help="Show round items")
    present_p.add_argument(
        "--round", "-r", type=int, required=True, dest="round_id",
    )
    present_p.add_argument("--item", "-i", type=int, help="Show specific item")
    present_p.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)

    # label
    label_p = subparsers.add_parser("label", help="Label a conversation")
    label_p.add_argument(
        "--round", "-r", type=int, required=True, dest="round_id",
    )
    label_p.add_argument(
        "--item", "-i", type=int, required=True, dest="item_position",
    )
    label_p.add_argument(
        "--rating", type=int, required=True, choices=[1, 2, 3],
    )
    label_p.add_argument("--tags", help="Comma-separated tags")
    label_p.add_argument("--notes", default="")
    label_p.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)

    # interpret
    interp_p = subparsers.add_parser("interpret", help="Analyze round results")
    interp_p.add_argument(
        "--round", "-r", type=int, required=True, dest="round_id",
    )
    interp_p.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)

    # status
    status_p = subparsers.add_parser("status", help="Show all rounds overview")
    status_p.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)

    args = parser.parse_args()

    if args.command == "themes":
        list_themes(db_path=args.db)
    elif args.command == "round":
        create_round(
            args.theme, db_path=args.db, corpus_dir=args.corpus_dir,
        )
    elif args.command == "present":
        present_round(
            args.round_id, item_position=args.item, db_path=args.db,
        )
    elif args.command == "label":
        label_conversation(
            args.round_id, args.item_position, args.rating,
            tags=args.tags, notes=args.notes, db_path=args.db,
        )
    elif args.command == "interpret":
        interpret_round(args.round_id, db_path=args.db)
    elif args.command == "status":
        show_status(db_path=args.db)


if __name__ == "__main__":
    main()
