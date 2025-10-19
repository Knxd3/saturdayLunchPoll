import os
import sqlite3
import hashlib
import random
from datetime import datetime
from .MBA import update_mab_stats
from scipy.stats import beta as sp_beta
from .timeutil import (
    now_london,
    to_london,
    iso_seconds_local,
    next_monday_10_london,
    voting_window_london,
)

DB_PATH = os.environ.get("DB_PATH", "database.db")
IP_SALT = os.environ.get("IP_SALT", "change-me-salt")


def _now() -> datetime:
    # Standardized London-local current time (aware)
    return now_london()


def _next_monday_10am(after_dt: datetime) -> datetime:
    # Monday 10:00 (Europe/London) of the week AFTER `after_dt`
    return next_monday_10_london(after_dt)


def _get_last_generated_at(conn: sqlite3.Connection) -> datetime | None:
    row = conn.execute("SELECT MAX(created_at) AS ts FROM weekly_selection").fetchone()
    if row and row["ts"]:
        try:
            # Stored as ISO without offset; treat as London local
            return to_london(datetime.fromisoformat(row["ts"]))
        except Exception:
            return None
    return None


def get_latest_created_at_iso() -> str | None:
    # Return the exact stored string to keep FK/joins stable
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT MAX(created_at) AS ts FROM weekly_selection").fetchone()
        return row["ts"] if row and row["ts"] else None


def should_refresh_weekly_selection(now: datetime | None = None) -> bool:
    now = to_london(now) if now else _now()
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        last = _get_last_generated_at(conn)
        if last is None:
            return True
        return now >= _next_monday_10am(last)


"""
def refresh_weekly_selection() -> None:
    ...  # Old random sampler preserved for reference
"""


