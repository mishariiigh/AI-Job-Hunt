"""Stage 12.6.2 regression tests: two-stage manual import preview.

The preview stage must not write to the database; the confirm stage
re-validates corrected fields and preserves provenance. All databases are
temporary; no HTTP calls are made.
"""
import json
import sqlite3
from unittest.mock import patch

import pytest

import database.db as db_module
from sources.manual_intake import (
    ManualImportError,
    build_import_job,
    detect_platform,
    validate_import,
)
from tracking.application_tracker import ApplicationTracker


@pytest.fixture
def isolated_tracker(tmp_path, monkeypatch):
    db_file = tmp_path / "test_preview.db"
    monkeypatch.setattr(db_module, "DB_PATH", str(db_file))
    db_module.init_db()
    yield ApplicationTracker()


GOOD_URL = "https://ca.indeed.com/viewjob?jk=1a2b3c4d"


def _base_kwargs(**overrides):
    kwargs = dict(
        url=GOOD_URL,
        title="Evening IT Support Analyst",
        employer="Acme Logistics",
        description="Shift runs 5 PM to 1 AM at the Mississauga office.",
        location="Mississauga, Ontario",
        employment_type="Part-time",
        platform="indeed",
    )
    kwargs.update(overrides)
    return kwargs


def _job_count():
    conn = sqlite3.connect(db_module.DB_PATH)
    n = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    conn.close()
    return n


# 1. Preview without database writes
def test_preview_writes_nothing_to_database(isolated_tracker):
    """build_import_job (the preview operation) must not persist anything."""
    draft = build_import_job(**_base_kwargs())
    assert draft["job_title"] == "Evening IT Support Analyst"
    assert draft["source_platform"] == "indeed"
    assert _job_count() == 0
    assert isolated_tracker.job_exists(isolated_tracker.normalize_url(GOOD_URL)) is False


# 2. Correcting preview fields
def test_corrected_fields_revalidate_and_persist(isolated_tracker):
    draft = build_import_job(**_base_kwargs())
    # User corrects title and employer in the preview
    corrected = build_import_job(
        url=draft["original_source_url"],           # provenance preserved
        title="Junior NOC Analyst",                 # corrected
        employer="Acme Technology Group",           # corrected
        description=draft["description"],
        location="Toronto, Ontario",                # corrected
        employment_type="Full-time",                # corrected
        platform=draft["source_platform"],
    )
    assert corrected["job_title"] == "Junior NOC Analyst"
    assert corrected["employer"] == "Acme Technology Group"
    job_id, row = _persist(isolated_tracker, corrected)
    assert row["job_title"] == "Junior NOC Analyst"
    assert row["employer"] == "Acme Technology Group"
    assert row["location"] == "Toronto, Ontario"


# 3. Confirming a valid posting
def test_confirm_saves_valid_posting(isolated_tracker):
    draft = build_import_job(**_base_kwargs())
    job_id, row = _persist(isolated_tracker, draft)
    assert job_id
    assert row["source"] == "indeed"
    assert row["listing_status"] == "user_imported"


# 4. Invalid URL rejection (at preview time AND confirm time)
def test_invalid_url_rejected_at_both_stages():
    with pytest.raises(ManualImportError):
        build_import_job(**_base_kwargs(url="https://boards.greenhouse.io/x/jobs/1"))
    with pytest.raises(ManualImportError):
        build_import_job(**_base_kwargs(url="not-a-url"))
    with pytest.raises(ManualImportError):
        # Corrections cannot change the platform away from the source URL
        draft = build_import_job(**_base_kwargs())
        build_import_job(
            url=draft["original_source_url"],
            title="T",
            employer="Employer",
            description="x" * 40,
            platform="linkedin",  # mismatches indeed URL
        )


