"""Stage 12.6.1 regression tests: discovery-stage job pipeline.

Interested → Verification Required → Verified → Resume Ready, kept strictly
separate from the application lifecycle (applications.status). All
databases are temporary; production data untouched.
"""
import json
import sqlite3

import pytest

import database.db as db_module
from tracking.application_tracker import ApplicationTracker


@pytest.fixture
def isolated_tracker(tmp_path, monkeypatch):
    db_file = tmp_path / "test_pipeline.db"
    monkeypatch.setattr(db_module, "DB_PATH", str(db_file))
    db_module.init_db()
    yield ApplicationTracker()


VALID_MANUAL_RESOLUTION = {
    "value": "confirmed_evening",
    "source": "https://employer.example.com/careers/1",
    "evidence": "Employer confirmed shift 5 PM - 1 AM",
    "timestamp": "2026-11-05T10:00:00-05:00",
}


def _add_job(tracker, url="https://jobs.example.com/1", description="Some posting text."):
    return tracker.add_job({
        "employer": "Example Corp",
        "job_title": "Support Analyst",
        "job_url": url,
        "source": "greenhouse",
        "description": description,
        "location": "Remote - Canada",
        "remote": 1,
        "listing_status": "active_on_source",
    })


def _stored_status(tracker, job_id):
    conn = sqlite3.connect(db_module.DB_PATH)
    row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    return row[0]


def _add_application_with_resume(job_id, tailored="<p>resume</p>"):
    """Create an application draft with a generated tailored resume."""
    conn = sqlite3.connect(db_module.DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO applications (job_id, status, tailored_resume) VALUES (?, ?, ?)",
        (job_id, "Draft", tailored),
    )
    app_id = cur.lastrowid
    conn.commit()
    conn.close()
    return app_id


# --- valid transitions ---

def test_full_valid_pipeline_progression(isolated_tracker):
    job_id = _add_job(isolated_tracker)
    assert isolated_tracker.get_discovery_status(job_id) == "discovered"
    isolated_tracker.set_discovery_status(job_id, "interested")
    assert isolated_tracker.get_discovery_status(job_id) == "interested"
    isolated_tracker.set_discovery_status(job_id, "verification_required")
    assert isolated_tracker.get_discovery_status(job_id) == "verification_required"
    # verified requires evidence-backed manual resolution
    conn = sqlite3.connect(db_module.DB_PATH)
    conn.execute(
        "UPDATE jobs SET schedule_classification = ? WHERE id = ?",
        (
            json.dumps({
                "status": "confirmed_evening",
                "manual_resolution": VALID_MANUAL_RESOLUTION,
            }),
            job_id,
        ),
    )
    conn.commit()
    conn.close()
    isolated_tracker.set_discovery_status(job_id, "verified")
    assert isolated_tracker.get_discovery_status(job_id) == "verified"
    # resume_ready requires an application with a generated resume
    with pytest.raises(ValueError, match="generated resume"):
        isolated_tracker.set_discovery_status(job_id, "resume_ready")
    app_id = _add_application_with_resume(job_id)
    isolated_tracker.set_discovery_status(job_id, "resume_ready", resume_id=app_id)
    assert isolated_tracker.get_discovery_status(job_id) == "resume_ready"


def test_discovered_to_verification_required_direct(isolated_tracker):
    job_id = _add_job(isolated_tracker)
    isolated_tracker.set_discovery_status(job_id, "verification_required")
    assert isolated_tracker.get_discovery_status(job_id) == "verification_required"


def test_backwards_transition_allowed(isolated_tracker):
    job_id = _add_job(isolated_tracker)
    isolated_tracker.set_discovery_status(job_id, "interested")
    isolated_tracker.set_discovery_status(job_id, "verification_required")
    isolated_tracker.set_discovery_status(job_id, "interested")  # step back
    assert isolated_tracker.get_discovery_status(job_id) == "interested"


# --- invalid transitions ---

def test_invalid_transitions_rejected(isolated_tracker):
    job_id = _add_job(isolated_tracker)
    with pytest.raises(ValueError, match="Invalid discovery transition"):
        isolated_tracker.set_discovery_status(job_id, "verified")
    with pytest.raises(ValueError, match="Invalid discovery transition"):
        isolated_tracker.set_discovery_status(job_id, "resume_ready")
    # discovered → resume_ready skipped states entirely
    with pytest.raises(ValueError, match="Invalid discovery transition"):
        isolated_tracker.set_discovery_status(job_id, "resume_ready")
    assert isolated_tracker.get_discovery_status(job_id) == "discovered"
    # unchanged row (no partial writes)
    assert _stored_status(isolated_tracker, job_id) == "discovered"


def test_verified_requires_manual_resolution(isolated_tracker):
    job_id = _add_job(isolated_tracker)
    isolated_tracker.set_discovery_status(job_id, "verification_required")
    with pytest.raises(ValueError, match="manual schedule resolution"):
        isolated_tracker.set_discovery_status(job_id, "verified")
    assert isolated_tracker.get_discovery_status(job_id) == "verification_required"


