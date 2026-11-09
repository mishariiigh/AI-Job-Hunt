import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from urllib.parse import urlparse, urlunparse

from agents.job_classifier import classify_evening_eligibility
from database.db import ensure_job_columns, get_conn, init_db


class ManualResolutionError(ValueError):
    """Raised when a manual schedule resolution is incomplete or invalid."""


class FieldVerificationError(ValueError):
    """Raised when a manual field verification is incomplete or invalid."""


# Stage 12.6.3: allowed values for manually verified employment hours and
# work arrangement. "unknown" is a valid explicit value: recording "I checked
# and it is not stated" is itself verified information.
EMPLOYMENT_HOURS_VALUES = {"full_time", "part_time", "exact_hours", "unknown"}
WORK_ARRANGEMENT_VALUES = {
    "remote_canada",
    "remote_north_america",
    "remote_worldwide",
    "remote_location_restricted",
    "hybrid",
    "on_site",
    "unknown",
}


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

    # ---- Discovery-stage pipeline (Interested → Verification Required →
    # ---- Verified → Resume Ready). Deliberately separate from the
    # ---- application lifecycle (Draft → Approved → …) which lives in
    # ---- applications.status.

    DISCOVERY_STATUSES = {
        "discovered": 0,           # legacy: unchanged discovered postings
        "interested": 1,
        "verification_required": 2,
        "verified": 3,
        "resume_ready": 4,
    }

    DISCOVERY_TRANSITIONS = {
        "discovered": {"interested", "verification_required"},
        "interested": {"verification_required", "discovered"},
        "verification_required": {"verified", "interested", "discovered"},
        "verified": {"resume_ready", "verification_required", "interested", "discovered"},
        "resume_ready": {"verified", "discovered"},
    }

    def get_discovery_status(self, job_id):
        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT status FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return row[0] if row[0] in self.DISCOVERY_STATUSES else "discovered"

    def set_discovery_status(self, job_id, new_status, *, resume_id=None):
        """Move a job through the discovery pipeline.

        User-controlled only: no automatic transitions. 'verified' requires a
        manual schedule resolution with recorded evidence (provenance stays in
        schedule_classification). 'resume_ready' requires a generated resume
        (resume_id must reference an existing resume row).
        """
        if new_status not in self.DISCOVERY_STATUSES:
            raise ValueError(f"Unknown discovery status: {new_status}")
        conn = get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT status, schedule_classification FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if not row:
                conn.rollback()
                raise ValueError(f"Job {job_id} does not exist.")
            current = row[0] if row[0] in self.DISCOVERY_STATUSES else "discovered"
            if new_status == current:
                conn.rollback()
                return current
            allowed = self.DISCOVERY_TRANSITIONS[current]
            if new_status not in allowed:
                conn.rollback()
                raise ValueError(
                    f"Invalid discovery transition: {current} → {new_status}. "
                    f"Allowed: {sorted(allowed)}"
                )
            if new_status == "resume_ready":
                if not resume_id:
                    conn.rollback()
                    raise ValueError(
                        "resume_ready requires a generated resume for this job."
                    )
                # Resume versions live on application records: an application
                # draft must exist for this job with a tailored resume.
                resume_row = conn.execute(
                    "SELECT id FROM applications WHERE job_id = ? AND"
                    " (tailored_resume IS NOT NULL AND tailored_resume != '')",
                    (job_id,),
                ).fetchone()
                if not resume_row:
                    conn.rollback()
                    raise ValueError(
                        f"No application with a generated resume exists for job "
                        f"{job_id}; resume_ready requires a generated, "
                        "validated resume."
                    )
            if new_status == "verified":
                try:
                    classification = json.loads(row[1] or "{}")
                except (TypeError, ValueError):
                    classification = {}
                has_resolution = bool(
                    isinstance(classification, dict)
                    and classification.get("manual_resolution")
                )
                if not has_resolution:
                    conn.rollback()
                    raise ValueError(
                        "verified requires a manual schedule resolution with "
                        "recorded evidence (source, evidence, timestamp)."
                    )
            conn.execute(
                "UPDATE jobs SET status = ? WHERE id = ?", (new_status, job_id)
            )
            conn.commit()
            return new_status
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

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

    @staticmethod
    def _description_fingerprint(description):
        """Whitespace-insensitive description fingerprint for change detection."""
        return " ".join(str(description or "").split())

    def _stored_manual_resolution(self, job_url):
        """Return the stored manual state for a job.

        Returns (manual_resolution dict or None, description fingerprint
        recorded at verification, current re-verification flag). The flag is
        read from the stored classification so it survives repeated
        automatic refreshes until an explicit user re-verification.
        """
        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT schedule_classification FROM jobs WHERE job_url = ?",
                (job_url,),
            ).fetchone()
        finally:
            conn.close()
        if not row or not row[0]:
            return None, None, False
        try:
            parsed = json.loads(row[0])
        except (TypeError, ValueError):
            return None, None, False
        if not isinstance(parsed, dict):
            return None, None, False
        resolution = parsed.get("manual_resolution")
        ok = isinstance(resolution, dict) and resolution.get("value")
        stored_hash = parsed.get("description_fingerprint_at_resolution")
        stored_flag = bool(parsed.get("manual_evidence_needs_reverification"))
        return (resolution if ok else None), stored_hash, stored_flag

    @staticmethod
    def _merge_manual_resolution(
        stored_manual, stored_description_hash, stored_reverify_flag,
        schedule_classification, description,
    ):
        """Re-apply the stored manual resolution onto an automatic refresh.

        The manual decision always wins over automatic classification. The
        incoming description is compared against a fingerprint of the
        description present when the manual resolution was originally
        verified ("description_fingerprint_at_resolution" is only updated
        by an explicit user re-verification, never by automatic refreshes):
        an unchanged description keeps the resolution cleanly; a changed
        description retains the decision but flags that the manual evidence
        must be re-verified. Repeated refreshes never clear the flag on
        their own. The automatic classification evidence is preserved
        inside the merged result rather than discarded.
        """
        if isinstance(schedule_classification, str):
            try:
                automatic = json.loads(schedule_classification)
            except (TypeError, ValueError):
                automatic = {}
        else:
            automatic = schedule_classification or {}
        description_changed = (
            description is not None
            and (
                stored_description_hash is None
                or ApplicationTracker._description_fingerprint(description)
                != stored_description_hash
            )
        )
        merged = {
            **automatic,
            "manual_resolution": stored_manual,
            # Keep the ORIGINAL verification fingerprint: it anchors the
            # evidence to the posting text the user actually verified.
            # Automatic refreshes must not move this anchor, or a second
            # refresh of a changed posting would silently clear the
            # re-verification flag.
            "description_fingerprint_at_resolution": stored_description_hash,
        }
        if stored_manual.get("value") == "confirmed_evening":
            merged["status"] = "confirmed_evening"
            merged["schedule_type"] = "confirmed_evening"
            merged["confirmed_evening"] = True
            merged["needs_schedule_verification"] = False
        elif stored_manual.get("value") == "incompatible":
            merged["status"] = "incompatible"
            merged["schedule_type"] = "day_shift"
            merged["confirmed_evening"] = False
        if description_changed:
            merged["manual_evidence_needs_reverification"] = True
            merged["reason"] = (
                "Manually verified schedule retained, but the source posting "
                "description changed after the manual evidence was recorded; "
                "re-verify the evidence against the current posting."
            )
        else:
            # Only an explicit user re-verification (which replaces the
            # manual_resolution and re-anchors the fingerprint) may clear
            # this flag; automatic refreshes never do.
            merged["manual_evidence_needs_reverification"] = bool(stored_reverify_flag)
        return json.dumps(merged)

    def record_manual_schedule_resolution(
        self, job_id, resolution, verified_description=None,
    ):
        """Explicit user-confirmed schedule re-verification.

        This is the ONLY operation that may replace a stored manual
        resolution, re-anchor description_fingerprint_at_resolution, and
        clear manual_evidence_needs_reverification. Discovery refreshes can
        never reach this code path.

        Required resolution fields: value (confirmed_evening or
        incompatible), source, evidence, timestamp. Incomplete or invalid
        resolutions are rejected with ManualResolutionError and change
        nothing.

        verified_description: the job description the user verified against.
        Defaults to the description currently stored for the job; passing a
        different description would break provenance, so it is validated.
        """
        from agents.job_classifier import classify_evening_eligibility

        if not isinstance(resolution, dict):
            raise ManualResolutionError("Resolution must be an object.")
        if resolution.get("value") not in {"confirmed_evening", "incompatible"}:
            raise ManualResolutionError(
                "Resolution value must be 'confirmed_evening' or 'incompatible'."
            )
        for field in ("source", "evidence", "timestamp"):
            if not str(resolution.get(field) or "").strip():
                raise ManualResolutionError(
                    f"Resolution field '{field}' is required."
                )

        conn = get_conn()
        try:
            # Atomic read-modify-write: BEGIN IMMEDIATE takes the database
            # write lock up front, so a concurrent discovery refresh cannot
            # change the description between the verification SELECT and
            # the persistence UPDATE. Matches the existing pattern used by
            # create_application_draft and the submission path.
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT description, schedule_classification FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if not row:
                raise ManualResolutionError(f"Job {job_id} does not exist.")
            try:
                classification = json.loads(row["schedule_classification"] or "{}")
            except (TypeError, ValueError):
                classification = {}
            if not isinstance(classification, dict):
                classification = {}
            description = verified_description
            if description is None:
                description = row["description"]
            elif description != row["description"]:
                raise ManualResolutionError(
                    "verified_description does not match the stored posting "
                    "description; re-verification must reference the posting "
                    "as currently recorded."
                )
            automatic = classify_evening_eligibility(
                {**dict(row), "description": description}
            )
            merged = {
                **classification,
                **automatic,
                "manual_resolution": dict(resolution),
                "description_fingerprint_at_resolution": (
                    self._description_fingerprint(description)
                ),
                "manual_evidence_needs_reverification": False,
                "confidence": "user_verified",
            }
            if resolution["value"] == "confirmed_evening":
                merged["status"] = "confirmed_evening"
                merged["confirmed_evening"] = True
                merged["needs_schedule_verification"] = False
            else:
                merged["status"] = "incompatible"
                merged["confirmed_evening"] = False
                merged["needs_schedule_verification"] = False
            conn.execute(
                "UPDATE jobs SET schedule_classification = ? WHERE id = ?",
                (json.dumps(merged), job_id),
            )
            conn.commit()
            return merged
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def record_manual_field_verification(
        self, job_id, field_name, value, evidence, source,
        timestamp=None, verified_description=None,
    ):
        """Stage 12.6.3: explicit user-verified employment details.

        Stores user-verified employment hours or work arrangement with full
        provenance in jobs.field_verification (JSON keyed by field name).
        This is the ONLY operation that writes that column; discovery
        refreshes never touch it.

        Architecture notes (mirrors record_manual_schedule_resolution):
        - One BEGIN IMMEDIATE transaction; any failure rolls the whole
          operation back, including a concurrent refresh's write.
        - Verified values are stored with field name, value, evidence text,
          evidence source, and timestamp per field, so updating one field
          never erases another field's evidence.
        - The schedule verification system (schedule_classification /
          manual_resolution) is untouched by this method; callers must use
          record_manual_schedule_resolution for schedule verification.

        field_name: "employment_hours" or "work_arrangement".
        value: one of EMPLOYMENT_HOURS_VALUES / WORK_ARRANGEMENT_VALUES
        (per field). "unknown" means the user verified the value is not
        stated anywhere; it never becomes a positive confirmation.
        evidence: the user's supporting text (required).
        source: where the evidence came from, e.g. employer email (required).
        verified_description: optional posting text the user verified
        against; must match the stored description when supplied, for the
        same provenance reason as in record_manual_schedule_resolution.
        """
        from agents.job_classifier import classify_evening_eligibility

        if field_name not in {"employment_hours", "work_arrangement"}:
            raise FieldVerificationError(
                "field_name must be 'employment_hours' or 'work_arrangement'."
            )
        allowed = (
            EMPLOYMENT_HOURS_VALUES
            if field_name == "employment_hours"
            else WORK_ARRANGEMENT_VALUES
        )
        if value not in allowed:
            raise FieldVerificationError(
                f"Invalid {field_name} value '{value}'. Allowed: {sorted(allowed)}"
            )
        evidence = str(evidence or "").strip()
        source = str(source or "").strip()
        if not evidence or not source:
            raise FieldVerificationError(
                "Both evidence text and evidence source are required."
            )
        timestamp = timestamp or datetime.now().astimezone().isoformat()
        try:
            datetime.fromisoformat(timestamp)
        except ValueError:
            raise FieldVerificationError("timestamp must be an ISO 8601 datetime.")
        if field_name == "employment_hours" and value == "exact_hours":
            # exact_hours needs the actual number in the evidence text.
            if not re.search(r"\d", evidence):
                raise FieldVerificationError(
                    "exact_hours requires the number of weekly hours in the "
                    "evidence text."
                )

        conn = get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT description, schedule_classification, "
                "field_verification FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if not row:
                raise FieldVerificationError(f"Job {job_id} does not exist.")
            if verified_description is not None and verified_description != row["description"]:
                raise FieldVerificationError(
                    "verified_description does not match the stored posting "
                    "description; verification must reference the posting as "
                    "currently recorded."
                )
            try:
                stored = json.loads(row["field_verification"] or "{}")
            except (TypeError, ValueError):
                stored = {}
            if not isinstance(stored, dict):
                stored = {}
            stored[field_name] = {
                "value": value,
                "evidence": evidence,
                "source": source,
                "timestamp": timestamp,
            }
            conn.execute(
                "UPDATE jobs SET field_verification = ? WHERE id = ?",
                (json.dumps(stored), job_id),
            )
            conn.commit()
            return stored
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def clear_manual_field_verification(self, job_id, field_name):
        """Remove a manual field verification (correction path).

        Only clears the named field; all other verified fields and the
        schedule verification are untouched.
        """
        if field_name not in {"employment_hours", "work_arrangement"}:
            raise FieldVerificationError(
                "field_name must be 'employment_hours' or 'work_arrangement'."
            )
        conn = get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT field_verification FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if not row:
                raise FieldVerificationError(f"Job {job_id} does not exist.")
            try:
                stored = json.loads(row["field_verification"] or "{}")
            except (TypeError, ValueError):
                stored = {}
            if not isinstance(stored, dict):
                stored = {}
            stored.pop(field_name, None)
            conn.execute(
                "UPDATE jobs SET field_verification = ? WHERE id = ?",
                (json.dumps(stored), job_id),
            )
            conn.commit()
            return stored
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _persisted_schedule_classification(job_data):
        """Return the authoritative schedule classification for persistence.

        Uses the classifier result supplied by discovery when present;
        otherwise computes it with the existing authoritative classifier.
        A manually resolved classification supplied in the incoming payload
        (carrying manual_resolution with source/evidence/timestamp) is
        preserved untouched.
        """
        existing = job_data.get("schedule_classification")
        if isinstance(existing, dict) and existing.get("manual_resolution"):
            return json.dumps(existing)
        if isinstance(existing, str):
            try:
                parsed = json.loads(existing)
            except (TypeError, ValueError):
                parsed = {}
            if isinstance(parsed, dict) and parsed.get("manual_resolution"):
                return existing
        result = classify_evening_eligibility(job_data)
        return json.dumps(result)

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
            schedule_classification = self._persisted_schedule_classification(job_data)
            # Record the description fingerprint at insert so future manual
            # resolutions and refreshes can detect posting-text changes.
            try:
                stored_classification = json.loads(schedule_classification)
            except (TypeError, ValueError):
                stored_classification = {}
            if isinstance(stored_classification, dict) and (
                stored_classification.get("manual_resolution")
                and not stored_classification.get("description_fingerprint_at_resolution")
            ):
                stored_classification["description_fingerprint_at_resolution"] = (
                    self._description_fingerprint(job_data.get("description"))
                )
                schedule_classification = json.dumps(stored_classification)
            cur.execute("""
                INSERT OR IGNORE INTO jobs
                (employer, job_title, job_url, source, description, location, remote, salary, shift,
                 employment_type, experience_required, education_required, posting_date, deadline,
                 discovered_at, match_score, match_explanation, status, approved, job_category,
                 source_feed, source_updated_at, last_verified_at, listing_status,
                 schedule_classification, repost_group_key,
                 gh_job_id, gh_metadata, office_locations, enriched_at,
                 source_platform, original_source_url, employer_application_url,
                 external_job_id, source_verification_status, imported_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                schedule_classification, job_data.get("repost_group_key") or self.repost_group_key(job_data),
                job_data.get("gh_job_id") or "",
                job_data.get("gh_metadata") or "",
                job_data.get("office_locations") or "",
                datetime.now().isoformat() if job_data.get("gh_job_id") else None,
                job_data.get("source_platform") or "",
                job_data.get("original_source_url") or "",
                job_data.get("employer_application_url") or "",
                job_data.get("external_job_id") or "",
                job_data.get("source_verification_status") or "",
                (
                    datetime.now().astimezone().isoformat()
                    if job_data.get("source_platform")
                    else None
                ),
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
        schedule_classification = self._persisted_schedule_classification(job_data)
        # Preserve a manually verified schedule resolution across automatic
        # refreshes: the incoming feed payload never carries manual_resolution,
        # so without this check the automatic classification would overwrite
        # the stored decision. If the source description changed, flag that
        # the manual evidence may need re-verification instead of silently
        # discarding either version.
        # Provenance rule: an automatic discovery refresh can NEVER create or
        # re-verify manual evidence, no matter what fields the feed payload
        # carries. Only record_manual_schedule_resolution() (a dedicated,
        # explicit user-confirmed operation) may replace a resolution, re-anchor
        # the description fingerprint, or clear the re-verification flag.
        stored_manual, stored_description_hash, stored_reverify_flag = (
            self._stored_manual_resolution(job_url)
        )
        if stored_manual:
            schedule_classification = self._merge_manual_resolution(
                stored_manual,
                stored_description_hash,
                stored_reverify_flag,
                schedule_classification,
                job_data.get("description"),
            )
        conn = get_conn()
        try:
            # Stage 12.3: enrich without damage — only overwrite an existing
            # enriched field when the feed provides a non-empty value.
            conn.execute(
                """
                UPDATE jobs
                SET gh_job_id = CASE WHEN ? != '' THEN ? ELSE gh_job_id END,
                    gh_metadata = CASE WHEN ? != '' THEN ? ELSE gh_metadata END,
                    office_locations = CASE WHEN ? != '' THEN ? ELSE office_locations END,
                    enriched_at = CASE
                        WHEN ? != '' THEN ?
                        ELSE enriched_at END
                WHERE job_url = ?
                """,
                (
                    job_data.get("gh_job_id") or "",
                    job_data.get("gh_job_id") or "",
                    job_data.get("gh_metadata") or "",
                    job_data.get("gh_metadata") or "",
                    job_data.get("office_locations") or "",
                    job_data.get("office_locations") or "",
                    job_data.get("gh_job_id") or "",
                    datetime.now().isoformat(),
                    job_url,
                ),
            )
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
        # Attach persisted hard disqualifiers (e.g. Seniority mismatch) so the
        # ranking and UI can treat them as provenance-backed gates.
        conn2 = get_conn()
        try:
            disqualifier_rows = {
                r["job_id"]: r["hard_disqualifiers"]
                for r in conn2.execute(
                    "SELECT job_id, hard_disqualifiers FROM matches"
                    " WHERE hard_disqualifiers IS NOT NULL"
                    " AND hard_disqualifiers != '[]'"
                ).fetchall()
            }
        finally:
            conn2.close()
        for job in rows:
            disqualifiers = disqualifier_rows.get(job["id"])
            if disqualifiers:
                job["hard_disqualifiers"] = disqualifiers
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
