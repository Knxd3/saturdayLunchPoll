from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Iterable, List, Dict, Any

import numpy as np
import pandas as pd
from scipy.stats import beta as sp_beta

from .db import get_db_connection
from .timeutil import week_monday_london, now_london, iso_seconds_local


@dataclass
class PosteriorRow:
    week_created_at: str  # ISO seconds, London tz
    name: str
    s: float
    n: float
    f: float
    alpha: float
    beta: float
    mean: float
    lower: float | None
    upper: float | None


def _fetch_weekly_votes_frame(conn: sqlite3.Connection, window_start_iso: str | None = None) -> pd.DataFrame:
    """Load per-restaurant weekly results joined with weekly trial counts.

    - Uses `weekly_results` for per-restaurant weekly votes.
    - Joins `votes` to compute weekly trial counts (number of distinct voters per week).
    - Optionally filters rows newer than `window_start_iso`.
    """
    # Intentionally avoid time filtering to ensure we pick up all historical rows
    params: Dict[str, Any] = {}
    where = ""

    sql = f"""
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
    {where}
    """
    df = pd.read_sql(sql, conn, params=params)
    # Normalize dtypes and timestamps
    df["week_created_at"] = pd.to_datetime(df["week_created_at"], utc=True, errors="coerce")
    return df


def build_weekly_posteriors(
    window_weeks: int = 200,
    half_life_weeks: int = 13,
    alpha0: float = 1.0, # increase to narrow CI and underweigh the evidence; change acf below to narrow CI and overweigh the evidence
    beta0: float = 1.0, # increase to narrow CI and underweigh the evidence; change acf below to narrow CI and overweigh the evidence
) -> List[PosteriorRow]:
    """Compute weekly posterior snapshots for each restaurant.

    Mirrors the weighting/decay from MBA.update_mab_stats but produces a
    snapshot "as of" each historical week timestamp in `weekly_results`.

    - For a given snapshot week W, we:
      - Include rows with created_at in (W - window_weeks, W].
      - Compute `weeks_ago` relative to Monday of W (London tz).
      - Apply exponential decay: w = gamma ** weeks_ago, where
        gamma = 0.5 ** (1 / half_life_weeks).
      - Aggregate decayed successes/trials per restaurant, then apply
        Beta(alpha0 + s, beta0 + (n - s)).
    - Returns a flat list of PosteriorRow sorted by week then name.
    """
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # We do not filter by restaurants table here; include all names present in history.

    # Use a soft cutoff window_start for IO; final per-week filter is done below
    from datetime import timedelta
    window_end = now_london()
    window_start_iso = iso_seconds_local(window_end - timedelta(weeks=max(1, int(window_weeks))))

    df = _fetch_weekly_votes_frame(conn, window_start_iso=window_start_iso)
    if df.empty:
        conn.close()
        return []

    # Fill weekly trial counts fallback and ensure numeric types
    df["trials"] = df["trials"].fillna(df.groupby("week_created_at")["votes"].transform("sum"))
    
    # Inflate the evidence for narrower confidence bands?
    # change acf below to narrow CI and overweigh the evidence
    # E[v/r] =  E[v] * p(r); 
    acf = 9
    df["votes"] = df["votes"].astype(float) * acf
    df["trials"] = df["trials"].astype(float) * acf

    # Unique timeline of weeks to snapshot (sorted)
    timeline = (
        df["week_created_at"].dropna().drop_duplicates().sort_values().to_list()
    )
    if not timeline:
        conn.close()
        return []

    results: List[PosteriorRow] = []
    gamma = 0.5 ** (1.0 / max(1, int(half_life_weeks)))

    for asof_ts in timeline:
        # Use the actual weekly_results timestamp as the snapshot anchor.
        # This avoids excluding the same week's rows by anchoring to Monday.
        asof_anchor = pd.Timestamp(asof_ts)

        # Restrict rows to the rolling window ending at asof_anchor
        lower_bound = asof_anchor - pd.Timedelta(weeks=max(1, int(window_weeks)))
        mask = (df["week_created_at"] > lower_bound) & (df["week_created_at"] <= asof_anchor)
        df_win = df.loc[mask].copy()
        if df_win.empty:
            continue

        # Compute weeks_ago relative to asof_anchor
        weeks_ago = np.floor(
            (asof_anchor - df_win["week_created_at"]).dt.total_seconds() / (7 * 24 * 3600)
        ).astype("Int64")
        weeks_ago = weeks_ago.clip(lower=0)
        df_win["weeks_ago"] = weeks_ago.astype(int)

        # Decay weights and effective counts
        w = np.power(gamma, df_win["weeks_ago"].to_numpy())
        df_win["s_decayed"] = df_win["votes"].astype(float) * w
        df_win["n_decayed"] = df_win["trials"].astype(float) * w

        # Aggregate by restaurant
        agg = df_win.groupby("name", as_index=False).agg(
            s=("s_decayed", "sum"),
            n=("n_decayed", "sum"),
        )
        agg["f"] = agg["n"] - agg["s"]
        agg["alpha"] = alpha0 + agg["s"]
        agg["beta"] = beta0 + (agg["n"] - agg["s"]) 
        agg["mean"] = agg["alpha"] / (agg["alpha"] + agg["beta"]) 

        # Credible interval (95%); tolerate numeric issues
        try:
            agg["lower"] = sp_beta.ppf(0.05, agg["alpha"], agg["beta"])  # type: ignore[arg-type]
            agg["upper"] = sp_beta.ppf(0.95, agg["alpha"], agg["beta"])  # type: ignore[arg-type]
        except Exception:
            agg["lower"] = np.nan
            agg["upper"] = np.nan

        # Emit PosteriorRow per allowed name, week label is the as-of timestamp (local ISO)
        asof_iso = iso_seconds_local(asof_anchor.to_pydatetime())
        for _, row in agg.iterrows():  # type: ignore[attr-defined]
            name = str(row["name"])
            s = float(row.get("s", 0.0))
            n = float(row.get("n", 0.0))
            f = float(row.get("f", max(0.0, n - s)))
            a = float(row.get("alpha", 1.0 + s))
            b = float(row.get("beta", 1.0 + max(0.0, n - s)))
            mean = float(row.get("mean", a / (a + b)))
            lower = row.get("lower", np.nan)
            upper = row.get("upper", np.nan)
            results.append(
                PosteriorRow(
                    week_created_at=asof_iso,
                    name=name,
                    s=s,
                    n=n,
                    f=f,
                    alpha=a,
                    beta=b,
                    mean=mean,
                    lower=None if pd.isna(lower) else float(lower),
                    upper=None if pd.isna(upper) else float(upper),
                )
            )

    conn.close()
    # Sort by week then name for stable consumers
    results.sort(key=lambda r: (r.week_created_at, r.name))
    return results


