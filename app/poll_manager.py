import os
import sqlite3
import hashlib
import random
from datetime import datetime, timedelta, time
from .MBA import update_mab_stats

DB_PATH = os.environ.get("DB_PATH", "database.db")
IP_SALT = os.environ.get("IP_SALT", "change-me-salt")


def _now() -> datetime:
    return datetime.now()


def _next_monday_10am(after_dt: datetime) -> datetime:
    # Compute Monday 10:00 of the week AFTER the week containing after_dt
    week_monday = after_dt.date() - timedelta(days=after_dt.weekday())
    next_week_monday = week_monday + timedelta(days=7)
    return datetime.combine(next_week_monday, time(10, 0))


def _get_last_generated_at(conn: sqlite3.Connection) -> datetime | None:
    row = conn.execute("SELECT MAX(created_at) AS ts FROM weekly_selection").fetchone()
    if row and row["ts"]:
        try:
            return datetime.fromisoformat(row["ts"])  # created via ISO format
        except Exception:
            return None
    return None


def get_latest_created_at_iso() -> str | None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        last = _get_last_generated_at(conn)
        return last.isoformat(timespec="seconds") if last else None


def should_refresh_weekly_selection(now: datetime | None = None) -> bool:
    now = now or _now()
    with sqlite3.connect(DB_PATH) as conn:
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
    now_iso = _now().isoformat(timespec="seconds")
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Update bandit stats and sample scores
        stats = update_mab_stats()
        if not stats:
            return
        samples = [
            (row["name"], random.betavariate(max(1e-6, float(row["alpha"])), max(1e-6, float(row["beta"]))))
            for row in stats
        ]
        samples.sort(key=lambda x: x[1], reverse=True)
        chosen_names = [name for name, _ in samples[:7]]
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
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        last = _get_last_generated_at(conn)
        if not last:
            return []
        ts = last.isoformat(timespec="seconds")
        # Compute votes from normalized table to avoid any stale counters
        rows = conn.execute(
            (
                "SELECT ws.id, ws.name, ws.address, ws.cuisine, ws.average_price, ws.rating, ws.reviews, ws.offer, ws.url, "
                "COALESCE(v.cnt, 0) AS votes "
                "FROM weekly_selection ws "
                "LEFT JOIN (SELECT option_id, COUNT(*) AS cnt FROM votes WHERE week_created_at = ? GROUP BY option_id) v "
                "ON v.option_id = ws.id "
                "WHERE ws.created_at = ?"
            ),
            (ts, ts),
        ).fetchall()
        options = [dict(r) for r in rows]
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
        return options


def backfill_current_selection_details() -> None:
    """Backfill any NULL detail columns in the current batch from restaurants.
    Matches by name. Safe to call repeatedly.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        last = _get_last_generated_at(conn)
        if not last:
            return
        ts = last.isoformat(timespec="seconds")
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
    with sqlite3.connect(DB_PATH) as conn:
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
    now_iso = _now().isoformat(timespec="seconds")
    with sqlite3.connect(DB_PATH) as conn:
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
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        last = _get_last_generated_at(conn)
        if not last:
            return False
        week_monday = last.date() - timedelta(days=last.weekday())
        open_start = datetime.combine(week_monday, time(10, 0))
        close_end = datetime.combine(week_monday + timedelta(days=2), time(23, 0))  # Wed 23:00
        return open_start <= now <= close_end


def get_voting_window() -> dict:
    """Return the voting window for the current selection as ISO strings."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        last = _get_last_generated_at(conn)
        if not last:
            return {"open": None, "close": None}
        week_monday = last.date() - timedelta(days=last.weekday())
        open_start = datetime.combine(week_monday, time(10, 0))
        close_end = datetime.combine(week_monday + timedelta(days=2), time(23, 0))
        return {"open": open_start.isoformat(timespec="minutes"), "close": close_end.isoformat(timespec="minutes")}


def record_vote(option_id: int, voter: dict | None = None) -> bool:
    """Increment vote for a given option id and record voter profile in normalized table.
    Returns True if a new vote was recorded, False otherwise.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        last = _get_last_generated_at(conn)
        if not last:
            return False
        ts = last.isoformat(timespec="seconds")
        cur = conn.cursor()
        email = (voter or {}).get("email") if voter else None
        name = (voter or {}).get("name") if voter else None
        picture = (voter or {}).get("picture") if voter else None
        if not email:
            return False
        # Try to insert a vote row; unique constraint prevents duplicates per option/email/week
        try:
            cur.execute(
                (
                    "INSERT INTO votes (week_created_at, option_id, email, name, picture, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)"
                ),
                (ts, option_id, email, name, picture, _now().isoformat(timespec="seconds")),
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
