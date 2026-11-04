import sqlite3, datetime
from database import db as _db

def _conn():
    return sqlite3.connect(_db.DB_PATH, timeout=30)

def _now():
    return datetime.datetime.utcnow()

def release(key, owner):
    conn = _conn()
    cur = conn.cursor()
    sql = "DELETE FROM submission_locks WHERE lock_key=? AND owner=?"
    cur.execute(sql, (key, owner))
    conn.commit()
    n = cur.rowcount
    conn.close()
    return n > 0

def is_locked(key):
    conn = _conn()
    cur = conn.cursor()
    sql = "SELECT expires_at FROM submission_locks WHERE lock_key=?"
    cur.execute(sql, (key,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return False
    return datetime.datetime.fromisoformat(row[0].replace("Z", "")) > _now()

def acquire(key, owner=None, ttl_seconds=300):
    import uuid
    owner = owner or str(uuid.uuid4())
    now = _now()
    conn = _conn()
    cur = conn.cursor()
    sql = 'INSERT INTO submission_locks (lock_key, owner, acquired_at, expires_at) VALUES (?,?,?,?)'
    try:
        cur.execute(sql, (key, owner, now.isoformat() + 'Z', now.isoformat() + 'Z'))
        conn.commit()
        conn.close()
        return True, owner
    except Exception:
        cur.execute('SELECT owner FROM submission_locks WHERE lock_key=?', (key,))
        row = cur.fetchone()
        conn.close()
        return False, row[0] if row else None
