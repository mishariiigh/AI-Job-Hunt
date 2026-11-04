import sqlite3, datetime
from database import db as _db

def _conn():
    return sqlite3.connect(_db.DB_PATH, timeout=30)

def log_event(application_id, employer, job_identifier, from_state, to_state, attempt_id=None, outcome=None, error_category=None, confirmation_ref=None):
    conn = _conn()
    cur = conn.cursor()
    sql = "INSERT INTO audit_events (application_id, employer, job_identifier, from_state, to_state, timestamp, attempt_id, outcome, error_category, confirmation_ref) VALUES (?,?,?,?,?,?,?,?,?,?)"
    vals = (application_id, employer, job_identifier, from_state, to_state, datetime.datetime.utcnow().isoformat() + "Z", attempt_id, outcome, error_category, confirmation_ref)
    cur.execute(sql, vals)
    conn.commit()
    conn.close()
