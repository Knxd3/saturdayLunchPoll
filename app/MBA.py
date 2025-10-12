import sqlite3
from datetime import datetime, timedelta
from .db import get_db_connection


def _iso_now_seconds() -> str:
    return datetime.now().isoformat(timespec="seconds")


def update_mab_stats(window_weeks: int = 8) -> list[dict]:
    """Compute per-restaurant Beta prior parameters over a rolling window.

    Strategy (weighted by turnout):
    - Consider the last `window_weeks` weeks using weekly_results.created_at.
    - For each week, use final vote counts per restaurant (weekly_results.votes).
    - Alpha = 1 + sum(votes_for) over weeks the restaurant appeared.
    - Beta  = 1 + sum(total_votes_in_week - votes_for) over those weeks.
      This penalizes failures in high-turnout weeks more than low-turnout weeks.
    - Restaurants with no history get Alpha=1, Beta=1 (uninformative prior).

    Also computes appearances and wins (ties count as wins) for reference.
    Stores in `mab_stats` and returns a list with name, alpha, beta, appearances, wins.
    """
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Helper table for visibility/debugging
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS mab_stats (
            name TEXT PRIMARY KEY,
            alpha REAL NOT NULL,
            beta REAL NOT NULL,
            appearances INTEGER NOT NULL,
            wins INTEGER NOT NULL,
            window_start TEXT,
            window_end TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )

    # Rolling window bounds
    now = datetime.now()
    window_end = now
    window_start = window_end - timedelta(days=7 * max(1, int(window_weeks)))
    window_start_iso = window_start.isoformat(timespec="seconds")
    window_end_iso = window_end.isoformat(timespec="seconds")

    # Weighted stats from weekly_results
    stats_rows = cur.execute(
        """
        WITH recent AS (
            SELECT name, votes, created_at
            FROM weekly_results
            WHERE created_at >= ? AND COALESCE(is_excluded, 0) = 0
        ),
        totals_per_week AS (
            SELECT created_at, SUM(votes) AS total_votes
            FROM recent
            GROUP BY created_at
        ),
        per_name_week AS (
            SELECT r.name,
                   r.votes AS votes_for,
                   t.total_votes,
                   r.created_at
            FROM recent r
            JOIN totals_per_week t USING (created_at)
        ),
        max_per_week AS (
            SELECT created_at, MAX(votes) AS max_votes
            FROM recent
            GROUP BY created_at
        ),
        wins AS (
            SELECT r.name, COUNT(*) AS win_count
            FROM recent r
            JOIN max_per_week m
              ON r.created_at = m.created_at AND r.votes = m.max_votes
            GROUP BY r.name
        ),
        appear AS (
            SELECT name, COUNT(*) AS app_count
            FROM recent
            GROUP BY namepy -
        ),
        agg AS (
            SELECT name,
                   SUM(votes_for) AS votes_for_sum,
                   SUM(total_votes) AS total_votes_sum
            FROM per_name_week
            GROUP BY name
        )
        SELECT a.name,
               COALESCE(w.win_count, 0) AS wins,
               a.app_count AS appearances,
               COALESCE(g.votes_for_sum, 0) AS votes_for_sum,
               COALESCE(g.total_votes_sum, 0) AS total_votes_sum
        FROM appear a
        LEFT JOIN wins w ON w.name = a.name
        LEFT JOIN agg g ON g.name = a.name
        """,
        (window_start_iso,),
    ).fetchall()

    # Merge with the full restaurant set so newcomers are included
    all_names = {r["name"] for r in cur.execute("SELECT name FROM restaurants WHERE COALESCE(is_excluded,0)=0").fetchall()}
    hist_map = {}
    for r in stats_rows:
        hist_map[r["name"]] = {
            "wins": int(r["wins"]),
            "appearances": int(r["appearances"]),
            "votes_for_sum": int(r["votes_for_sum"]),
            "total_votes_sum": int(r["total_votes_sum"]),
        }

    payload = []
    for name in sorted(all_names):
        rec = hist_map.get(name)
        if rec:
            votes_for_sum = max(0, rec["votes_for_sum"])
            total_votes_sum = max(0, rec["total_votes_sum"])
            alpha = 1 + votes_for_sum
            beta = 1 + max(0, total_votes_sum - votes_for_sum)
            apps = rec["appearances"]
            wins = rec["wins"]
        else:
            alpha = 1.0
            beta = 1.0
            apps = 0
            wins = 0
        payload.append(
            {
                "name": name,
                "alpha": float(alpha),
                "beta": float(beta),
                "appearances": int(apps),
                "wins": int(wins),
            }
        )

    # Refresh helper table
    cur.execute("DELETE FROM mab_stats")
    for row in payload:
        cur.execute(
            (
                "INSERT INTO mab_stats (name, alpha, beta, appearances, wins, window_start, window_end, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            ),
            (
                row["name"],
                row["alpha"],
                row["beta"],
                row["appearances"],
                row["wins"],
                window_start_iso,
                window_end_iso,
                _iso_now_seconds(),
            ),
        )

    conn.commit()
    conn.close()
    return payload
