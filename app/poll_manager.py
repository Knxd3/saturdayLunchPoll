import os
import re
import sqlite3
import hashlib
import random
from collections import defaultdict
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from .MBA import update_mab_stats
from .settings import WEEKLY_SELECTION_SIZE
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
AUTO_REFRESH_RESTAURANTS = os.environ.get("AUTO_REFRESH_RESTAURANTS", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
FALLBACK_SEARCH_URL = (
    "https://www.thefork.co.uk/search?cityId=665790&date=2026-02-28&hour=780&p=1"
    "&partySize=5&promotionOnly=true&timezone=Europe%2FLondon"
)


def _env_int(name: str, default: int) -> int:
    val = os.environ.get(name)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _env_flag(name: str, default: bool = True) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() not in {"0", "false", "no", "off"}


def _next_saturday_date(now: datetime | None = None) -> str:
    dt = to_london(now) if now else _now()
    days_ahead = (5 - dt.weekday()) % 7
    target = dt + timedelta(days=days_ahead)
    return target.date().isoformat()


def _normalize_search_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    target_date = _next_saturday_date()
    replaced_date = False
    replaced_page = False
    out_pairs: list[tuple[str, str]] = []
    for k, v in pairs:
        if k == "date":
            v = target_date
            replaced_date = True
        elif k == "p":
            v = "1"
            replaced_page = True
        out_pairs.append((k, v))
    if not replaced_date:
        out_pairs.append(("date", target_date))
    if not replaced_page:
        out_pairs.append(("p", "1"))
    new_query = urlencode(out_pairs, doseq=True)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment))


def _scrape_latest_catalog() -> list[dict] | None:
    pages = max(1, _env_int("SCRAPER_PAGE_COUNT", _env_int("SCRAPER_PAGES", 10)))
    base_url = os.environ.get("SCRAPER_BASE_URL")
    # Default to the offline BeautifulSoup parser; Selenium requires a full
    # Chrome/driver stack which is unavailable on Fly's shared machines and
    # can hang worker startups while it tries to download binaries.
    use_selenium = _env_flag("SCRAPER_USE_SELENIUM", False)
    scrape_fn = None
    default_url = base_url

    if use_selenium:
        try:
            from . import scraper_selenium as scraper_mod

            scrape_fn = scraper_mod.scrape_restaurants
            if not default_url:
                default_url = getattr(scraper_mod, "DEFAULT_SEARCH_URL", None)
        except Exception as exc:
            print(f"[poll_manager] Selenium scraper unavailable: {exc}")

    if scrape_fn is None:
        try:
            from . import scraper as scraper_mod

            scrape_fn = scraper_mod.scrape_restaurants
            if not default_url:
                default_url = getattr(scraper_mod, "DEFAULT_SEARCH_URL", None)
        except Exception as exc:
            print(f"[poll_manager] Requests scraper unavailable: {exc}")
            return None

    target_url = _normalize_search_url(default_url or FALLBACK_SEARCH_URL)
    try:
        return scrape_fn(base_url=target_url, pages=pages)
    except Exception as exc:
        print(f"[poll_manager] scrape failed: {exc}")
        return None


