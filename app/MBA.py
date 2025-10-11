import pandas as pd
from .db import get_db_connection
import sqlite3

conn = get_db_connection()
conn.close()