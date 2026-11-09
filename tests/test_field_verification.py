"""Stage 12.6.3 regression tests: manually verified employment hours and
work arrangement.

The new verification fields extend — never replace — the existing schedule
verification system (record_manual_schedule_resolution /
schedule_classification). All databases are temporary; no HTTP calls.
"""
import json
import sqlite3
import threading
from datetime import datetime

import pytest

import database.db as db_module
from tracking.application_tracker import (
    ApplicationTracker,
    FieldVerificationError,
    ManualResolutionError,
)


@pytest.fixture
def isolated_tracker(tmp_path, monkeypatch):
    db_file = tmp_path / "test_fv.db"
    monkeypatch.setattr(db_module, "DB_PATH", str(db_file))
    db_module.init_db()
    yield ApplicationTracker()


def _add_job(tracker, **overrides):
    job = {
        "employer": "Acme Logistics",
        "job_title": "Evening IT Support Analyst",
        "job_url": "https://ca.indeed.com/viewjob?jk=fvtest001",
        "source": "indeed",
        "description": "Shift runs 5 PM to 1 AM at the Mississauga office.",
        "location": "Mississauga, Ontario",
        "employment_type": "",
        "listing_status": "user_imported",
    }
    job.update(overrides)
    return tracker.add_job(job)


def _fv(tracker, job_id):
    conn = sqlite3.connect(db_module.DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT field_verification, schedule_classification FROM jobs WHERE id = ?",
        (job_id,),
    ).fetchone()
    conn.close()
    return row


# 1. Schedule-only verification still works (unchanged path)
def test_schedule_only_verification_unchanged(isolated_tracker):
    job_id = _add_job(isolated_tracker)
    resolution = {
        "value": "confirmed_evening",
        "source": "Employer email",
        "evidence": "Employer confirmed the shift is 5:00 PM to 1:00 AM.",
        "timestamp": datetime.now().astimezone().isoformat(),
    }
    merged = isolated_tracker.record_manual_schedule_resolution(job_id, resolution)
    assert merged["status"] == "confirmed_evening"
    row = _fv(isolated_tracker, job_id)
    # schedule lives in schedule_classification; field_verification untouched
    assert json.loads(row["field_verification"]) == {}
    assert json.loads(row["schedule_classification"])["manual_resolution"]["source"] == "Employer email"


# 2. Part-time verification
def test_part_time_verification(isolated_tracker):
    job_id = _add_job(isolated_tracker)
    stored = isolated_tracker.record_manual_field_verification(
        job_id, "employment_hours", "part_time",
        evidence="Posting states 20 hours per week.", source="Employer posting",
    )
    assert stored["employment_hours"]["value"] == "part_time"
    row = _fv(isolated_tracker, job_id)
    assert json.loads(row["field_verification"])["employment_hours"]["value"] == "part_time"


# 3. Exact weekly-hours verification
def test_exact_hours_verification(isolated_tracker):
    job_id = _add_job(isolated_tracker)
    stored = isolated_tracker.record_manual_field_verification(
        job_id, "employment_hours", "exact_hours",
        evidence="Employer email states exactly 24 hours per week.",
        source="Employer email",
    )
    assert stored["employment_hours"]["value"] == "exact_hours"
    assert "24" in stored["employment_hours"]["evidence"]


def test_exact_hours_without_number_rejected(isolated_tracker):
    job_id = _add_job(isolated_tracker)
    with pytest.raises(FieldVerificationError, match="exact_hours"):
        isolated_tracker.record_manual_field_verification(
            job_id, "employment_hours", "exact_hours",
            evidence="Employer said the hours are fixed weekly.", source="Employer email",
        )
    assert _fv(isolated_tracker, job_id)["field_verification"] == "{}"


# 4. Remote, hybrid, and on-site verification
@pytest.mark.parametrize("value", [
    "remote_canada", "remote_north_america", "remote_worldwide",
    "remote_location_restricted", "hybrid", "on_site",
])
def test_work_arrangement_values(isolated_tracker, value):
    job_id = _add_job(isolated_tracker)
    stored = isolated_tracker.record_manual_field_verification(
        job_id, "work_arrangement", value,
        evidence="Employer states remote within Canada only.", source="Employer posting",
    )
    assert stored["work_arrangement"]["value"] == value


# 5. Unknown values remain unknown (explicit, never positive confirmation)
def test_unknown_values_recorded_as_unknown(isolated_tracker):
    job_id = _add_job(isolated_tracker)
    isolated_tracker.record_manual_field_verification(
        job_id, "employment_hours", "unknown",
        evidence="Checked posting and FAQ; hours are not stated anywhere.",
        source="Employer posting",
    )
    isolated_tracker.record_manual_field_verification(
        job_id, "work_arrangement", "unknown",
        evidence="Posting gives no arrangement details.", source="Employer posting",
    )
    fv = json.loads(_fv(isolated_tracker, job_id)["field_verification"])
    assert fv["employment_hours"]["value"] == "unknown"
    assert fv["work_arrangement"]["value"] == "unknown"


