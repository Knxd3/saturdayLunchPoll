from .scraper import scrape_restaurants
from .db import get_db_connection
import pandas as pd

def seed_restaurants():
    df = pd.DataFrame(scrape_restaurants(num_pages=7))
    df["reviews"] = df["reviews"].str.extract(r"\((\d+)\)").astype(float)
    conn = get_db_connection()
    df.to_sql("restaurants", conn, if_exists="replace", index=False)
    conn.close()

if __name__ == "__main__":
    seed_restaurants()