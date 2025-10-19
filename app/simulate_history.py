"""
Utilities to simulate historical data into weekly_results and votes, and to clear them.

- simulate_history: creates N weeks of synthetic weekly_results rows and matching
  votes with consistent week timestamps so joins/aggregations work.
- clear_history: deletes all rows from votes and weekly_results.

This does not touch restaurants/weekly_selection and should not break other flows.
"""
from __future__ import annotations

import random
import string
from dataclasses import dataclass
from datetime import timedelta, time
from typing import Iterable, List

import sqlite3

from .db import get_db_connection
from .timeutil import week_monday_london, now_london, iso_seconds_local, to_london


@dataclass
class SimConfig:
    weeks: int = 20
    options_per_week: int = 7
    min_voters: int = 5
    max_voters: int = 8
    seed: int = 42
    # Fixed global pool size (same restaurants available every week)
    pool_size: int = 150
    # Bias controls: portion of restaurants with higher "true p"
    heavy_ratio: float = 0.01  # fraction of pool that are high performers
    base_p_range: tuple[float, float] = (0.1, 0.5)
    high_p_range: tuple[float, float] = (0.75, 0.99)
    week_noise: float = 0.06  # +/- noise added to per-week p
    # Voter preference matrix controls
    use_voter_matrix: bool = True
    voter_pool_size: int = 10
    voter_noise: float = 0.9  # per-voter deviation from restaurant base p
    # Raise probabilities to this power before sampling to sharpen choices
    temperature: float = 10
    # Debug printing controls
    verbose: bool = False
    debug_weeks: int = 5


def _make_week_label(base_monday, week_index: int) -> str:
    """Wednesday 09:00 local ISO string for the given week index."""
    week_start = base_monday + timedelta(weeks=week_index)
    weds_morning = to_london((week_start + timedelta(days=2)).replace(hour=9, minute=0, second=0, microsecond=0))
    return iso_seconds_local(weds_morning)


def _random_email(i: int) -> str:
    return f"user{i}@example.com"


def _random_name(i: int) -> str:
    return f"User {i}"