def build_chart_series(
    rows: Iterable[PosteriorRow],
    include_ci: bool = True,
) -> List[Dict[str, Any]]:
    """Pivot PosteriorRow list into a chart-friendly series.

    Output shape per timepoint (week):
      {
        "week": "YYYY-MM-DDTHH:MM:SS+01:00",
        "<name>_mean": float,
        "<name>_lo": float (optional),
        "<name>_band": float (optional)  # hi - lo
      }

    This aligns with the stacked Area + Line approach used in the provided
    Recharts example (lo + band).
    """
    # Group by week
    by_week: Dict[str, List[PosteriorRow]] = {}
    for r in rows:
        by_week.setdefault(r.week_created_at, []).append(r)

    series: List[Dict[str, Any]] = []
    for week_iso in sorted(by_week.keys()):
        point: Dict[str, Any] = {"week": week_iso}
        for r in by_week[week_iso]:
            key = r.name
            point[f"{key}_mean"] = r.mean
            if include_ci and (r.lower is not None) and (r.upper is not None):
                point[f"{key}_lo"] = r.lower
                point[f"{key}_band"] = max(0.0, r.upper - r.lower)
        series.append(point)
    return series


if __name__ == "__main__":
    # Quick manual run to verify shape
    rows = build_weekly_posteriors()
    print(f"rows: {len(rows)}")
    for r in rows[:10]:
        print(r)
    series = build_chart_series(rows)
    print(f"series points: {len(series)}")
    for p in series[:5]:
        print(p)
