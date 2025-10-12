
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