def clear_history() -> None:
    """Delete all rows from votes and weekly_results."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM votes")
    cur.execute("DELETE FROM weekly_results")
    conn.commit()
    conn.close()


def simulate_history(cfg: SimConfig | None = None) -> None:
    """Insert synthetic weekly_results and votes rows for demo/visualization.

    - Generates `cfg.weeks` of data.
    - For each week: creates `cfg.options_per_week` restaurants with varying
      probability of being chosen by voters.
    - Ensures weekly_results.votes equals the number of votes recorded in votes
      for that restaurant/week.
    - week_created_at in votes matches weekly_results.created_at exactly.
    """
    cfg = cfg or SimConfig()
    rnd = random.Random(cfg.seed)

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    base_monday = week_monday_london(now_london() - timedelta(weeks=cfg.weeks))

    # Global pool of synthetic restaurant names to draw from (fixed across weeks)
    pool_size = max(1, int(cfg.pool_size))
    restaurant_pool = [f"Restaurant {i+1}" for i in range(pool_size)]

    # Assign latent true probabilities (bias) per restaurant
    heavy_count = max(1, int(cfg.heavy_ratio * pool_size))
    heavy_names = set(rnd.sample(restaurant_pool, k=heavy_count))
    base_p_by_name: dict[str, float] = {}
    

    # Optional highly skewed true restaurant p
    for nm in restaurant_pool:
        lo, hi = cfg.high_p_range if nm in heavy_names else cfg.base_p_range # tuple assignment
        p =  rnd.uniform(lo, hi)
        w = p ** (cfg.temperature) # set temperature to 1 to remove skew
        base_p_by_name[nm] = w

    if cfg.temperature > 1:
        total = sum(base_p_by_name.values())
        base_p_by_name = {k: v / total for k, v in base_p_by_name.items()}

    if cfg.verbose:
        print(f"{base_p_by_name.values()}")

    if cfg.verbose:
        print(f"[simulate_history] pool_size={pool_size} heavy_count={heavy_count} heavy_ratio={cfg.heavy_ratio}")
        sorted_base = sorted(base_p_by_name.items(), key=lambda x: x[1], reverse=True)
        show = min(10, len(sorted_base))
        print("[simulate_history] top base p:")
        for nm, p in sorted_base[:show]:
            print(f"  {nm:<16} base_p={p:.4f} {'(HEAVY)' if nm in heavy_names else ''}")
        if len(sorted_base) > show:
            print("[simulate_history] bottom base p:")
            for nm, p in sorted_base[-show:]:
                print(f"  {nm:<16} base_p={p:.4f} {'(HEAVY)' if nm in heavy_names else ''}")

    # Optional per-voter preference matrix around base restaurant p
    voter_ids = list(range(max(1, int(cfg.voter_pool_size))))
    pref_by_voter_name: dict[int, dict[str, float]] = {}
    if cfg.use_voter_matrix:
        for v in voter_ids:
            mp: dict[str, float] = {}
            for nm in restaurant_pool:
                p0 = base_p_by_name[nm]
                p = max(0.001, min(0.999, p0 + rnd.uniform(-cfg.voter_noise, cfg.voter_noise)))
                mp[nm] = p
            pref_by_voter_name[v] = mp

    # Clear any existing simulated history? Leave as-is; caller can call clear_history.

    for w in range(cfg.weeks):
        week_ts = _make_week_label(base_monday, w)

        # Sample options for this week
        names = rnd.sample(restaurant_pool, k=cfg.options_per_week)

        # Per-week probabilities around latent true p with slight noise
        probs: list[float] = []
        for nm in names:
            p0 = base_p_by_name[nm]
            p = max(0.02, min(0.98, p0 + rnd.uniform(-cfg.week_noise, cfg.week_noise)))
            probs.append(p)

        # Decide how many voters this week
        voters = rnd.randint(cfg.min_voters, cfg.max_voters)
        if cfg.use_voter_matrix:
            voter_sample = rnd.sample(voter_ids, k=min(voters, len(voter_ids)))
        else:
            voter_sample = list(range(voters))

        # Prepare per-option vote counters
        counts = [0 for _ in names]
        if cfg.verbose and w < cfg.debug_weeks:
            # Precompute per-week debug stats
            base_ps = [base_p_by_name[nm] for nm in names]
            if cfg.use_voter_matrix:
                # Average preference across the sampled voters this week
                avg_prefs = []
                for nm in names:
                    vals = [pref_by_voter_name[v][nm] for v in voter_sample]
                    avg_prefs.append(sum(vals) / max(1, len(vals)))
                print(f"\n[simulate_history] Week {w} @ {week_ts}")
                for nm, b, ap in zip(names, base_ps, avg_prefs):
                    print(f"  show {nm:<16} base_p={b:.4f} avg_pref={ap:.4f}")
            else:
                # Population mode: show weekly probs
                print(f"\n[simulate_history] Week {w} @ {week_ts}")
                for nm, b, pw in zip(names, base_ps, probs):
                    print(f"  show {nm:<16} base_p={b:.4f} week_p={pw:.4f}")

        for i, v_id in enumerate(voter_sample):
            # Each voter casts exactly one vote to a single option
            if cfg.use_voter_matrix:
                prefs = pref_by_voter_name[v_id]
                weights = [max(1e-12, prefs[nm]) ** max(0.0, cfg.temperature) for nm in names]
            else:
                # Weighted choice by probs^temperature to amplify separation
                weights = [max(1e-12, p) ** max(0.0, cfg.temperature) for p in probs]
            total = sum(weights)
            r = rnd.random() * total
            acc = 0.0
            choice = 0
            for idx, w in enumerate(weights):
                acc += w
                if r <= acc:
                    choice = idx
                    break
            counts[choice] += 1

            # Insert into votes
            option_id = choice + 1  # keep 1..K per-week mapping; uniqueness is (week, option_id, email)
            voter_key = (v_id if cfg.use_voter_matrix else (w * 1000 + i))
            email = _random_email(voter_key)
            name = _random_name(voter_key)
            cur.execute(
                (
                    "INSERT INTO votes (week_created_at, option_id, email, name, picture, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)"
                ),
                (
                    week_ts,
                    option_id,
                    email,
                    name,
                    None,
                    week_ts,
                ),
            )

        # Insert weekly_results rows matching counts
        for idx, nm in enumerate(names):
            cur.execute(
                (
                    "INSERT INTO weekly_results (name, address, cuisine, average_price, rating, reviews, offer, url, is_excluded, votes, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                ),
                (
                    nm,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    0,
                    counts[idx],
                    week_ts,
                ),
            )
        if cfg.verbose and w < cfg.debug_weeks:
            total_votes = sum(counts) or 1
            shares = [c / total_votes for c in counts]
            print("[simulate_history] counts/share:")
            for nm, c, s in zip(names, counts, shares):
                print(f"  {nm:<16} count={c:4d} share={s:0.3f}")

    conn.commit()
    # Print per-restaurant total votes summary if verbose
    if cfg.verbose:
        try:
            rows = conn.execute(
                "SELECT name, SUM(COALESCE(votes,0)) AS tot FROM weekly_results GROUP BY name ORDER BY tot DESC, name ASC"
            ).fetchall()
            print("\n[simulate_history] Total votes by restaurant (descending):")
            grand = sum(int(r["tot"] or 0) for r in rows) or 1
            for r in rows:
                tot = int(r["tot"] or 0)
                pct = 100.0 * tot / grand
                print(f"  {r['name']:<16} total={tot:5d}  ({pct:5.1f}%)")
        except Exception as e:
            print(f"[simulate_history] Failed to summarize totals: {e}")
    conn.close()


if __name__ == "__main__":
    # Example usage: clear and reseed 10 weeks
    print("Clearing votes and weekly_results...")
    clear_history()
    print("Seeding synthetic history...")
    simulate_history(SimConfig(weeks=250, options_per_week=7, min_voters=5, max_voters=10, seed=1, verbose=True))
    print("Done.")
