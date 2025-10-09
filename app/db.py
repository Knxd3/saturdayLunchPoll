"""
Database placeholder.
"""
import sqlite3

def get_db_connection():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    # Placeholder for initializing DB schema
    pass