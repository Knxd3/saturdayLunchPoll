import numpy as np
import pandas as pd
import sqlite3
from datetime import timedelta
from .db import get_db_connection
from .timeutil import now_london, iso_seconds_local, week_monday_london


def _iso_now_seconds() -> str:
    return iso_seconds_local(now_london())


def update_mab_stats(window_weeks: int = 200) -> list[dict]:
    """Compute per-restaurant Beta prior parameters with exponential time-decay.

    Strategy (weighted by turnout with decay):

    Use all rows from weekly_results where COALESCE(is_excluded, 0) = 0; 200 week pseudo hard cutoff implemented now.
    For each week/restaurant: successes = votes; trials = COUNT(DISTINCT(votes)) for that week.
    Anchor at the current London Monday; compute weeks_ago for each row.
    Apply decay weight w = gamma ** weeks_ago, with gamma = 0.5 ** (1 / half_life_weeks).
    Posterior parameters:
    alpha = alpha0 + sum (w * votes)
    beta = beta0 + sum (w * (trials - votes))
    This emphasizes high-turnout weeks and smoothly fades older evidence.
    Other outputs:

    Results are persisted to mab_stats and returned as a list of dicts. If computed,
    mean and a 95% credible interval (ci_lower, ci_upper) are included for convenience.
    Notes:

    Decay produces fractional effective counts; this is expected.
    Tune half_life_weeks (e.g., 13-26) to balance adaptivity vs. memory.
    """
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Helper table for visibility/debugging
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS mab_stats (
            name TEXT PRIMARY KEY,
            s INTEGER NOT NULL,
            n INTEGER NOT NULL,
            f INTEGER NOT NULL,
            alpha REAL NOT NULL,
            beta REAL NOT NULL,
            window_start TEXT,
            window_end TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )

    # Rolling window bounds
    window_end = now_london()
    window_start = window_end - timedelta(days=7 * max(1, int(window_weeks)))
    window_start_iso = iso_seconds_local(window_start)
    # print(window_start_iso)
    window_end_iso = iso_seconds_local(window_end)
    # 1) Materialize weekly rows (no cutoff)
    sql = """
    WITH weekly_trials AS (
      SELECT week_created_at, COUNT(DISTINCT email) AS trials
      FROM votes
      GROUP BY week_created_at
    )
    SELECT
      wr.created_at AS week_created_at,
      wr.name,
      wr.votes,
      wt.trials
    FROM weekly_results wr
    LEFT JOIN weekly_trials wt
      ON wr.created_at = wt.week_created_at
    WHERE COALESCE(wr.is_excluded, 0) = 0
    AND wr.created_at > :start
    """
    df = pd.read_sql(sql, 
                     conn,
                     params={"start": window_start_iso})

    # 2) Compute weeks_ago relative to the current London Monday
    asof_monday = week_monday_london(now_london())

    # Ensure tz-aware timestamps
    df['week_created_at'] = pd.to_datetime(df['week_created_at'], utc=True, errors='coerce')

    weeks_ago = np.floor((asof_monday - df['week_created_at']).dt.total_seconds() / (7*24*3600)).astype('Int64')
    weeks_ago = weeks_ago.clip(lower=0)  # guard negatives if any future stamps
    df['weeks_ago'] = weeks_ago.astype(int)

    # 3) Decay weights and decayed successes/trials
    H = 26  # half-life in weeks (tune 13–26)
    gamma = 0.5 ** (1.0 / H)
    w = np.power(gamma, df['weeks_ago'].to_numpy())

    # Fill any missing trials with the week’s total votes as a fallback
    df['trials'] = df['trials'].fillna(df.groupby('week_created_at')['votes'].transform('sum'))


    df['s_decayed'] = df['votes'].astype(float) * w
    df['n_decayed'] = df['trials'].astype(float) * w

    # 4) Aggregate per restaurant
    agg = df.groupby('name', as_index=False).agg(
        s=('s_decayed', 'sum'),
        n=('n_decayed', 'sum'),
    )
    agg['f'] = agg['n'] - agg['s']

    # 5) Posterior parameters
    from scipy.stats import beta 
    alpha0, beta0 = 1.0, 1.0  # or Jeffreys 0.5,0.5; or EB prior
    agg['alpha'] = alpha0 + agg['s']
    agg['beta']  = beta0  + (agg['n'] - agg['s'])

    # Optional: mean and 95% credible interval
    agg['mean']  = agg['alpha'] / (agg['alpha'] + agg['beta'])
    try:
        agg['lower'] = beta.ppf(0.025, agg['alpha'], agg['beta'])
        agg['upper'] = beta.ppf(0.975, agg['alpha'], agg['beta'])
    except Exception:
        pass  # if scipy is unavailable, skip or add a normal approximation

    

    all_names = {
        r["name"]
        for r in cur.execute(
            "SELECT name FROM restaurants WHERE COALESCE(is_excluded,0)=0"
        ).fetchall()
    }

    payload: list[dict] = []
    ab_map: dict[str, tuple[float, float]] = {}
    for _, row in agg.iterrows():  # type: ignore[attr-defined]
        name = str(row["name"])
        if name not in all_names:
            continue
        s = float(row.get("s", 0.0))
        n = float(row.get("n", 0.0))
        f = float(row.get("f", max(0.0, n - s)))

        a = float(row.get("alpha", 1.0 + s))
        b = float(row.get("beta",  1.0 + max(0.0, n - s)))

        ab_map[name] = (s, n, f, a, b)

    for name in sorted(all_names):
                s, n, f, a, b = ab_map.get(name, (0.0, 0.0, 0.0, 1.0, 1.0))
                payload.append({"name": name, 's': float(s), 'n': float(n), 'f': float(f), "alpha": float(a), "beta": float(b)})


    cur.execute("DELETE FROM mab_stats")
    for row in payload:
        cur.execute(
            (
                "INSERT INTO mab_stats (name, s, n, f, alpha, beta, window_start, window_end, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
            ),
            (
                row["name"],
                row['s'],
                row['n'],
                row['f'],
                row["alpha"],
                row["beta"],
                window_start_iso,
                window_end_iso,
                _iso_now_seconds(),
            ),
        )

    conn.commit()
    conn.close()
    # print(agg)
    # print(payload)
    if __name__ == "__main__":
         return df, agg, payload
    return payload



if __name__ == "__main__":
    df, agg, stats = update_mab_stats()
    import random
    samples = [
            (row["name"], random.betavariate(max(1e-6, float(row["alpha"])), max(1e-6, float(row["beta"]))))
            for row in stats
        ]
    samples.sort(key=lambda x: x[1], reverse=True)

    print(f"\n Just Thompson samples: {samples[:7]}")

    chosen_names = [name for name, _ in samples[:7]]
    print(chosen_names)

    print(df)
    print(agg)