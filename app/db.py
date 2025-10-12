"""
Database utilities.
"""
import os
import sqlite3

DB_PATH = os.environ.get("DB_PATH", "database.db")


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # NOTE: The restaurants table may be created via pandas to_sql in seed_db.
    # We don't enforce a schema here to avoid clashing with to_sql(replace).

    # Store the 7 options for the current week. We keep one batch marked by created_at.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS weekly_selection (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            address TEXT,
            cuisine TEXT,
            average_price TEXT,
            rating TEXT,
            reviews TEXT,
            offer TEXT,
            url TEXT,
            votes INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )

    # Historical record of weekly selection and votes
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS weekly_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            address TEXT,
            cuisine TEXT,
            average_price TEXT,
            rating TEXT,
            reviews TEXT,
            offer TEXT,
            url TEXT,
            is_excluded INTEGER NOT NULL DEFAULT 0,
            votes INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL UNIQUE
        )
        """
    )

    # No backfills: assume fresh DB with latest schema

    # Voter log: track one vote per week per voter (cookie/email) and per IP hash
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS voter_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_created_at TEXT NOT NULL,
            voter_id TEXT NOT NULL,
            ip_hash TEXT NOT NULL,
            user_agent TEXT,
            email TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_voter_unique_cookie ON voter_log(week_created_at, voter_id)"
    )
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_voter_unique_ip ON voter_log(week_created_at, ip_hash)"
    )

    conn.commit()
    # Normalized per-vote table: one row per user per option per week
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_created_at TEXT NOT NULL,
            option_id INTEGER NOT NULL,
            email TEXT NOT NULL,
            name TEXT,
            picture TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_vote_unique ON votes(week_created_at, option_id, email)"
    )
    conn.commit()
    conn.close()
