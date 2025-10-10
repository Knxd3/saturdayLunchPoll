from .db import get_db_connection
import pandas as pd

def update_restaurants():
    df = pd.DataFrame(scrape_restaurants(num_pages=7))
    df["reviews"] = "Reviews: " + df["reviews"].str.extract(r"\((\d+)\)")[0]
    conn = get_db_connection()
    # df.to_sql("restaurants", conn, if_exists="replace", index=False)

    cur = conn.cursor()
    # cur.execute("""
    #             DROP TABLE restaurants
    #             """)
    # conn.commit()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS restaurants (
        name TEXT UNIQUE,
        address TEXT,
        cuisine TEXT,
        average_price TEXT,
        rating TEXT,
        reviews TEXT,
        offer TEXT,
        url TEXT
    )
    """)
    # Upsert (replace on name conflict)
    for _, row in df.iterrows():
        cur.execute("""
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
        """, (
            row.get("name"),
            row.get("address"),
            row.get("cuisine"),
            row.get("average_price"),
            row.get("rating"),
            row.get("reviews"),
            row.get("offer"),
            row.get("url"),
        ))

    conn.commit()
    conn.close()


if __name__ == "__main__":
    update_restaurants()