import sqlite3, datetime
from database import db as _db

def _conn():
    return sqlite3.connect(_db.DB_PATH, timeout=30)

def recover():
    conn = _conn()
    cur = conn.cursor()
    cur.execute("UPDATE submission_attempts SET outcome='UNKNOWN' WHERE state='SUBMITTING' AND outcome='PENDING'")
    conn.commit()
    now = datetime.datetime.utcnow().isoformat() + "Z"
    cur.execute("DELETE FROM submission_locks WHERE expires_at < ?", (now,))
    conn.commit()
    conn.close()
