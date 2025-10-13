from .scraper import scrape_restaurants
from .db import get_db_connection
import pandas as pd


def seed_restaurants():
    df = pd.DataFrame(scrape_restaurants())
    # Ensure numeric dtypes where appropriate
    for col, as_float in [("rating", True), ("reviews", False), ("average_price", False), ("offer", False)]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            if not as_float:
                df[col] = df[col].astype("Int64")
    # Add exclusion flag defaulting to 0 (not excluded)
    if "is_excluded" not in df.columns:
        df["is_excluded"] = 0
    conn = get_db_connection()
    df.to_sql("restaurants", conn, if_exists="replace", index=False)
    conn.close()

if __name__ == "__main__":
    seed_restaurants()