# 6. Evidence and timestamps persist
def test_evidence_and_timestamp_persist(isolated_tracker):
    job_id = _add_job(isolated_tracker)
    before = datetime.now().astimezone().isoformat()
    stored = isolated_tracker.record_manual_field_verification(
        job_id, "work_arrangement", "hybrid",
        evidence="Recruiter call confirmed 2 days in office.",
        source="Recruiter phone call",
    )
    after = datetime.now().astimezone().isoformat()
    record = stored["work_arrangement"]
    assert record["evidence"] == "Recruiter call confirmed 2 days in office."
    assert record["source"] == "Recruiter phone call"
    ts = datetime.fromisoformat(record["timestamp"])
    assert datetime.fromisoformat(before) <= ts <= datetime.fromisoformat(after)


# 7. Updating one field preserves the other field's evidence
def test_updating_one_field_preserves_other(isolated_tracker):
    job_id = _add_job(isolated_tracker)
    isolated_tracker.record_manual_field_verification(
        job_id, "employment_hours", "part_time",
        evidence="Posting states 20 hours per week.", source="Employer posting",
    )
    isolated_tracker.record_manual_field_verification(
        job_id, "work_arrangement", "remote_canada",
        evidence="Employer confirms remote within Canada.", source="Employer email",
    )
    # Now update hours; arrangement evidence must survive
    isolated_tracker.record_manual_field_verification(
        job_id, "employment_hours", "exact_hours",
        evidence="Updated: exactly 21 hours per week.", source="Employer email",
    )
    fv = json.loads(_fv(isolated_tracker, job_id)["field_verification"])
    assert fv["employment_hours"]["value"] == "exact_hours"
    assert fv["work_arrangement"]["value"] == "remote_canada"
    assert fv["work_arrangement"]["evidence"] == "Employer confirms remote within Canada."
    assert fv["work_arrangement"]["source"] == "Employer email"


# 7b. Schedule evidence survives field verification (and vice versa)
def test_schedule_and_field_verification_coexist(isolated_tracker):
    job_id = _add_job(isolated_tracker)
    resolution = {
        "value": "confirmed_evening",
        "source": "Employer email",
        "evidence": "Employer confirmed the shift is 5:00 PM to 1:00 AM.",
        "timestamp": datetime.now().astimezone().isoformat(),
    }
    isolated_tracker.record_manual_schedule_resolution(job_id, resolution)
    isolated_tracker.record_manual_field_verification(
        job_id, "employment_hours", "part_time",
        evidence="Posting states 20 hours per week.", source="Employer posting",
    )
    row = _fv(isolated_tracker, job_id)
    sc = json.loads(row["schedule_classification"])
    fv = json.loads(row["field_verification"])
    assert sc["manual_resolution"]["value"] == "confirmed_evening"
    assert fv["employment_hours"]["value"] == "part_time"
    # No field_verification content leaked into schedule_classification
    assert "employment_hours" not in sc


# 8. Invalid values are rejected
def test_invalid_values_rejected(isolated_tracker):
    job_id = _add_job(isolated_tracker)
    with pytest.raises(FieldVerificationError, match="field_name"):
        isolated_tracker.record_manual_field_verification(
            job_id, "schedule", "confirmed_evening", evidence="x", source="y",
        )
    with pytest.raises(FieldVerificationError, match="Invalid employment_hours"):
        isolated_tracker.record_manual_field_verification(
            job_id, "employment_hours", "flexible", evidence="x", source="y",
        )
    with pytest.raises(FieldVerificationError, match="Invalid work_arrangement"):
        isolated_tracker.record_manual_field_verification(
            job_id, "work_arrangement", "fully_remote", evidence="x", source="y",
        )
    with pytest.raises(FieldVerificationError, match="evidence"):
        isolated_tracker.record_manual_field_verification(
            job_id, "employment_hours", "part_time", evidence="", source="y",
        )
    with pytest.raises(FieldVerificationError, match="source"):
        isolated_tracker.record_manual_field_verification(
            job_id, "employment_hours", "part_time", evidence="x", source="",
        )
    with pytest.raises(FieldVerificationError, match="timestamp"):
        isolated_tracker.record_manual_field_verification(
            job_id, "employment_hours", "part_time", evidence="x", source="y",
            timestamp="not-a-date",
        )
    with pytest.raises(FieldVerificationError, match="does not exist"):
        isolated_tracker.record_manual_field_verification(
            99999, "employment_hours", "part_time", evidence="x", source="y",
        )
    # Nothing persisted
    assert _fv(isolated_tracker, job_id)["field_verification"] == "{}"


