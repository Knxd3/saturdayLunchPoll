import pandas as pd
from .db import get_db_connection
import sqlite3

conn = get_db_connection()
query = """
SELECT 
    r.name,
    r.address,
    r.cuisine,
    r.average_price,
    r.rating,
    r.reviews,
    r.offer,
    r.url,
    IFNULL(w.total_votes, 0) AS total_votes
FROM restaurants AS r
LEFT JOIN (
    SELECT name, SUM(votes) AS total_votes
    FROM weekly_results
    GROUP BY name
) AS w
ON r.name = w.name
"""

df = pd.read_sql_query(query, conn)
print(df.sort_values('total_votes', ascending=0))
conn.close()