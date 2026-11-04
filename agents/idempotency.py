import sqlite3, os, uuid
from database import db as _db

def _conn():
    return sqlite3.connect(_db.DB_PATH, timeout=30)

def stable_key(app_id, job_id):
    return "app:%s:job:%s" % (app_id, job_id)

def create_attempt(app_id, job_id, stage):
    key = stable_key(app_id, job_id)
    conn = _conn()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO submission_attempts (application_id, idempotency_key, state, outcome, attempt_id, created_at) VALUES (?,?,?,?,?,datetime('now'))", (app_id, key, stage, "PENDING", str(uuid.uuid4())))
        conn.commit()
        return True, key
    except sqlite3.IntegrityError:
        return False, key
    finally:
        conn.close()