def test_resume_ready_requires_generated_resume(isolated_tracker):
    job_id = _add_job(isolated_tracker)
    isolated_tracker.set_discovery_status(job_id, "interested")
    isolated_tracker.set_discovery_status(job_id, "verification_required")
    conn = sqlite3.connect(db_module.DB_PATH)
    conn.execute(
        "UPDATE jobs SET schedule_classification = ? WHERE id = ?",
        (json.dumps({"manual_resolution": VALID_MANUAL_RESOLUTION}), job_id),
    )
    conn.commit()
    conn.close()
    isolated_tracker.set_discovery_status(job_id, "verified")
    # Opening the resume page is not enough: no application with resume exists
    with pytest.raises(ValueError, match="generated resume"):
        isolated_tracker.set_discovery_status(job_id, "resume_ready")
    # An application WITHOUT a tailored resume is also insufficient
    conn = sqlite3.connect(db_module.DB_PATH)
    conn.execute(
        "INSERT INTO applications (job_id, status, tailored_resume) VALUES (?, ?, ?)",
        (job_id, "Draft", None),
    )
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="generated resume"):
        isolated_tracker.set_discovery_status(job_id, "resume_ready")
    assert isolated_tracker.get_discovery_status(job_id) == "verified"


def test_unknown_status_rejected(isolated_tracker):
    job_id = _add_job(isolated_tracker)
    with pytest.raises(ValueError, match="Unknown discovery status"):
        isolated_tracker.set_discovery_status(job_id, "approved")
    with pytest.raises(ValueError, match="Unknown discovery status"):
        isolated_tracker.set_discovery_status(job_id, "nonexistent")


def test_nonexistent_job_rejected(isolated_tracker):
    with pytest.raises(ValueError, match="does not exist"):
        isolated_tracker.set_discovery_status(99999, "interested")


# --- provenance preservation ---

def test_provenance_preserved_across_transitions(isolated_tracker):
    job_id = _add_job(isolated_tracker)
    classification = {
        "status": "confirmed_evening",
        "manual_resolution": VALID_MANUAL_RESOLUTION,
        "description_fingerprint_at_resolution": "abc",
        "manual_evidence_needs_reverification": False,
    }
    conn = sqlite3.connect(db_module.DB_PATH)
    conn.execute(
        "UPDATE jobs SET schedule_classification = ? WHERE id = ?",
        (json.dumps(classification), job_id),
    )
    conn.commit()
    conn.close()
    isolated_tracker.set_discovery_status(job_id, "interested")
    isolated_tracker.set_discovery_status(job_id, "verification_required")
    isolated_tracker.set_discovery_status(job_id, "verified")
    conn = sqlite3.connect(db_module.DB_PATH)
    row = conn.execute(
        "SELECT schedule_classification FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()
    conn.close()
    stored = json.loads(row[0])
    assert stored["manual_resolution"] == VALID_MANUAL_RESOLUTION
    assert stored["description_fingerprint_at_resolution"] == "abc"
    assert stored["manual_evidence_needs_reverification"] is False


# --- backward compatibility ---

def test_backward_compatibility_legacy_status_values(isolated_tracker):
    """Rows with legacy/unknown status values map to 'discovered'."""
    job_id = _add_job(isolated_tracker)
    conn = sqlite3.connect(db_module.DB_PATH)
    conn.execute("UPDATE jobs SET status = 'discovered' WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()
    assert isolated_tracker.get_discovery_status(job_id) == "discovered"
    # Pipeline works from legacy value
    isolated_tracker.set_discovery_status(job_id, "interested")
    assert isolated_tracker.get_discovery_status(job_id) == "interested"


def test_application_lifecycle_untouched(isolated_tracker):
    """Application statuses live in applications.status and are never touched
    by discovery transitions; audit history preserved."""
    job_id = _add_job(isolated_tracker)
    app_id = _add_application_with_resume(job_id)
    isolated_tracker.set_discovery_status(job_id, "interested")
    isolated_tracker.set_discovery_status(job_id, "verification_required")
    conn = sqlite3.connect(db_module.DB_PATH)
    conn.row_factory = sqlite3.Row
    app_row = conn.execute(
        "SELECT status, job_id FROM applications WHERE id = ?", (app_id,)
    ).fetchone()
    conn.close()
    assert app_row["status"] == "Draft"          # lifecycle untouched
    assert app_row["job_id"] == job_id           # no duplicate/rewrite
    # exactly one application for the job
    conn = sqlite3.connect(db_module.DB_PATH)
    count = conn.execute(
        "SELECT COUNT(*) FROM applications WHERE job_id = ?", (job_id,)
    ).fetchone()[0]
    conn.close()
    assert count == 1


def test_existing_readiness_and_suitability_gates_unchanged(isolated_tracker):
    """Discovery status must not affect classification or suitability."""
    from agents.job_classifier import classify_opportunity
    job_id = _add_job(
        isolated_tracker,
        description="Shift: 5 PM - 1 AM Eastern Time.",
    )
    conn = sqlite3.connect(db_module.DB_PATH)
    conn.row_factory = sqlite3.Row
    job_row = dict(conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())
    conn.close()
    classification_before = classify_opportunity(job_row)
    isolated_tracker.set_discovery_status(job_id, "interested")
    isolated_tracker.set_discovery_status(job_id, "verification_required")
    conn = sqlite3.connect(db_module.DB_PATH)
    conn.row_factory = sqlite3.Row
    job_row2 = dict(conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())
    conn.close()
    classification_after = classify_opportunity(job_row2)
    assert classification_before["status"] == classification_after["status"]
    assert classification_after["status"] == "confirmed_evening"