def refresh_weekly_selection() -> None:
    """Rotate weekly selection using Thompson Sampling over Beta priors.

    Chooses 7 restaurants by sampling Beta(alpha, beta) where alpha/beta come
    from a rolling window of weekly_results weighted by per-week turnout.
    Preserves the output shape and archiving semantics of the previous version.
    """
    now_iso = iso_seconds_local(_now())
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Update bandit stats and sample scores
        stats = update_mab_stats()
        if not stats:
            return
        # Thompson sampling with clipped Beta sample to reduce extreme randomness
        
        samples = []
        for row in stats:
            a = max(1e-6, float(row.get("alpha", 1.0)))
            b = max(1e-6, float(row.get("beta", 1.0)))
            p = random.betavariate(a, b)
            if sp_beta is not None:
                # Clip to central 95% interval (2.5%..97.5%) to dampen variance
                lo = float(sp_beta.ppf(0.025, a, b))
                hi = float(sp_beta.ppf(0.975, a, b))
                if lo <= hi:
                    p = min(max(p, lo), hi)
            samples.append((row["name"], p))
        samples.sort(key=lambda x: x[1], reverse=True)
        chosen_names = [name for name, _ in samples[:7]]
        # print(samples[:7])
        if not chosen_names:
            return

        # Archive the finishing week
        rows_ = cur.execute(
            """
            SELECT name, address, cuisine, average_price, rating, reviews, offer, url, votes, created_at
            FROM weekly_selection
            """
        ).fetchall()
        for r in rows_:
            cur.execute(
                (
                    "INSERT INTO weekly_results"
                    "(name, address, cuisine, average_price, rating, reviews, offer, url, votes, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                ),
                (
                    r["name"],
                    r["address"] if "address" in r.keys() else None,
                    r["cuisine"] if "cuisine" in r.keys() else None,
                    r["average_price"] if "average_price" in r.keys() else None,
                    r["rating"] if "rating" in r.keys() else None,
                    r["reviews"] if "reviews" in r.keys() else None,
                    r["offer"] if "offer" in r.keys() else None,
                    r["url"] if "url" in r.keys() else None,
                    r["votes"] if "votes" in r.keys() else None,
                    r["created_at"] if "created_at" in r.keys() else now_iso,
                ),
            )

        # Replace current batch using chosen names
        cur.execute("DELETE FROM weekly_selection")

        # Fetch all chosen rows in one go, then insert in sampled order
        placeholders = ",".join(["?"] * len(chosen_names))
        rs = cur.execute(
            (
                "SELECT name, address, cuisine, average_price, rating, reviews, offer, url "
                f"FROM restaurants WHERE COALESCE(is_excluded,0)=0 AND name IN ({placeholders})"
            ),
            chosen_names,
        ).fetchall()
        by_name = {r["name"]: r for r in rs}

        for nm in chosen_names:
            r = by_name.get(nm)
            if not r:
                continue
            cur.execute(
                (
                    "INSERT INTO weekly_selection "
                    "(name, address, cuisine, average_price, rating, reviews, offer, url, votes, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                ),
                (
                    r["name"],
                    r["address"] if "address" in r.keys() else None,
                    r["cuisine"] if "cuisine" in r.keys() else None,
                    r["average_price"] if "average_price" in r.keys() else None,
                    r["rating"] if "rating" in r.keys() else None,
                    r["reviews"] if "reviews" in r.keys() else None,
                    r["offer"] if "offer" in r.keys() else None,
                    r["url"] if "url" in r.keys() else None,
                    0,
                    now_iso,
                ),
            )
        conn.commit()


def ensure_weekly_selection() -> None:
    if should_refresh_weekly_selection():
        refresh_weekly_selection()
    else:
        # Best-effort backfill in case schema evolved and details are missing
        backfill_current_selection_details()


def get_current_week_selection() -> list[dict]:
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        last = _get_last_generated_at(conn)
        if not last:
            return []
        ts = get_latest_created_at_iso()
        # Compute votes from normalized table and join restaurants for exclusion flag
        rows = conn.execute(
            (
                "SELECT ws.id, ws.name, ws.address, ws.cuisine, ws.average_price, ws.rating, ws.reviews, ws.offer, ws.url, "
                "COALESCE(v.cnt, 0) AS votes, COALESCE(r.is_excluded, 0) AS is_excluded "
                "FROM weekly_selection ws "
                "LEFT JOIN (SELECT option_id, COUNT(*) AS cnt FROM votes WHERE week_created_at = ? GROUP BY option_id) v "
                "ON v.option_id = ws.id "
                "LEFT JOIN restaurants r ON r.name = ws.name "
                "WHERE ws.created_at = ?"
            ),
            (ts, ts),
        ).fetchall()
        options = [dict(r) for r in rows]
        # Compute derived display fields (e.g., Net Average from average_price and offer, beta credible interval)
        import re
        def _parse_price(val: str | None) -> float | None:
            if not val:
                return None
            s = str(val)
            m = re.search(r"(\d+(?:[\.,]\d+)?)", s)
            if not m:
                return None
            num = m.group(1).replace(',', '.')
            try:
                return float(num)
            except Exception:
                return None
        def _parse_percent(val) -> float | None:
            if val is None:
                return None
            s = str(val)
            m = re.search(r"(\d+(?:[\.,]\d+)?)", s)
            if not m:
                return None
            num = m.group(1).replace(',', '.')
            try:
                v = float(num)
            except Exception:
                return None
            # Treat values > 1 as percent (e.g., 20 means 20%), else already fraction
            return v/100.0 if v > 1.0 else v
        for opt in options:
            price = _parse_price(opt.get('average_price'))
            pct = _parse_percent(opt.get('offer'))
            rating_val = opt.get('rating')
            rating = _parse_price(rating_val) if rating_val not in (None, "") else None
            reviews_val = opt.get('reviews')
            reviews_num = _parse_price(reviews_val) if reviews_val not in (None, "") else None
            reviews = int(reviews_num) if reviews_num is not None else None
            if price is not None and pct is not None:
                net = max(0.0, price * (1.0 - pct))
                opt['net_average'] = net
            
            if rating is not None and reviews is not None:
                max_rating = 10
                s = rating / max_rating * reviews 
                prior_alpha = 1.0
                prior_beta = 1.0
                posterior_alpha = (prior_alpha + s)
                posterior_beta = (prior_beta + reviews - s)
                posterior_mean = max_rating * posterior_alpha / (posterior_alpha + posterior_beta)
                    
                qlo5 = max_rating * sp_beta.ppf(0.025, posterior_alpha, posterior_beta)
                qhi5 = max_rating * sp_beta.ppf(0.975, posterior_alpha, posterior_beta)

                opt['posterior_mean'] = posterior_mean
                opt['qlo5'] = qlo5
                opt['qhi5'] = qhi5

        # Attach voter profiles per option from normalized votes table
        vote_rows = conn.execute(
            (
                "SELECT option_id, email, name, picture FROM votes "
                "WHERE week_created_at = ? ORDER BY id ASC"
            ),
            (ts,),
        ).fetchall()
        voters_by_option: dict[int, list[dict]] = {}
        for vr in vote_rows:
            voters_by_option.setdefault(vr["option_id"], []).append(
                {"email": vr["email"], "name": vr["name"] or vr["email"], "picture": vr["picture"]}
            )
        for opt in options:
            opt["voters"] = voters_by_option.get(opt["id"], [])
        # # Optional: inject dummy voters for preview (set PREVIEW_DUMMY_VOTERS=1)
        # import os as _os
        # # if _os.environ.get("PREVIEW_DUMMY_VOTERS") == "1":
        # if 1:
        #     dummy_pool = [
        #         {"email": "alice@example.com", "name": "Alice", "picture": "https://i.pravatar.cc/28?img=1"},
        #         {"email": "bob@example.com", "name": "Bob", "picture": "https://i.pravatar.cc/28?img=2"},
        #         {"email": "carol@example.com", "name": "Carol", "picture": "https://i.pravatar.cc/28?img=3"},
        #         {"email": "dave@example.com", "name": "Dave", "picture": "https://i.pravatar.cc/28?img=4"},
        #         {"email": "eve@example.com", "name": "Eve", "picture": "https://i.pravatar.cc/28?img=5"},
        #     ]
        #     for opt in options:
        #         current = list(opt.get("voters") or [])
        #         # If there are no voters yet, add a few dummies so avatars render
        #         if not current:
        #             k = 3
        #             current = dummy_pool[:k]
        #         opt["voters"] = current
        #         # Keep vote chip from looking empty when avatars show
        #         try:
        #             opt["votes"] = max(int(opt.get("votes") or 0), len(current))
        #         except Exception:
        #             pass
        return options


def backfill_current_selection_details() -> None:
    """Backfill any NULL detail columns in the current batch from restaurants.
    Matches by name. Safe to call repeatedly.
    """
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        last = _get_last_generated_at(conn)
        if not last:
            return
        ts = get_latest_created_at_iso()
        cur = conn.cursor()
        cur.execute(
            (
                "UPDATE weekly_selection SET "
                "address = COALESCE(address, (SELECT address FROM restaurants WHERE restaurants.name = weekly_selection.name LIMIT 1)), "
                "cuisine = COALESCE(cuisine, (SELECT cuisine FROM restaurants WHERE restaurants.name = weekly_selection.name LIMIT 1)), "
                "average_price = COALESCE(average_price, (SELECT average_price FROM restaurants WHERE restaurants.name = weekly_selection.name LIMIT 1)), "
                "rating = COALESCE(rating, (SELECT rating FROM restaurants WHERE restaurants.name = weekly_selection.name LIMIT 1)), "
                "reviews = COALESCE(reviews, (SELECT reviews FROM restaurants WHERE restaurants.name = weekly_selection.name LIMIT 1)), "
                "offer = COALESCE(offer, (SELECT offer FROM restaurants WHERE restaurants.name = weekly_selection.name LIMIT 1)), "
                "url = COALESCE(url, (SELECT url FROM restaurants WHERE restaurants.name = weekly_selection.name LIMIT 1)) "
                "WHERE created_at = ?"
            ),
            (ts,),
        )
        conn.commit()


def hash_ip(ip: str | None) -> str:
    raw = f"{IP_SALT}|{ip or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def voter_already_voted(voter_id: str | None, ip_hash: str | None) -> bool:
    ts = get_latest_created_at_iso()
    if not ts:
        return False
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT 1 FROM voter_log
            WHERE week_created_at = ? AND (voter_id = ? OR ip_hash = ?)
            LIMIT 1
            """,
            (ts, voter_id or "", ip_hash or ""),
        ).fetchone()
        return row is not None


def log_voter(voter_id: str, ip_hash: str, user_agent: str | None, email: str | None = None) -> None:
    ts = get_latest_created_at_iso()
    if not ts:
        return
    now_iso = iso_seconds_local(_now())
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        cur = conn.cursor()
        try:
            # Prefer inserting email if the column exists
            cur.execute(
                (
                    "INSERT INTO voter_log (week_created_at, voter_id, ip_hash, user_agent, email, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)"
                ),
                (ts, voter_id, ip_hash, user_agent or "", email or "", now_iso),
            )
            conn.commit()
        except Exception:
            try:
                # Fallback for older schemas without email column
                cur.execute(
                    (
                        "INSERT INTO voter_log (week_created_at, voter_id, ip_hash, user_agent, created_at) "
                        "VALUES (?, ?, ?, ?, ?)"
                    ),
                    (ts, voter_id, ip_hash, user_agent or "", now_iso),
                )
                conn.commit()
            except Exception:
                # Ignore uniqueness collisions or other insert errors
                pass


def is_voting_open(now: datetime | None = None) -> bool:
    """Voting is open from Monday 10:00 to Wednesday 23:00 of the current selection week."""
    now = now or _now()
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        last = _get_last_generated_at(conn)
        if not last:
            return False
        open_start, close_end = voting_window_london(last)
        return open_start <= to_london(now) <= close_end


def get_voting_window() -> dict:
    """Return the voting window for the current selection as ISO strings (no offset)."""
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        last = _get_last_generated_at(conn)
        if not last:
            return {"open": None, "close": None}
        open_start, close_end = voting_window_london(last)
        return {
            "open": open_start.replace(tzinfo=None).isoformat(timespec="minutes"),
            "close": close_end.replace(tzinfo=None).isoformat(timespec="minutes"),
        }


def record_vote(option_id: int, voter: dict | None = None) -> bool:
    """Increment vote for a given option id and record voter profile in normalized table.
    Returns True if a new vote was recorded, False otherwise.
    """
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        last = _get_last_generated_at(conn)
        if not last:
            return False
        # Use the exact stored ISO string for joins and keys
        ts_row = conn.execute("SELECT MAX(created_at) AS ts FROM weekly_selection").fetchone()
        ts = ts_row["ts"] if ts_row and ts_row["ts"] else None
        if not ts:
            return False
        cur = conn.cursor()
        email = (voter or {}).get("email") if voter else None
        name = (voter or {}).get("name") if voter else None
        picture = (voter or {}).get("picture") if voter else None
        if not email:
            return False
        # Do not allow voting on excluded options (joined by name)
        ex_row = conn.execute(
            (
                "SELECT COALESCE(r.is_excluded, 0) AS ex "
                "FROM weekly_selection ws LEFT JOIN restaurants r ON r.name = ws.name "
                "WHERE ws.id = ? AND ws.created_at = ?"
            ),
            (option_id, ts),
        ).fetchone()
        if not ex_row or int(ex_row["ex"] or 0) == 1:
            return False
        # Try to insert a vote row; unique constraint prevents duplicates per option/email/week
        try:
            cur.execute(
                (
                    "INSERT INTO votes (week_created_at, option_id, email, name, picture, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)"
                ),
                (ts, option_id, email, name, picture, iso_seconds_local(_now())),
            )
            # Increment the denormalized counter for quick reads
            cur.execute(
                "UPDATE weekly_selection SET votes = votes + 1 WHERE id = ? AND created_at = ?",
                (option_id, ts),
            )
            conn.commit()
            return cur.rowcount > 0
        except Exception:
            # Likely a uniqueness collision; treat as no-op
            return False


if __name__ == '__main__':
    # refresh_weekly_selection()
    
    stats = update_mab_stats()
    import random
    samples = [
            (row["name"], random.betavariate(max(1e-6, float(row["alpha"])), max(1e-6, float(row["beta"]))))
            for row in stats
        ]
    samples.sort(key=lambda x: x[1], reverse=True)

    print(f"\n Just Thompson samples: {samples[:7]}")
    # print(update_mab_stats())

    print(get_current_week_selection())