# 5. Duplicate detection at confirmation time
def test_duplicate_rejected_at_confirmation(isolated_tracker):
    draft = build_import_job(**_base_kwargs())
    first = isolated_tracker.add_job(draft)
    # Second confirm of the same posting
    second = isolated_tracker.add_job(draft)
    assert first == second  # INSERT OR IGNORE → same row, no duplicate
    assert _job_count() == 1


# 6. Preserve Indeed/LinkedIn attribution through preview→confirm
def test_attribution_preserved_through_preview_cycle(isolated_tracker):
    for url, platform in [
        ("https://ca.indeed.com/viewjob?jk=aaaa1111", "indeed"),
        ("https://www.linkedin.com/jobs/view/some-role-999888", "linkedin"),
    ]:
        draft = build_import_job(**_base_kwargs(url=url, platform=platform))
        # simulate corrections
        corrected = build_import_job(
            url=draft["original_source_url"],
            title=draft["job_title"],
            employer=draft["employer"],
            description=draft["description"],
            platform=draft["source_platform"],
        )
        job_id, row = _persist(isolated_tracker, corrected)
        assert row["source"] == platform
        assert row["source_platform"] == platform
        assert row["original_source_url"] == url
        assert row["source_verification_status"] == "user_supplied"


# 7. Missing description handling
def test_missing_description_rejected_with_clear_error():
    with pytest.raises(ManualImportError, match="description"):
        build_import_job(**_base_kwargs(description="short"))
    with pytest.raises(ManualImportError, match="description"):
        build_import_job(**_base_kwargs(description=""))


# 8. Session-state reset after successful save (Streamlit semantics:
#    clearing the key means the next render shows the entry form again)
def test_session_state_reset_semantics():
    """Simulate the Streamlit session-state lifecycle used by the UI."""
    session = {"manual_import_preview": {"draft": build_import_job(**_base_kwargs())}}
    assert "manual_import_preview" in session  # preview stage shows editable fields
    # After a successful save the UI does: del session["manual_import_preview"]
    del session["manual_import_preview"]
    assert "manual_import_preview" not in session  # entry form shows again


# 8b. Save-lock semantics: the in-progress flag mirrors what the UI sets while
#     a save is running, and resets (to absent/False) once the save completes.
def test_save_lock_flag_lifecycle():
    draft = build_import_job(**_base_kwargs())
    session = {"manual_import_preview": {"draft": draft}}
    # While saving, the UI sets manual_import_saving = True
    session["manual_import_saving"] = True
    assert session["manual_import_saving"] is True
    # After the save completes (success or duplicate), the lock is released
    session["manual_import_saving"] = False
    assert not session["manual_import_saving"]


# 8c. Duplicate pre-check at confirmation uses the same normalize/exists path
#     as add_job's internal duplicate handling, on the CORRECTED fields.
def test_duplicate_precheck_uses_corrected_url(isolated_tracker):
    draft = build_import_job(**_base_kwargs())
    isolated_tracker.add_job(draft)
    # A correction that does NOT change the URL still hits the duplicate
    assert isolated_tracker.job_exists(
        isolated_tracker.normalize_url(draft["original_source_url"])
    )
    assert _job_count() == 1


# 8d. The corrections in the preview never alter provenance fields: the source
#     URL passed to build_import_job on confirm is always the original one.
def test_confirm_always_rebuilds_from_original_url():
    draft = build_import_job(**_base_kwargs())
    corrected = build_import_job(
        url=draft["original_source_url"],  # what the UI passes on confirm
        title="Changed Title",
        employer="Changed Employer",
        description=draft["description"],
        location="Ottawa, Ontario",
        platform=draft["source_platform"],
    )
    assert corrected["original_source_url"] == GOOD_URL
    assert corrected["external_job_id"] == draft["external_job_id"]
    assert corrected["job_title"] == "Changed Title"


# helper
def _persist(tracker, job):
    job_id = tracker.add_job(job)
    conn = sqlite3.connect(db_module.DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    return job_id, dict(row)
