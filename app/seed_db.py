from datetime import timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pandas as pd

from .scraper import scrape_restaurants
from .db import get_db_connection
from .timeutil import now_london, week_monday_london


def seed_restaurants():
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
    # Drop entries missing a name or that duplicate an existing name
    if "name" in df.columns:
        df = df.dropna(subset=["name"])
        df = df.drop_duplicates(subset=["name"])
    # Ensure numeric dtypes where appropriate
    for col, as_float in [("rating", True), ("reviews", False), ("average_price", False), ("offer", False)]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            if not as_float:
                df[col] = df[col].astype("Int64")
    # Optionally filter
    # df = df.loc[(df.offer > 20) | ((df.rating > 9.0) & (df.reviews > 10)), :]
    # df = df.loc[df.reviews > 0, :]
    # df = df.loc[df.offer > 30, :]
    # t = df.groupby('offer').agg({'average_price': 'mean', 'name': 'count'})
    # print(t)
    print(f"Count: {df.shape}")
    # Add exclusion flag defaulting to 0 (not excluded)
    if "is_excluded" not in df.columns:
        df["is_excluded"] = 0
    conn = get_db_connection()
    df.to_sql("restaurants", conn, if_exists="replace", index=False)
    # Ensure future upserts can rely on a unique name constraint
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_restaurants_name ON restaurants(name)")
    conn.close()

if __name__ == "__main__":
    seed_restaurants()
