"""
Stratified sampling for conversation labeling.
"""

import random
from typing import List, Dict, Optional
from pathlib import Path

from .db import get_connection, DEFAULT_DB_PATH


def sample_random(
    n: int = 5,
    exclude_labeled: bool = True,
    db_path: Path = DEFAULT_DB_PATH
) -> List[Dict]:
    """Sample n random files."""
    with get_connection(db_path) as conn:
        if exclude_labeled:
            query = """
                SELECT f.* FROM files f
                LEFT JOIN labels l ON f.id = l.file_id
                WHERE l.id IS NULL
                ORDER BY RANDOM()
                LIMIT ?
            """
        else:
            query = "SELECT * FROM files ORDER BY RANDOM() LIMIT ?"

        rows = conn.execute(query, (n,)).fetchall()
        return [dict(r) for r in rows]


def sample_stratified(
    n_per_stratum: int = 2,
    exclude_labeled: bool = True,
    db_path: Path = DEFAULT_DB_PATH
) -> Dict[str, List[Dict]]:
    """
    Sample from different strata to ensure diversity.

    Strata:
    - high_engagement: 10+ substantive turns
    - medium_engagement: 3-9 substantive turns
    - low_engagement: 1-2 substantive turns
    - reflective: has reflective language markers
    - dense: high dialogue density (words per turn)
    """
    samples = {}

    with get_connection(db_path) as conn:
        base_query = """
            SELECT f.* FROM files f
            LEFT JOIN labels l ON f.id = l.file_id
            WHERE l.id IS NULL AND {condition}
            ORDER BY RANDOM()
            LIMIT ?
        """ if exclude_labeled else """
            SELECT * FROM files WHERE {condition}
            ORDER BY RANDOM()
            LIMIT ?
        """

        strata = {
            'high_engagement': 'substantive_user_turns >= 10',
            'medium_engagement': 'substantive_user_turns BETWEEN 3 AND 9',
            'low_engagement': 'substantive_user_turns BETWEEN 1 AND 2',
            'reflective': 'has_reflective_language = 1',
            'high_density': 'dialogue_density > 100',
            'agent_sessions': 'is_agent = 1 AND substantive_user_turns > 0',
        }

        for name, condition in strata.items():
            query = base_query.format(condition=condition)
            rows = conn.execute(query, (n_per_stratum,)).fetchall()
            samples[name] = [dict(r) for r in rows]

    return samples


def sample_by_date(
    date: str,
    n: int = 5,
    db_path: Path = DEFAULT_DB_PATH
) -> List[Dict]:
    """Sample files from a specific date."""
    with get_connection(db_path) as conn:
        rows = conn.execute("""
            SELECT * FROM files
            WHERE date = ?
            ORDER BY RANDOM()
            LIMIT ?
        """, (date, n)).fetchall()
        return [dict(r) for r in rows]


def sample_top_candidates(
    n: int = 10,
    exclude_labeled: bool = True,
    db_path: Path = DEFAULT_DB_PATH
) -> List[Dict]:
    """
    Sample top candidates based on multiple signals:
    - Has reflective language
    - High substantive turns
    - High user word count
    """
    with get_connection(db_path) as conn:
        if exclude_labeled:
            query = """
                SELECT f.* FROM files f
                LEFT JOIN labels l ON f.id = l.file_id
                WHERE l.id IS NULL
                ORDER BY
                    (CASE WHEN has_reflective_language THEN 1 ELSE 0 END) DESC,
                    substantive_user_turns DESC,
                    user_word_count DESC
                LIMIT ?
            """
        else:
            query = """
                SELECT * FROM files
                ORDER BY
                    (CASE WHEN has_reflective_language THEN 1 ELSE 0 END) DESC,
                    substantive_user_turns DESC,
                    user_word_count DESC
                LIMIT ?
            """

        rows = conn.execute(query, (n,)).fetchall()
        return [dict(r) for r in rows]


def get_labeling_progress(db_path: Path = DEFAULT_DB_PATH) -> Dict:
    """Get labeling progress statistics."""
    with get_connection(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        labeled = conn.execute("SELECT COUNT(DISTINCT file_id) FROM labels").fetchone()[0]
        rich = conn.execute(
            "SELECT COUNT(DISTINCT file_id) FROM labels WHERE is_rich = 1"
        ).fetchone()[0]
        not_rich = conn.execute(
            "SELECT COUNT(DISTINCT file_id) FROM labels WHERE is_rich = 0"
        ).fetchone()[0]

        return {
            'total': total,
            'labeled': labeled,
            'unlabeled': total - labeled,
            'rich': rich,
            'not_rich': not_rich,
            'progress_pct': round(100 * labeled / total, 1) if total > 0 else 0
        }
