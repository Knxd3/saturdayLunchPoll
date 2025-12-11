from datetime import timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pandas as pd

from .scraper import scrape_restaurants
from .db import get_db_connection
from .timeutil import now_london, week_monday_london


def _coerce_value(val):
    if pd.isna(val):
        return None
    if hasattr(val, "item"):
        try:
            return val.item()
        except Exception:
            pass
    return val


def update_restaurants():
    week_monday = week_monday_london(now_london())
    saturday = (week_monday + timedelta(days=5)).date().isoformat()
    base_url = (
        "https://www.thefork.co.uk/search?coordinates=51.50583%2C-0.139401&date=2025-12-13"
        "&hour=780&p=1&partySize=8&promotionOnly=true&radius=5.994615908"
    )
    urls = []
    for page in (1, 2, 3):
        parts = urlsplit(base_url)
        pairs = parse_qsl(parts.query, keep_blank_values=True)
        replaced_date = False
        replaced_page = False
        out_pairs = []
        for k, v in pairs:
            if k == "date":
                v = saturday
                replaced_date = True
            if k == "p":
                v = str(page)
                replaced_page = True
            out_pairs.append((k, v))
        if not replaced_date:
            out_pairs.append(("date", saturday))
        if not replaced_page:
            out_pairs.append(("p", str(page)))
        new_query = urlencode(out_pairs)
        urls.append(urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment)))

    df = pd.DataFrame(scrape_restaurants(urls))
    # Ensure numeric dtypes where appropriate
    for col, as_float in [("rating", True), ("reviews", False), ("average_price", False), ("offer", False)]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            if not as_float:
                df[col] = df[col].astype("Int64")
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS restaurants (
        name TEXT UNIQUE,
        address TEXT,
        cuisine TEXT,
        average_price INTEGER,
        rating REAL,
        reviews INTEGER,
        offer INTEGER,
        url TEXT
    )
    """
    )
    # Upsert (replace on name conflict)
    for _, row in df.iterrows():
        values = tuple(
            _coerce_value(row.get(col))
            for col in (
                "name",
                "address",
                "cuisine",
                "average_price",
                "rating",
                "reviews",
                "offer",
                "url",
            )
        )
        cur.execute(
            """
        INSERT INTO restaurants (name, address, cuisine, average_price, rating, reviews, offer, url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            address=excluded.address,
            cuisine=excluded.cuisine,
            average_price=excluded.average_price,
            rating=excluded.rating,
            reviews=excluded.reviews,
            offer=excluded.offer,
            url=excluded.url
        """,
            values,
        )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    update_restaurants()
