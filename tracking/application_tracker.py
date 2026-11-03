from database.db import get_conn
from datetime import datetime
from urllib.parse import urlparse, urlunparse


class ApplicationTracker:
    def normalize_url(self, url):
        if not url:
            return ''
        try:
            parsed = urlparse(url.strip())
            # Remove fragments and common tracking params
            cleaned = parsed._replace(fragment='')
            return urlunparse(cleaned)
        except Exception:
            return url.strip() if url else ''
    
    PLACEHOLDER_DOMAINS = {'example.com','example.org','example.net','test.com','localhost'}
    PLACEHOLDER_EMPLOYERS = {'', 'test', 'example', 'placeholder', 'none', 'n/a'}
    PLACEHOLDER_TITLES = {'', 'test', 'example', 'placeholder', 'none', 'n/a'}

    def _valid_job(self, job_data):
        employer = (job_data.get('employer') or '').strip().lower()
        title = (job_data.get('job_title') or '').strip().lower()
        url = (job_data.get('job_url') or '').strip()
        source = (job_data.get('source') or '').strip().lower()
        if employer in self.PLACEHOLDER_EMPLOYERS:
            return False
        if title in self.PLACEHOLDER_TITLES:
            return False
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.scheme not in ('http','https') or not parsed.netloc:
            return False
        host = parsed.netloc.split(':')[0].lower()
        if host in self.PLACEHOLDER_DOMAINS or host.startswith('localhost'):
            return False
        if source == 'test':
            return False
        return True

    def set_application_resume(self, application_id, resume_id):
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE applications SET resume_id = ? WHERE id = ?", (resume_id, application_id))
        conn.commit()
        conn.close()
        return True

    def get_application(self, application_id):
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM applications WHERE id = ?", (application_id,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None


    def get_applications(self):
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM applications ORDER BY id DESC")
        rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]


    def set_cover_letter(self, application_id, content):
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE applications SET cover_letter = ? WHERE id = ?", (content, application_id))
        conn.commit()
        conn.close()
        return True

    def add_job(self, job_data):
        if not self._valid_job(job_data):
            return None
        conn = get_conn()
        cur = conn.cursor()
        job_url_norm = self.normalize_url(job_data.get('job_url', ''))
        if not job_url_norm:
            conn.close()
            return None
        try:
            cur.execute("""
                INSERT OR IGNORE INTO jobs 
                (employer, job_title, job_url, source, description, location, remote, salary, shift, 
                 employment_type, experience_required, education_required, posting_date, deadline, 
                 discovered_at, match_score, match_explanation, status, approved)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job_data.get('employer'), job_data.get('job_title'), job_url_norm,
                job_data.get('source'), job_data.get('description'), job_data.get('location'),
                1 if job_data.get('remote') else 0, job_data.get('salary'), job_data.get('shift', 'unknown'),
                job_data.get('employment_type'), job_data.get('experience_required'),
                job_data.get('education_required'), job_data.get('posting_date'),
                job_data.get('deadline'), datetime.now().isoformat(), job_data.get('match_score', 0),
                job_data.get('match_explanation', ''), job_data.get('status', 'discovered'),
                0
            ))
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()
    
    def get_jobs(self):
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM jobs ORDER BY discovered_at DESC")
        rows = cur.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def job_exists(self, job_url):
        job_url_norm = self.normalize_url(job_url)
        if not job_url_norm:
            return False
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT id FROM jobs WHERE job_url = ?", (job_url_norm,))
        row = cur.fetchone()
        conn.close()
        return row is not None


def ensure_schema():
    from database.db import get_conn
    conn = get_conn()
    cur = conn.cursor()
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
    conn.close()




ensure_schema()
