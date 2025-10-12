from .scraper import scrape_restaurants
from .db import get_db_connection
import pandas as pd

def seed_restaurants():
    df = pd.DataFrame(scrape_restaurants())
    df["reviews"] = "Reviews: " + df["reviews"].str.extract(r"\((\d+)\)")[0]
    # Add exclusion flag defaulting to 0 (not excluded)
    if "is_excluded" not in df.columns:
        df["is_excluded"] = 0
    conn = get_db_connection()
    df.to_sql("restaurants", conn, if_exists="replace", index=False)
    conn.close()

if __name__ == "__main__":
    seed_restaurants()
