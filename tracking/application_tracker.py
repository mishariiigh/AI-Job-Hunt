import hashlib
import json
import re
from collections import Counter
from database.db import ensure_job_columns, get_conn, init_db
from datetime import datetime
from urllib.parse import urlparse, urlunparse


class ApplicationTracker:
    def __init__(self):
        ensure_schema()

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

    @staticmethod
    def repost_group_key(job_data):
        parts = [
            re.sub(r"\s+", " ", str(job_data.get(key) or "").strip().lower())
            for key in ("employer", "job_title", "location")
        ]
        if not all(parts):
            return ""
        key = "|".join(parts)
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

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
        cur.execute("""
            SELECT a.*, j.job_title AS job_title, j.employer AS employer,
                   j.job_url AS job_url, j.location AS location,
                   j.remote AS remote, j.description AS job_description,
                   j.salary AS salary, j.employment_type AS employment_type,
                   j.shift AS shift, j.match_score AS match_score,
                   j.match_explanation AS match_explanation
            FROM applications a
            LEFT JOIN jobs j ON j.id = a.job_id
            WHERE a.id = ?
        """, (application_id,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_job(self, job_id):
        conn = get_conn()
        try:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def create_application_draft(self, job_id, draft, allow_new_version=False):
        conn = get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            job = conn.execute("SELECT id FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not job:
                raise ValueError(f"Job {job_id} does not exist")
            existing = conn.execute(
                "SELECT id, version_number FROM applications WHERE job_id = ? ORDER BY version_number DESC, id DESC LIMIT 1",
                (job_id,),
            ).fetchone()
            if existing and not allow_new_version:
                conn.commit()
                return existing["id"], False
            version = int(existing["version_number"] or 1) + 1 if existing else 1
            cursor = conn.execute(
                """
                INSERT INTO applications (
                    job_id, resume_filename, cover_letter_filename, answers,
                    status, interview_status, notes, resume_id, cover_letter,
                    submission_state, version_number, resume_version,
                    tailored_resume, additional_questions, eligibility_status,
                    eligibility_reasons, qualification_assessment, missing_information,
                    schedule_inquiry, submission_method, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, '', ?, ?, ?, 'NOT_SUBMITTED', ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?)
                """,
                (
                    job_id,
                    draft.get("resume_filename"),
                    None,
                    draft.get("answers", "[]"),
                    draft["status"],
                    draft.get("notes", ""),
                    draft.get("resume_id"),
                    draft.get("cover_letter", ""),
                    version,
                    draft.get("resume_version", ""),
                    draft.get("tailored_resume", ""),
                    draft.get("additional_questions", ""),
                    draft.get("eligibility_status", "needs_verification"),
                    draft.get("eligibility_reasons", "[]"),
                    draft.get("qualification_assessment", "{}"),
                    draft.get("missing_information", "[]"),
                    draft.get("schedule_inquiry", ""),
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                ),
            )
            application_id = cursor.lastrowid
            conn.execute(
                """
                INSERT INTO application_audit (
                    application_id, event_type, from_status, to_status,
                    details, created_at
                ) VALUES (?, 'draft_created', NULL, ?, ?, ?)
                """,
                (
                    application_id,
                    draft["status"],
                    f"job_id={job_id}; version={version}",
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            return application_id, True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def update_application(
        self,
        application_id,
        updates,
        event_type="draft_updated",
        details="",
        expected_status=None,
    ):
        allowed = {
            "answers", "resume_filename", "resume_id", "resume_version",
            "tailored_resume", "cover_letter", "additional_questions", "status",
            "eligibility_status", "eligibility_reasons", "qualification_assessment",
            "missing_information", "eligibility_verification", "submission_method", "confirmation_ref",
            "follow_up_date", "approved_at", "submitted_at", "submission_state",
            "idempotency_key", "applied_at", "schedule_resolution", "schedule_inquiry",
        }
        invalid = set(updates) - allowed
        if invalid:
            raise ValueError(f"Unsupported application fields: {', '.join(sorted(invalid))}")
        if not updates:
            return self.get_application(application_id)

        conn = get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT status FROM applications WHERE id = ?", (application_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"Application {application_id} does not exist")
            previous = row["status"]
            if expected_status is not None and previous != expected_status:
                raise ValueError(
                    f"Application {application_id} status changed from "
                    f"{expected_status} to {previous}"
                )
            values = dict(updates)
            values["updated_at"] = datetime.now().isoformat()
            assignments = ", ".join(f"{key} = ?" for key in values)
            conn.execute(
                f"UPDATE applications SET {assignments} WHERE id = ?",
                (*values.values(), application_id),
            )
            next_status = values.get("status", previous)
            conn.execute(
                """
                INSERT INTO application_audit (
                    application_id, event_type, from_status, to_status,
                    details, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    application_id,
                    event_type,
                    previous,
                    next_status,
                    details,
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return self.get_application(application_id)

    def get_application_events(self, application_id):
        conn = get_conn()
        try:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM application_audit WHERE application_id = ? ORDER BY id",
                    (application_id,),
                ).fetchall()
            ]
        finally:
            conn.close()

    def get_applications(self):
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT a.*, j.job_title AS job_title, j.employer AS employer,
                   j.job_url AS job_url, j.location AS location
            FROM applications a
            LEFT JOIN jobs j ON j.id = a.job_id
            ORDER BY a.id DESC
        """)
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
            now = datetime.now().astimezone().isoformat()
            schedule_classification = job_data.get("schedule_classification") or {}
            if not isinstance(schedule_classification, str):
                schedule_classification = json.dumps(schedule_classification)
            cur.execute("""
                INSERT OR IGNORE INTO jobs 
                (employer, job_title, job_url, source, description, location, remote, salary, shift, 
                 employment_type, experience_required, education_required, posting_date, deadline, 
                 discovered_at, match_score, match_explanation, status, approved, job_category,
                 source_feed, source_updated_at, last_verified_at, listing_status,
                 schedule_classification, repost_group_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job_data.get('employer'), job_data.get('job_title'), job_url_norm,
                job_data.get('source'), job_data.get('description'), job_data.get('location'),
                1 if job_data.get('remote') else 0, job_data.get('salary'), job_data.get('shift', 'unknown'),
                job_data.get('employment_type'), job_data.get('experience_required'),
                job_data.get('education_required'), job_data.get('posting_date'),
                job_data.get('deadline'), datetime.now().isoformat(), job_data.get('match_score', 0),
                job_data.get('match_explanation', ''), job_data.get('status', 'discovered'),
                0, job_data.get("job_category", ""), job_data.get("source_feed", ""),
                job_data.get("source_updated_at"),
                job_data.get("last_verified_at") or job_data.get("retrieved_at"),
                job_data.get("listing_status", "unknown"),
                schedule_classification, job_data.get("repost_group_key") or self.repost_group_key(job_data)
            ))
            conn.commit()
            if cur.rowcount == 0:
                row = cur.execute(
                    "SELECT id FROM jobs WHERE job_url = ?", (job_url_norm,)
                ).fetchone()
                return row["id"] if row else None
            return cur.lastrowid
        finally:
            conn.close()

    def refresh_job_listing(self, job_data, checked_at=None):
        job_url = self.normalize_url(job_data.get("job_url", ""))
        if not job_url:
            return False
        verified_at = checked_at or job_data.get("last_verified_at") or datetime.now().astimezone().isoformat()
        schedule_classification = job_data.get("schedule_classification") or {}
        if not isinstance(schedule_classification, str):
            schedule_classification = json.dumps(schedule_classification)
        conn = get_conn()
        try:
            cursor = conn.execute(
                """
                UPDATE jobs
                SET employer = ?, job_title = ?, source = ?, description = ?, location = ?,
                    remote = ?, salary = ?, shift = ?, employment_type = ?,
                    experience_required = ?, education_required = ?, posting_date = ?,
                    deadline = ?, job_category = ?, source_feed = ?, source_updated_at = ?,
                    last_verified_at = ?, listing_status = ?,
                    schedule_classification = ?, repost_group_key = ?
                WHERE job_url = ?
                """,
                (
                    job_data.get("employer"), job_data.get("job_title"), job_data.get("source"),
                    job_data.get("description"), job_data.get("location"),
                    1 if job_data.get("remote") else 0, job_data.get("salary"),
                    job_data.get("shift", "unknown"), job_data.get("employment_type"),
                    job_data.get("experience_required"), job_data.get("education_required"),
                    job_data.get("posting_date"), job_data.get("deadline"),
                    job_data.get("job_category", ""), job_data.get("source_feed", ""),
                    job_data.get("source_updated_at"), verified_at,
                    job_data.get("listing_status", "active_on_source"), schedule_classification,
                    job_data.get("repost_group_key") or self.repost_group_key(job_data), job_url,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def update_source_snapshot(
        self,
        source,
        source_feed,
        listed_urls,
        checked_at,
        active_status="active_on_source",
    ):
        normalized_urls = sorted(
            {self.normalize_url(url) for url in listed_urls if self.normalize_url(url)}
        )
        conn = get_conn()
        try:
            conn.execute(
                """
                UPDATE jobs
                SET listing_status = 'not_listed_on_source', last_verified_at = ?
                WHERE source = ? AND source_feed = ?
                """,
                (checked_at, source, source_feed),
            )
            for start in range(0, len(normalized_urls), 500):
                batch = normalized_urls[start : start + 500]
                placeholders = ",".join("?" for _ in batch)
                conn.execute(
                    f"""
                    UPDATE jobs
                    SET listing_status = ?, last_verified_at = ?
                    WHERE source = ? AND source_feed = ? AND job_url IN ({placeholders})
                    """,
                    (active_status, checked_at, source, source_feed, *batch),
                )
            conn.commit()
        finally:
            conn.close()
    
    def get_jobs(self):
        conn = get_conn()
        try:
            rows = [
                dict(row)
                for row in conn.execute("SELECT * FROM jobs ORDER BY discovered_at DESC")
            ]
        finally:
            conn.close()
        for job in rows:
            if not job.get("repost_group_key"):
                job["repost_group_key"] = self.repost_group_key(job)
        group_counts = Counter(
            job["repost_group_key"] for job in rows if job["repost_group_key"]
        )
        for job in rows:
            job["possible_repost_count"] = group_counts.get(job["repost_group_key"], 1)
        return rows
    
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
    init_db()
    conn = get_conn()
    try:
        ensure_job_columns(conn)
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(applications)")
        }
        migrations = {
            "resume_id": "TEXT",
            "cover_letter": "TEXT",
            "submission_state": "TEXT",
            "idempotency_key": "TEXT",
            "tailored_resume": "TEXT",
            "version_number": "INTEGER NOT NULL DEFAULT 1",
            "resume_version": "TEXT",
            "additional_questions": "TEXT NOT NULL DEFAULT ''",
            "eligibility_status": "TEXT NOT NULL DEFAULT 'needs_verification'",
            "eligibility_reasons": "TEXT NOT NULL DEFAULT '[]'",
            "qualification_assessment": "TEXT NOT NULL DEFAULT '{}'",
            "missing_information": "TEXT NOT NULL DEFAULT '[]'",
            "eligibility_verification": "TEXT NOT NULL DEFAULT ''",
            "schedule_resolution": "TEXT NOT NULL DEFAULT ''",
            "schedule_inquiry": "TEXT NOT NULL DEFAULT ''",
            "submission_method": "TEXT NOT NULL DEFAULT ''",
            "confirmation_ref": "TEXT NOT NULL DEFAULT ''",
            "follow_up_date": "TEXT",
            "approved_at": "TEXT",
            "submitted_at": "TEXT",
            "created_at": "TEXT",
            "updated_at": "TEXT",
        }
        for name, declaration in migrations.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE applications ADD COLUMN {name} {declaration}")

        duplicates = conn.execute(
            """
            SELECT job_id, COUNT(*) AS application_count
            FROM applications
            WHERE job_id IS NOT NULL
            GROUP BY job_id
            HAVING COUNT(*) > 1
            """
        ).fetchall()
        for duplicate in duplicates:
            applications = conn.execute(
                """
                SELECT id FROM applications
                WHERE job_id = ?
                ORDER BY COALESCE(created_at, ''), id
                """,
                (duplicate["job_id"],),
            ).fetchall()
            conn.executemany(
                "UPDATE applications SET version_number = ? WHERE id = ?",
                ((version, row["id"]) for version, row in enumerate(applications, 1)),
            )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS application_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                from_status TEXT,
                to_status TEXT,
                details TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(application_id) REFERENCES applications(id)
            )
        """)
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_app_job_version
            ON applications(job_id, version_number)
            WHERE job_id IS NOT NULL
        """)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return True
