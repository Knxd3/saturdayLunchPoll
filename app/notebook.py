
#%%
import sqlite3
import numpy as np
import pandas as pd
import os

os.getcwd()
con = sqlite3.connect("c:\\Users\\alexa\\Documents\\Personal\\Projects\\saturdayLunchPoll\\database.db")
# pd.read_sql("SELECT * FROM votes", con)

# pd.read_sql("SELECT * FROM weekly_selection a LEFT JOIN votes b ON a.created_at = b.week_created_at AND (a.id-1) = b.option_id", con)

# weekly restaurant votes
# pd.read_sql("""
#             SELECT name, 
#             SUM(CASE WHEN created_at IS NOT NULL THEN 1 ELSE 0 END) AS votes
#             FROM weekly_selection a 
#             LEFT JOIN votes b 
#             ON a.created_at = b.week_created_at AND (a.id-1) = b.option_id
#             GROUP BY a.name, a.created_at
#             """)


# Weekly successes and failures for each restaurant
# Note - failures is total voters - successes; thus has to be computed weekly

# pd.read_sql("""
#             SELECT COALESCE(created_at, '2025-10-01T00:00:00') AS week_created_at
#              ,r.name
#              ,COALESCE(ws.votes, 0) as s
#              FROM weekly_selection ws
#              FULL JOIN restaurants r 
#             ON ws.name = r.name
#            """, con)

# import pandas as pd
# from .db import get_db_connection
# import sqlite3

# conn = get_db_connection()



# plan
# create 
def posterior_mean(s, f, prior_s, prior_f):
    return ((prior_s + s) / (prior_s + s + prior_f + f))

data = pd.read_sql("""
            WITH weekly_unique_voters AS 
            (
            SELECT week_created_at,
            COUNT(DISTINCT(email)) as n
            FROM votes
            GROUP BY week_created_at
            ),
            weekly_votes AS 
            (
            SELECT COALESCE(created_at, '2025-10-01T00:00:00') AS week_created_at
             ,r.name
             ,COALESCE(ws.votes, 0) as s
             FROM weekly_selection ws -- make sure to run AFTER voting ends for a week
             FULL JOIN restaurants r 
            ON ws.name = r.name
            ),
            step1 AS
            (
            SELECT 
            a.week_created_at
            ,a.name
            ,a.s
            ,COALESCE(b.n, 0) AS n
            ,COALESCE(b.n, 0) - a.s as f
            ,SUM(a.s) OVER (PARTITION BY a.name ORDER BY a.week_created_at) AS sum_s
            ,SUM(b.n - a.s) OVER (PARTITION BY a.name ORDER BY a.week_created_at) AS sum_f
            FROM weekly_votes a 
            LEFT JOIN weekly_unique_voters b
            ON a.week_created_at = b.week_created_at
            )
            SELECT *
            ,COALESCE(LAG(sum_s) OVER (PARTITION BY name ORDER BY week_created_at), 1) AS prior_s
            ,COALESCE(LAG(sum_f) OVER (PARTITION BY name ORDER BY week_created_at), 1) AS prior_f
            FROM step1   
            """, con)


data['posterior_mean'] = data.apply(lambda row: posterior_mean(s = row['s'], f = row['f'], prior_s = row['prior_s'], prior_f = row['prior_f']), axis = 1)
data['beta'] = data.apply(lambda row: np.random.beta(row['s'] + row['prior_s'], row['f'] + row['prior_f']), axis = 1)
data

# %%
import sqlite3
import numpy as np
import pandas as pd
import os

os.getcwd()
con = sqlite3.connect("c:\\Users\\alexa\\Documents\\Personal\\Projects\\saturdayLunchPoll\\database.db")
data2 = pd.read_sql("""
        WITH recent AS (
            SELECT name, votes, created_at
            FROM weekly_results
            --WHERE created_at >= ?
        ),
        max_per_week AS (
            SELECT created_at, MAX(votes) AS max_votes
            FROM recent
            GROUP BY created_at
        ),
        wins AS (
            SELECT r.name, COUNT(*) AS win_count
            FROM recent r
            JOIN max_per_week m
              ON r.created_at = m.created_at AND r.votes = m.max_votes
            GROUP BY r.name
        ),
        appear AS (
            SELECT name, COUNT(*) AS app_count
            FROM recent
            GROUP BY name
        )
        SELECT a.name,
               COALESCE(w.win_count, 0) AS wins,
               a.app_count AS appearances
        FROM appear a
        LEFT JOIN wins w ON w.name = a.name
        """, con)

data2
# %%


# %%
import sqlite3
import numpy as np
import pandas as pd
import os

