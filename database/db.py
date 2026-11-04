import sqlite3
import os


DB_PATH = os.path.join(os.path.dirname(__file__), "app.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_job_columns(conn):
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
    migrations = {
        "job_category": "TEXT NOT NULL DEFAULT ''",
        "source_feed": "TEXT NOT NULL DEFAULT ''",
        "source_updated_at": "TEXT",
        "last_verified_at": "TEXT",
        "listing_status": "TEXT NOT NULL DEFAULT 'unknown'",
        "schedule_classification": "TEXT NOT NULL DEFAULT '{}'",
        "repost_group_key": "TEXT NOT NULL DEFAULT ''",
    }
    added = set()
    for name, declaration in migrations.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {declaration}")
            added.add(name)

    if "last_verified_at" in added:
        conn.execute(
            """
            UPDATE jobs
            SET last_verified_at = discovered_at
            WHERE source IN ('greenhouse', 'lever', 'remotive')
            """
        )
    if "listing_status" in added:
        conn.execute(
            """
            UPDATE jobs
            SET listing_status = 'active_on_source'
            WHERE source IN ('greenhouse', 'lever')
            """
        )
    if "source_feed" in added:
        conn.execute(
            """
            UPDATE jobs
            SET source_feed = lower(trim(employer))
            WHERE source IN ('greenhouse', 'lever')
            """
        )


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employer TEXT,
            job_title TEXT,
            job_url TEXT UNIQUE,
            source TEXT,
            description TEXT,
            location TEXT,
            remote INTEGER,
            salary TEXT,
            shift TEXT,
            employment_type TEXT,
            experience_required TEXT,
            education_required TEXT,
            posting_date TEXT,
            deadline TEXT,
            discovered_at TEXT,
            match_score REAL,
            match_explanation TEXT,
            status TEXT,
            approved INTEGER,
            job_category TEXT NOT NULL DEFAULT '',
            source_feed TEXT NOT NULL DEFAULT '',
            source_updated_at TEXT,
            last_verified_at TEXT,
            listing_status TEXT NOT NULL DEFAULT 'unknown',
            schedule_classification TEXT NOT NULL DEFAULT '{}',
            repost_group_key TEXT NOT NULL DEFAULT ''
        )
    """)
    ensure_job_columns(conn)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER,
            resume_filename TEXT,
            cover_letter_filename TEXT,
            answers TEXT,
            applied_at TEXT,
            status TEXT,
            interview_status TEXT,
            notes TEXT,
            FOREIGN KEY(job_id) REFERENCES jobs(id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS candidate (
            id INTEGER PRIMARY KEY,
            name TEXT,
            email TEXT,
            phone TEXT,
            address TEXT,
            resume_path TEXT,
            profile_json TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER UNIQUE,
            match_score REAL,
            match_category TEXT,
            hard_disqualifiers TEXT,
            required_matched TEXT,
            missing_qualifications TEXT,
            explanation TEXT,
            ai_used INTEGER,
            calculated_at TEXT,
            FOREIGN KEY(job_id) REFERENCES jobs(id)
        )
    """)
    # backward-compatible migration: add resume_id column
    try:
        cur.execute("ALTER TABLE applications ADD COLUMN resume_id TEXT")
        conn.commit()
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE applications ADD COLUMN cover_letter TEXT")
        conn.commit()
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE ai_analysis ADD COLUMN cache_key TEXT")
        conn.commit()
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE jobbank_imports ADD COLUMN record_hash TEXT")
        conn.commit()
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE jobbank_imports ADD COLUMN dataset_publication_date TEXT")
        conn.commit()
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE jobbank_imports ADD COLUMN original_filename TEXT")
        conn.commit()
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE applications ADD COLUMN submission_state TEXT")
        conn.commit()
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE applications ADD COLUMN idempotency_key TEXT")
        conn.commit()
    except Exception:
        pass
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER UNIQUE,
            cache_key TEXT,
            compatibility_score REAL,
            assessment TEXT,
            missing TEXT,
            concerns TEXT,
            explanation TEXT,
            analyzed_at TEXT,
            FOREIGN KEY(job_id) REFERENCES jobs(id)
        )
    """)
    conn.commit()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS jobbank_imports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            location TEXT,
            noc TEXT,
            record_hash TEXT UNIQUE,
            imported_at TEXT,
            dataset_month TEXT,
            dataset_publication_date TEXT,
            original_filename TEXT
        )
    """)
    conn.commit()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS submission_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id INTEGER,
            idempotency_key TEXT UNIQUE,
            state TEXT,
            outcome TEXT,
            error_category TEXT,
            attempt_id TEXT,
            created_at TEXT,
            FOREIGN KEY(application_id) REFERENCES applications(id)
        )
    """)
    conn.commit()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id INTEGER,
            employer TEXT,
            job_identifier TEXT,
            from_state TEXT,
            to_state TEXT,
            timestamp TEXT,
            attempt_id TEXT,
            outcome TEXT,
            error_category TEXT,
            confirmation_ref TEXT
        )
    """)
    conn.commit()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS submission_locks (
            lock_key TEXT PRIMARY KEY,
            owner TEXT,
            acquired_at TEXT,
            expires_at TEXT
        )
    """)
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print("DB initialized")
