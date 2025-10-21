from .scraper import scrape_restaurants
from .db import get_db_connection
import pandas as pd


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
    df = pd.DataFrame(scrape_restaurants())
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