os.getcwd()
con = sqlite3.connect("c:\\Users\\alexa\\Documents\\Personal\\Projects\\saturdayLunchPoll\\database.db")
pd.read_sql("SELECT * FROM mab_stats ORDER BY name", con)






# %%
import sqlite3
import numpy as np
import pandas as pd
import os

os.getcwd()
con = sqlite3.connect("c:\\Users\\alexa\\Documents\\Personal\\Projects\\saturdayLunchPoll\\database.db")
con.row_factory = sqlite3.Row
cur = con.cursor()


cur.execute("DELETE FROM weekly_results")

cur.execute(
        """
        CREATE TABLE IF NOT EXISTS weekly_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            address TEXT,
            cuisine TEXT,
            average_price TEXT,
            rating TEXT,
            reviews TEXT,
            offer TEXT,
            url TEXT,
            is_excluded INTEGER NOT NULL DEFAULT 0,
            votes INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
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
                    r["created_at"] if "created_at" in r.keys() else None
                ),
            )
con.commit()
# con.close()

# stats_rows = cur.execute(
#         """
#         WITH recent AS (
#             SELECT name, votes, created_at
#             FROM weekly_results
#             WHERE COALESCE(is_excluded, 0) = 0 --AND created_at >= ? -- implement decay instead
#         ),
#         totals_per_week AS (
#             SELECT created_at, SUM(votes) AS total_votes
#             FROM recent
#             GROUP BY created_at
#         ),
#         per_name_week AS (
#             SELECT r.name,
#                    r.votes AS votes_for,
#                    t.total_votes,
#                    r.created_at
#             FROM recent r
#             JOIN totals_per_week t USING (created_at)
#         ),
#         max_per_week AS (
#             SELECT created_at, MAX(votes) AS max_votes
#             FROM recent
#             GROUP BY created_at
#         ),
#         wins AS (
#             SELECT r.name, COUNT(*) AS win_count
#             FROM recent r
#             JOIN max_per_week m
#               ON r.created_at = m.created_at AND r.votes = m.max_votes
#             GROUP BY r.name
#         ),
#         appear AS (
#             SELECT name, COUNT(*) AS app_count
#             FROM recent
#             GROUP BY name
#         ),
#         agg AS (
#             SELECT name,
#                    SUM(votes_for) AS votes_for_sum,
#                    SUM(total_votes) AS total_votes_sum
#             FROM per_name_week
#             GROUP BY name
#         )
#         SELECT a.name,
#                COALESCE(w.win_count, 0) AS wins,
#                a.app_count AS appearances,
#                COALESCE(g.votes_for_sum, 0) AS votes_for_sum,
#                COALESCE(g.total_votes_sum, 0) AS total_votes_sum
#         FROM appear a
#         LEFT JOIN wins w ON w.name = a.name
#         LEFT JOIN agg g ON g.name = a.name
#         """,
#     ).fetchall()

# hist_map = {}
# for r in stats_rows:
#         hist_map[r["name"]] = {
#             "wins": int(r["wins"]),
#             "appearances": int(r["appearances"]),
#             "votes_for_sum": int(r["votes_for_sum"]),
#             "total_votes_sum": int(r["total_votes_sum"]),
#         }

# hist_map

# for r in stats_rows:
#       print(r['created_at'])







pd.read_sql("""
        WITH recent AS (
            SELECT name, votes, created_at
            FROM weekly_results
            WHERE COALESCE(is_excluded, 0) = 0 --AND created_at >= ? -- implement decay instead
        ),
        totals_per_week AS (
            SELECT created_at, SUM(votes) AS total_votes
            FROM recent
            GROUP BY created_at
        ),
        per_name_week AS (
            SELECT r.name,
                   r.votes AS votes_for,
                   t.total_votes,
                   r.created_at
            FROM recent r
            JOIN totals_per_week t USING (created_at)
        ),
        max_per_week AS (
            SELECT created_at, MAX(votes) AS max_votes
            FROM recent
            GROUP BY created_at
        ),
        wins AS (
            SELECT r.name, COUNT(*) AS win_count
            FROM recent r
            JOIN max_per_week m
              ON r.created_at = m.created_at AND r.votes = m.max_votes
            GROUP BY r.name
        ),
        appear AS (
            SELECT name, COUNT(*) AS app_count
            FROM recent
            GROUP BY name
        ),
        agg AS (
            SELECT name,
                   SUM(votes_for) AS votes_for_sum,
                   SUM(total_votes) AS total_votes_sum
            FROM per_name_week
            GROUP BY name
        )
        SELECT a.name,
               COALESCE(w.win_count, 0) AS wins,
               a.app_count AS appearances,
               COALESCE(g.votes_for_sum, 0) AS votes_for_sum,
               COALESCE(g.total_votes_sum, 0) AS total_votes_sum,
               MAX(g.wins)
        FROM appear a
        LEFT JOIN wins w ON w.name = a.name
        LEFT JOIN agg g ON g.name = a.name
        """, con)



from timeutil import week_monday_london, now_london
asof_iso = week_monday_london(now_london())

pd.read_sql("""
            WITH weekly_trials AS (
            SELECT week_created_at,
            COUNT(DISTINCT(email)) AS trials
            FROM votes
            GROUP BY week_created_at
            )
            SELECT
            wr.created_at AS week_created_at,
            wr.name,
            wr.votes,
            wt.trials,
            CAST((julianday(:asof_iso) - julianday(wr.created_at)) / 7.0 AS INTEGER) AS weeks_ago
            FROM weekly_results wr
            LEFT JOIN weekly_trials wt
            ON wr.created_at = wt.week_created_at

            """, con)


pd.read_sql("SELECT * FROM voter_log", con)


pd.read_sql("SELECT * FROM weekly_selection", con)
pd.read_sql("SELECT * FROM weekly_results", con)
pd.read_sql("SELECT * FROM votes", con)


pd.read_sql("""SELECT week_created_at,
            COUNT(DISTINCT(email)) AS trials
            FROM votes
            GROUP BY week_created_at""", con)

pd.read_sql(""" SELECT name,
            votes,
            created_at
            FROM weekly_results""", con)



# 1) Materialize weekly rows (no cutoff)
sql = """
WITH weekly_trials AS (
  SELECT week_created_at, COUNT(DISTINCT email) AS trials
  FROM votes
  GROUP BY week_created_at
)
SELECT
  wr.created_at AS week_created_at,
  wr.name,
  wr.votes,
  wt.trials
FROM weekly_results wr
LEFT JOIN weekly_trials wt
  ON wr.created_at = wt.week_created_at
WHERE COALESCE(wr.is_excluded, 0) = 0
"""

df = pd.read_sql(sql, con)
df

# 2) Compute weeks_ago relative to the current London Monday
from timeutil import now_london, week_monday_london
asof_monday = week_monday_london(now_london())

# Ensure tz-aware timestamps
df['week_created_at'] = pd.to_datetime(df['week_created_at'], utc=True, errors='coerce')

weeks_ago = np.floor((asof_monday - df['week_created_at']).dt.total_seconds() / (7*24*3600)).astype('Int64')
weeks_ago = weeks_ago.clip(lower=0)  # guard negatives if any future stamps
df['weeks_ago'] = weeks_ago.astype(int)

df

# 3) Decay weights and decayed successes/trials
H = 26  # half-life in weeks (tune 13–26)
gamma = 0.5 ** (1.0 / H)
w = np.power(gamma, df['weeks_ago'].to_numpy())

# Fill any missing trials with the week’s total votes as a fallback
df['trials'] = df['trials'].fillna(df.groupby('week_created_at')['votes'].transform('sum'))


df['s_decayed'] = df['votes'].astype(float) * w
df['n_decayed'] = df['trials'].astype(float) * w

df

# 4) Aggregate per restaurant
agg = df.groupby('name', as_index=False).agg(
    s=('s_decayed', 'sum'),
    n=('n_decayed', 'sum'),
)
agg['f'] = agg['n'] - agg['s']

agg

# 5) Posterior parameters
from scipy.stats import beta 
alpha0, beta0 = 1.0, 1.0  # or Jeffreys 0.5,0.5; or EB prior
agg['alpha'] = alpha0 + agg['s']
agg['beta']  = beta0  + (agg['n'] - agg['s'])

# Optional: mean and 95% credible interval
agg['mean']  = agg['alpha'] / (agg['alpha'] + agg['beta'])
try:
    agg['lower'] = beta.ppf(0.025, agg['alpha'], agg['beta'])
    agg['upper'] = beta.ppf(0.975, agg['alpha'], agg['beta'])
except Exception:
    pass  # if scipy is unavailable, skip or add a normal approximation

agg

posteriors = agg[['name', 'alpha', 'beta', 'mean'] + ([ 'lower','upper'] if 'lower' in agg else [])]



cur.execute("DROP TABLE mab_stats")



# %%
# drop the tables and test synthetic data
import sqlite3
import numpy as np
import pandas as pd
import os

os.getcwd()
con = sqlite3.connect("c:\\Users\\alexa\\Documents\\Personal\\Projects\\saturdayLunchPoll\\database.db")

con.execute("DROP TABLE mab_stats")
con.execute("DROP TABLE weekly_selection")
con.execute("DROP TABLE voter_log")
con.execute("DROP TABLE weekly_results")
con.execute("DROP TABLE votes")




# %%
import sqlite3
import numpy as np
import pandas as pd
import os

os.getcwd()
con = sqlite3.connect("c:\\Users\\alexa\\Documents\\Personal\\Projects\\saturdayLunchPoll\\database.db")
# pd.read_sql("SELECT * FROM weekly_selection", con)
# pd.read_sql("SELECT * FROM weekly_results", con)
# pd.read_sql("SELECT * FROM votes", con)


pd.read_sql("SELECT * FROM weekly_results WHERE votes = (SELECT MAX(votes) FROM weekly_results)", con)




# %%
# drop the tables and test synthetic data
import sqlite3
import numpy as np
import pandas as pd
import os

os.getcwd()
con = sqlite3.connect("c:\\Users\\alexa\\Documents\\Personal\\Projects\\saturdayLunchPoll\\database.db")
# pd.read_sql("SELECT * FROM weekly_selection", con)
# pd.read_sql("SELECT * FROM weekly_results", con)
# pd.read_sql("SELECT * FROM votes", con)

rows = [
    # Week 1 — 2025-08-06
    ("2025-08-06T09:00:00+01:00", 2, "jane.doe@example.com",  "Jane Doe",  "https://lh3.googleusercontent.com/a/AAJANE",  "2025-08-06T09:05:12+01:00"),
    ("2025-08-06T09:00:00+01:00", 5, "john.smith@example.com","John Smith","https://lh3.googleusercontent.com/a/AAJOHN",  "2025-08-06T09:06:44+01:00"),
    ("2025-08-06T09:00:00+01:00", 3, "priya.k@example.com",   "Priya K",   "https://lh3.googleusercontent.com/a/AAPRIYA", "2025-08-06T09:08:01+01:00"),
    ("2025-08-06T09:00:00+01:00", 7, "marco.r@example.com",   "Marco R",   "https://lh3.googleusercontent.com/a/AAMARCO", "2025-08-06T09:10:29+01:00"),

    # Week 2 — 2025-10-13 (includes your Aleb example)
    ("2025-10-13T21:19:09+01:00", 3, "driciale6@gmail.com",   "Aleb",      "https://lh3.googleusercontent.com/a/ACocIU77...", "2025-10-13T21:28:39+01:00"),
    ("2025-10-13T21:19:09+01:00", 1, "jane.doe@example.com",  "Jane Doe",  "https://lh3.googleusercontent.com/a/AAJANE",      "2025-10-13T21:30:02+01:00"),
    ("2025-10-13T21:19:09+01:00", 4, "john.smith@example.com","John Smith","https://lh3.googleusercontent.com/a/AAJOHN",      "2025-10-13T21:31:47+01:00"),
    ("2025-10-13T21:19:09+01:00", 6, "lina.w@example.com",    "Lina W",    "https://lh3.googleusercontent.com/a/AALINA",      "2025-10-13T21:33:10+01:00"),
    ("2025-10-13T21:19:09+01:00", 2, "priya.k@example.com",   "Priya K",   "https://lh3.googleusercontent.com/a/AAPRIYA",     "2025-10-13T21:34:55+01:00"),

    # Week 3 — 2025-10-20
    ("2025-10-20T08:30:00+01:00", 2, "zoe.t@example.com",     "Zoe T",     "https://lh3.googleusercontent.com/a/AAZOE",       "2025-10-20T08:31:12+01:00"),
    ("2025-10-20T08:30:00+01:00", 3, "jane.doe@example.com",  "Jane Doe",  "https://lh3.googleusercontent.com/a/AAJANE",      "2025-10-20T08:32:21+01:00"),
    ("2025-10-20T08:30:00+01:00", 1, "john.smith@example.com","John Smith","https://lh3.googleusercontent.com/a/AAJOHN",      "2025-10-20T08:33:03+01:00"),
    ("2025-10-20T08:30:00+01:00", 7, "marco.r@example.com",   "Marco R",   "https://lh3.googleusercontent.com/a/AAMARCO",     "2025-10-20T08:34:45+01:00"),
    ("2025-10-20T08:30:00+01:00", 5, "lina.w@example.com",    "Lina W",    "https://lh3.googleusercontent.com/a/AALINA",      "2025-10-20T08:36:18+01:00"),
]

con.executemany(
    """
    INSERT OR IGNORE INTO votes
        (week_created_at, option_id, email, name, picture, created_at)
    VALUES (?, ?, ?, ?, ?, ?)
    """,
    rows,
)
con.commit()

# Optional: preview what got inserted
for row in con.execute("""
    SELECT id, week_created_at, option_id, email, name, picture, created_at
    FROM votes
    ORDER BY week_created_at, created_at
    LIMIT 50
"""):
    print(tuple(row))




# Map option_id to a consistent restaurant profile
restaurants = {
    1: {
        "name": "Sushi Zen",
        "address": "123 Ocean Ave",
        "cuisine": "Japanese",
        "average_price": "£££",
        "rating": "4.6",
        "reviews": "210",
        "offer": "Free miso soup",
        "url": "https://example.com/sushizen",
    },
    2: {
        "name": "Pasta Piazza",
        "address": "45 Market St",
        "cuisine": "Italian",
        "average_price": "££",
        "rating": "4.2",
        "reviews": "380",
        "offer": "Lunch set £9.95",
        "url": "https://example.com/pastapiazza",
    },
    3: {
        "name": "Curry House",
        "address": "78 Spice Rd",
        "cuisine": "Indian",
        "average_price": "££",
        "rating": "4.4",
        "reviews": "510",
        "offer": "2-for-1 curries",
        "url": "https://example.com/curryhouse",
    },
    4: {
        "name": "Burger Barn",
        "address": "9 Grill Lane",
        "cuisine": "American",
        "average_price": "££",
        "rating": "4.1",
        "reviews": "275",
        "offer": "Fries included",
        "url": "https://example.com/burgerbarn",
    },
    5: {
        "name": "Tapas 24",
        "address": "16 Rambla Pl",
        "cuisine": "Spanish",
        "average_price": "££",
        "rating": "4.3",
        "reviews": "330",
        "offer": "3 tapas £12",
        "url": "https://example.com/tapas24",
    },
    6: {
        "name": "Pho King",
        "address": "3 Lotus Ct",
        "cuisine": "Vietnamese",
        "average_price": "£",
        "rating": "4.5",
        "reviews": "190",
        "offer": "Pho + roll £10",
        "url": "https://example.com/phoking",
    },
    7: {
        "name": "Taco Loco",
        "address": "55 Cactus Way",
        "cuisine": "Mexican",
        "average_price": "£",
        "rating": "4.0",
        "reviews": "145",
        "offer": "Taco Tuesday",
        "url": "https://example.com/tacoloco",
    },
}

# Vote counts per week (consistent with the votes inserted earlier)
votes_by_week = {
    "2025-08-06T09:00:00+01:00": {2: 1, 5: 1, 3: 1, 7: 1},
    "2025-10-13T21:19:09+01:00": {3: 1, 1: 1, 4: 1, 6: 1, 2: 1},
    "2025-10-20T08:30:00+01:00": {2: 1, 3: 1, 1: 1, 7: 1, 5: 1},
}

rows = []
for week_created_at, counts in votes_by_week.items():
    for option_id in range(1, 8):
        r = restaurants[option_id]
        rows.append((
            r["name"],
            r["address"],
            r["cuisine"],
            r["average_price"],
            r["rating"],
            r["reviews"],
            r["offer"],
            r["url"],
            0,  # is_excluded
            counts.get(option_id, 0),  # votes for this restaurant in that week
            week_created_at,  # created_at matches votes.week_created_at
        ))

con.executemany(
    """
    INSERT INTO weekly_results
        (name, address, cuisine, average_price, rating, reviews, offer, url, is_excluded, votes, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    rows,
)
con.commit()

# Optional: preview
for row in con.execute("""
    SELECT id, name, votes, created_at
    FROM weekly_results
    ORDER BY created_at, votes DESC, name
    LIMIT 50
"""):
    print(tuple(row))
# %%

",".join(["?"] * len(['chosen_names', 'b']))

# %%

lo, hi = (1,5) if 1 else (2,4)

print(lo)

print(hi)


a = {}
a['a'] = 1
a['b'] = 4
a['c'] = 9

import numpy as np

np.array(list(a.values()))/ 14


# %%
import sqlite3
import numpy as np
import pandas as pd
import os

os.getcwd()
con = sqlite3.connect("c:\\Users\\alexa\\Documents\\Personal\\Projects\\saturdayLunchPoll\\database.db")
pd.read_sql("SELECT * FROM weekly_selection", con)
# pd.read_sql("SELECT * FROM weekly_results", con)
# pd.read_sql("SELECT * FROM votes", con)
# %%
import numpy as np
np.arange(0, 10+1)/10
# %%