def _ensure_restaurant_schema(cur: sqlite3.Cursor) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS restaurants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            address TEXT,
            cuisine TEXT,
            average_price REAL,
            rating REAL,
            reviews REAL,
            offer REAL,
            url TEXT,
            is_excluded INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    try:
        cur.execute("ALTER TABLE restaurants ADD COLUMN is_excluded INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass


def _refresh_restaurant_catalog_from_scrape() -> bool:
    scraped = _scrape_latest_catalog()
    if not scraped:
        return False

    deduped: list[dict] = []
    seen: set[str] = set()
    for row in scraped:
        name = (row.get("name") or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)

    if not deduped:
        return False

    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        _ensure_restaurant_schema(cur)

        exclusion_map: dict[str, int] = {}
        try:
            rows = cur.execute(
                "SELECT COALESCE(url, '') AS url, name, COALESCE(is_excluded, 0) AS ex FROM restaurants"
            ).fetchall()
            for row in rows:
                key = (row["url"] or "").strip().lower() or (row["name"] or "").strip().lower()
                if key:
                    exclusion_map[key] = int(row["ex"] or 0)
        except sqlite3.OperationalError:
            exclusion_map = {}

        try:
            conn.execute("BEGIN")
            cur.execute("DELETE FROM restaurants")
            insert_sql = (
                "INSERT INTO restaurants (name, address, cuisine, average_price, rating, reviews, offer, url, is_excluded)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
            )
            for row in deduped:
                name = (row.get("name") or "").strip()
                if not name:
                    continue
                key = (row.get("url") or "").strip().lower() or name.lower()
                cur.execute(
                    insert_sql,
                    (
                        name,
                        row.get("address"),
                        row.get("cuisine"),
                        row.get("average_price"),
                        row.get("rating"),
                        row.get("reviews"),
                        row.get("offer"),
                        row.get("url"),
                        exclusion_map.get(key, 0),
                    ),
                )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            print(f"[poll_manager] failed to refresh restaurants table: {exc}")
            return False

    return True


def _now() -> datetime:
    # Standardized London-local current time (aware)
    return now_london()


def _next_monday_10am(after_dt: datetime) -> datetime:
    # Next Sunday 09:00 (Europe/London) after `after_dt`
    return next_monday_10_london(after_dt)


def _coerce_numeric(val) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        pass
    m = re.search(r"-?\d+(?:[\.,]\d+)?", s)
    if not m:
        return None
    num = m.group(0).replace(",", ".")
    try:
        return float(num)
    except Exception:
        return None


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
def refresh_weekly_selection(min_offer: float | int | None = 30, selection_size: int | None = None) -> None:
    """Rotate weekly selection using Thompson Sampling over Beta priors.

    Chooses ``selection_size`` restaurants (10 by default) by sampling
    Beta(alpha, beta) where alpha/beta come from a rolling window of
    weekly_results weighted by per-week turnout.
    Preserves the output shape and archiving semantics of the previous version.
    If ``min_offer`` is provided, only restaurants with ``offer`` strictly
    greater than that value are eligible; pass ``None`` to disable the filter.
    """
    if AUTO_REFRESH_RESTAURANTS:
        _refresh_restaurant_catalog_from_scrape()

    try:
        size = int(selection_size) if selection_size is not None else WEEKLY_SELECTION_SIZE
    except Exception:
        size = WEEKLY_SELECTION_SIZE
    size = max(1, size)

    now_iso = iso_seconds_local(_now())
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Update bandit stats and sample scores
        stats = update_mab_stats()
        if not stats:
            return
        # Thompson sampling with clipped Beta sample to reduce extreme randomness
        
        restaurant_meta: dict[str, dict[str, object]] = {
            row["name"]: {
                "cuisine": (row["cuisine"] or "").strip().lower(),
                "offer": row["offer"],
            }
            for row in cur.execute(
                "SELECT name, cuisine, offer FROM restaurants WHERE COALESCE(is_excluded,0)=0"
            )
        }

        def _passes_offer_filter(name: str) -> bool:
            if min_offer is None:
                return True
            meta = restaurant_meta.get(name)
            if not meta:
                return False
            offer_val = _coerce_numeric(meta.get("offer"))
            if offer_val is None:
                return False
            try:
                threshold = float(min_offer)
            except Exception:
                threshold = 30.0
            return offer_val > threshold

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

        filtered_samples = samples if min_offer is None else [item for item in samples if _passes_offer_filter(item[0])]
        if len(filtered_samples) < size:
            reason = "eligible restaurants"
            if min_offer is not None:
                reason = f"restaurants match offer > {min_offer}"
            print(
                f"[refresh_weekly_selection] Only {len(filtered_samples)} {reason}; "
                f"need at least {size}. Skipping refresh."
            )
            return

        # Limit any single cuisine to at most two selections per week (fallback fills if needed)
        def _cuisine_key(name: str) -> str:
            meta = restaurant_meta.get(name) or {}
            cuisine = str(meta.get("cuisine") or "").strip().lower()
            return cuisine if cuisine else "unknown"

        max_per_cuisine = 2
        cuisine_counts: dict[str, int] = defaultdict(int)
        chosen_names: list[str] = []
        for name, _ in filtered_samples:
            cuisine_key = _cuisine_key(name)
            if max_per_cuisine > 0 and cuisine_counts[cuisine_key] >= max_per_cuisine:
                continue
            cuisine_counts[cuisine_key] += 1
            chosen_names.append(name)
            if len(chosen_names) == size:
                break
        if len(chosen_names) < size:
            # Fill remaining slots ignoring cuisine cap to ensure we always hit the target count
            for name, _ in filtered_samples:
                if name in chosen_names:
                    continue
                chosen_names.append(name)
                if len(chosen_names) == size:
                    break
        # print(samples[:size])
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
            raw_name = vr["name"] or ""
            if isinstance(raw_name, str):
                parts = raw_name.strip().split()
                display_name = parts[0] if parts else ""
            else:
                display_name = ""
            if not display_name:
                display_name = 'NA' # vr["email"]
            voters_by_option.setdefault(vr["option_id"], []).append(
                {"email": vr["email"], "name": display_name, "picture": vr["picture"]}
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
    """Voting is open from Sunday 09:00 to Tuesday 21:00 of the current selection week."""
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
        if isinstance(name, str):
            parts = name.strip().split()
            name = parts[0] if parts else None  # Only persist first name going forward
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

    print(f"\n Just Thompson samples: {samples[:WEEKLY_SELECTION_SIZE]}")
    # print(update_mab_stats())

    print(get_current_week_selection())
