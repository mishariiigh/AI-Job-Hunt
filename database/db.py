import sqlite3
import os


DB_PATH = os.path.join(os.path.dirname(__file__), "app.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


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
            approved INTEGER
        )
    """)
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
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print("DB initialized")