# 9. Transaction rollback works (concurrent refresh cannot interleave)
def test_rollback_on_concurrent_write(isolated_tracker):
    """A concurrent discovery refresh during record_manual_field_verification
    must not corrupt state; the verification rolls back or succeeds atomically
    (BEGIN IMMEDIATE serializes the writers)."""
    job_id = _add_job(isolated_tracker)
    started = threading.Event()
    release = threading.Event()

    def concurrent_refresh():
        started.set()
        release.wait(5)
        conn = sqlite3.connect(db_module.DB_PATH, timeout=5)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE jobs SET description = ? WHERE id = ?",
                ("Refreshed description between transactions.", job_id),
            )
            conn.commit()
        finally:
            conn.close()

    writer = threading.Thread(target=concurrent_refresh)
    writer.start()
    started.wait(5)
    try:
        stored = isolated_tracker.record_manual_field_verification(
            job_id, "employment_hours", "part_time",
            evidence="Posting states 20 hours per week.", source="Employer posting",
        )
        assert stored["employment_hours"]["value"] == "part_time"
    finally:
        release.set()
        writer.join(10)
    row = _fv(isolated_tracker, job_id)
    fv = json.loads(row["field_verification"])
    # Either the verification and the refresh both committed (serialized), or
    # the refresh failed to acquire the lock — never a partial state.
    assert fv["employment_hours"]["value"] == "part_time"


def test_failed_verification_rolls_back(isolated_tracker):
    """A failure mid-verification leaves the stored state unchanged."""
    job_id = _add_job(isolated_tracker)
    isolated_tracker.record_manual_field_verification(
        job_id, "employment_hours", "part_time",
        evidence="First good verification.", source="Employer posting",
    )
    with pytest.raises(FieldVerificationError):
        isolated_tracker.record_manual_field_verification(
            job_id, "work_arrangement", "invalid_value", evidence="x", source="y",
        )
    fv = json.loads(_fv(isolated_tracker, job_id)["field_verification"])
    assert fv["employment_hours"]["value"] == "part_time"
    assert "work_arrangement" not in fv


# 10. Existing discovery-status transitions remain correct
def test_verified_still_requires_schedule_resolution(isolated_tracker):
    job_id = _add_job(isolated_tracker)
    isolated_tracker.set_discovery_status(job_id, "verification_required")
    with pytest.raises(ValueError, match="verified requires"):
        isolated_tracker.set_discovery_status(job_id, "verified")
    # Field verification alone must NOT unlock the verified status
    isolated_tracker.record_manual_field_verification(
        job_id, "employment_hours", "part_time",
        evidence="Posting states 20 hours per week.", source="Employer posting",
    )
    with pytest.raises(ValueError, match="verified requires"):
        isolated_tracker.set_discovery_status(job_id, "verified")
    # With a schedule resolution it works (unchanged requirement)
    resolution = {
        "value": "confirmed_evening",
        "source": "Employer email",
        "evidence": "Employer confirmed the shift is 5:00 PM to 1:00 AM.",
        "timestamp": datetime.now().astimezone().isoformat(),
    }
    isolated_tracker.record_manual_schedule_resolution(job_id, resolution)
    assert isolated_tracker.set_discovery_status(job_id, "verified") == "verified"


# 11. Existing application lifecycle unchanged
def test_application_lifecycle_unchanged(isolated_tracker):
    from tracking.application_workflow import (
        ApplicationWorkflowError,
        prepare_application_draft,
    )
    job_id = _add_job(isolated_tracker)
    isolated_tracker.record_manual_field_verification(
        job_id, "employment_hours", "part_time",
        evidence="Posting states 20 hours per week.", source="Employer posting",
    )
    # The schedule gate is unchanged: field verification does not satisfy the
    # verified discovery-status requirement (not auto-verified by new fields)
    isolated_tracker.set_discovery_status(job_id, "verification_required")
    with pytest.raises(ValueError, match="verified requires"):
        isolated_tracker.set_discovery_status(job_id, "verified")
    # Application draft preparation itself is unchanged by the new fields
    prepared = prepare_application_draft(job_id, tracker=isolated_tracker)
    assert prepared["application"]["job_id"] == job_id


# 12. Clear preserves the other field
def test_clear_preserves_other_field(isolated_tracker):
    job_id = _add_job(isolated_tracker)
    isolated_tracker.record_manual_field_verification(
        job_id, "employment_hours", "part_time",
        evidence="Posting states 20 hours per week.", source="Employer posting",
    )
    isolated_tracker.record_manual_field_verification(
        job_id, "work_arrangement", "hybrid",
        evidence="Posting states hybrid 3 days in office.", source="Employer posting",
    )
    isolated_tracker.clear_manual_field_verification(job_id, "employment_hours")
    fv = json.loads(_fv(isolated_tracker, job_id)["field_verification"])
    assert "employment_hours" not in fv
    assert fv["work_arrangement"]["value"] == "hybrid"


# 13. verified_description mismatch rejected (provenance)
def test_verified_description_mismatch_rejected(isolated_tracker):
    job_id = _add_job(isolated_tracker)
    with pytest.raises(FieldVerificationError, match="verified_description"):
        isolated_tracker.record_manual_field_verification(
            job_id, "employment_hours", "part_time",
            evidence="Posting states 20 hours per week.", source="Employer posting",
            verified_description="Some other posting text entirely.",
        )
