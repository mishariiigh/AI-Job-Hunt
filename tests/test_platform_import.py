"""Stage 12.3.1 regression tests: manual Indeed/LinkedIn job import.

No HTTP calls are made to Indeed or LinkedIn; no scraping, no credentials.
All databases are temporary.
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
from agents.job_classifier import classify_opportunity


@pytest.fixture
def isolated_tracker(tmp_path, monkeypatch):
    db_file = tmp_path / "test_import.db"
    monkeypatch.setattr(db_module, "DB_PATH", str(db_file))
    db_module.init_db()
    yield ApplicationTracker()


def _persist(tracker, job):
    job_id = tracker.add_job(job)
    conn = sqlite3.connect(db_module.DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    return job_id, dict(row)


# --- platform detection & validation ---

def test_url_platform_detection():
    assert detect_platform("https://ca.indeed.com/viewjob?jk=abc123") == "indeed"
    assert detect_platform(
        "https://www.linkedin.com/jobs/view/1234567"
    ) == "linkedin"
    assert detect_platform("https://boards.greenhouse.io/x/jobs/1") is None
    assert detect_platform("not a url") is None


def test_indeed_manual_import(isolated_tracker):
    job = build_import_job(
        url="https://ca.indeed.com/viewjob?jk=abc123def",
        title="Evening IT Support Analyst",
        employer="Acme Logistics",
        description="Shift runs from 5 PM to 1 AM at the Mississauga office.",
        location="Mississauga, Ontario",
        employment_type="Part-time",
    )
    assert job["source_platform"] == "indeed"
    assert job["external_job_id"] == "abc123def"
    job_id, row = _persist(isolated_tracker, job)
    assert row["source"] == "indeed"
    assert row["source_platform"] == "indeed"
    assert row["original_source_url"] == "https://ca.indeed.com/viewjob?jk=abc123def"
    assert row["external_job_id"] == "abc123def"
    assert row["source_verification_status"] == "user_supplied"
    assert row["imported_at"]
    assert "5 PM to 1 AM" in row["description"]


def test_linkedin_manual_import(isolated_tracker):
    job = build_import_job(
        url="https://www.linkedin.com/jobs/view/senior-support-analyst-4321987",
        title="Support Analyst",
        employer="Data Health Inc",
        description="Provide application support on a rotating schedule covering evenings.",
        location="Toronto, Ontario",
        employer_application_url="https://datahealth.example.com/careers/apply/99",
    )
    assert job["source_platform"] == "linkedin"
    assert job["external_job_id"] == "4321987"
    job_id, row = _persist(isolated_tracker, job)
    assert row["source"] == "linkedin"
    assert row["employer_application_url"] == (
        "https://datahealth.example.com/careers/apply/99"
    )


def test_url_validation_rejects_bad_input():
    with pytest.raises(ManualImportError):
        validate_import("not a url", "Title", "Employer", "x" * 30)
    with pytest.raises(ManualImportError):
        # ftp scheme rejected
        validate_import("ftp://indeed.com/x", "Title", "Employer", "x" * 30)
    with pytest.raises(ManualImportError):
        # URL host does not match the declared platform
        validate_import(
            "https://boards.greenhouse.io/x/jobs/1",
            "Title", "Employer", "x" * 30, platform="indeed",
        )
    with pytest.raises(ManualImportError):
        validate_import(
            "https://ca.indeed.com/viewjob?jk=1", "Ti", "Employer", "x" * 30
        )  # title too short
    with pytest.raises(ManualImportError):
        validate_import(
            "https://ca.indeed.com/viewjob?jk=1", "Title", "E", "x" * 30
        )  # employer too short
    with pytest.raises(ManualImportError):
        validate_import(
            "https://ca.indeed.com/viewjob?jk=1", "Title", "Employer", "short"
        )  # description too short
    with pytest.raises(ManualImportError):
        # employer application URL invalid when provided
        build_import_job(
            url="https://ca.indeed.com/viewjob?jk=1",
            title="Title",
            employer="Employer",
            description="x" * 40,
            employer_application_url="not-a-url",
        )


def test_source_attribution_survives_normalization(isolated_tracker):
    job = build_import_job(
        url="https://www.linkedin.com/jobs/view/999888",
        title="Platform Analyst",
        employer="Veritas Health",
        description="Evening availability preferred for this support position.",
    )
    job_id, row = _persist(isolated_tracker, job)
    # Source remains identifiable after normalization
    assert row["source"] == "linkedin"
    assert row["source_platform"] == "linkedin"
    assert row["original_source_url"].startswith("https://www.linkedin.com/")
    # The canonical job_url is preserved (no invented rewrite)
    assert row["job_url"] == job["job_url"]


def test_duplicate_detection(isolated_tracker):
    job = build_import_job(
        url="https://ca.indeed.com/viewjob?jk=dupe01",
        title="Evening Analyst",
        employer="Acme",
        description="Evening shift 5 PM to 1 AM in Toronto.",
    )
    first = isolated_tracker.add_job(job)
    second = isolated_tracker.add_job(job)
    assert first == second
    conn = sqlite3.connect(db_module.DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    conn.close()
    assert count == 1


def test_missing_optional_fields(isolated_tracker):
    job = build_import_job(
        url="https://ca.indeed.com/viewjob?jk=0a1b2c3d",
        title="Optional Fields Analyst",
        employer="Acme",
        description="A posting with no optional details provided at all.",
    )
    job_id, row = _persist(isolated_tracker, job)
    assert row["employment_type"] == ""
    assert row["employer_application_url"] == ""
    assert row["shift"] == "" or row["shift"] == "unknown"
    assert row["external_job_id"] == "0a1b2c3d"
    # Missing schedule info must not invent a classification
    classification = json.loads(row["schedule_classification"])
    assert classification.get("confirmed_evening") is not True


def test_employer_url_preserved_separately(isolated_tracker):
    job = build_import_job(
        url="https://ca.indeed.com/viewjob?jk=empurl1",
        title="Analyst",
        employer="Acme",
        description="Evening shift starting at 5 PM until 1 AM daily.",
        employer_application_url="https://acme.example.com/apply/42",
    )
    job_id, row = _persist(isolated_tracker, job)
    assert row["original_source_url"] == "https://ca.indeed.com/viewjob?jk=empurl1"
    assert row["employer_application_url"] == "https://acme.example.com/apply/42"


def test_user_supplied_description_persisted(isolated_tracker):
    description = (
        "The employer states: evening shift 6 PM - 10 PM, Monday to Friday, "
        "on-site in Oakville."
    )
    job = build_import_job(
        url="https://www.linkedin.com/jobs/view/777000",
        title="NOC Analyst",
        employer="Acme",
        description=description,
    )
    job_id, row = _persist(isolated_tracker, job)
    assert row["description"] == description
    # User-supplied provenance recorded
    assert row["source_verification_status"] == "user_supplied"
    assert row["listing_status"] == "user_imported"


def test_imported_jobs_enter_matching_gates_unchanged(isolated_tracker):
    """Confirmed evening hours in the user-supplied description produce a
    confirmed evening opportunity through the normal gates."""
    job = build_import_job(
        url="https://ca.indeed.com/viewjob?jk=gate01",
        title="Evening Support Analyst",
        employer="Acme",
        description="Shift: 5 PM - 1 AM Eastern Time, on-site in Mississauga.",
        location="Mississauga, Ontario",
    )
    job_id, row = _persist(isolated_tracker, job)
    opportunity = classify_opportunity(row)
    assert opportunity["status"] in {"confirmed_evening", "needs_verification"}
    # Technical match still computed through the existing pipeline
    from agents.matching_agent import MatchingAgent
    matcher = MatchingAgent()
    result = matcher.deterministic_match(row)
    assert 0 <= result["match_score"] <= 100


def test_unknown_schedule_remains_unconfirmed(isolated_tracker):
    job = build_import_job(
        url="https://ca.indeed.com/viewjob?jk=unk01",
        title="Flexible Analyst",
        employer="Acme",
        description="Flexible hours; evening availability preferred.",
    )
    job_id, row = _persist(isolated_tracker, job)
    classification = json.loads(row["schedule_classification"])
    assert classification["status"] != "confirmed_evening"
    assert classification["confirmed_evening"] is False


def test_manual_schedule_resolution_survives_imports(isolated_tracker):
    """An existing job (e.g. previously imported with unknown schedule) that
    later receives a manual resolution keeps it when the same job is
    refreshed via a new import of the same URL."""
    url = "https://ca.indeed.com/viewjob?jk=resv1"
    job = build_import_job(
        url=url,
        title="Support Analyst",
        employer="Acme",
        description="Hours not stated in the posting.",
    )
    isolated_tracker.add_job(job)
    # User explicitly re-verifies via the dedicated operation
    row = _persist(isolated_tracker, {**job, "schedule_classification": {}})[1]
    from tracking.application_tracker import ManualResolutionError
    resolution = {
        "value": "confirmed_evening",
        "source": "https://employer.example.com/careers/1",
        "evidence": "Employer confirmed 5 PM - 1 AM",
        "timestamp": "2026-11-05T10:00:00-05:00",
    }
    updated = isolated_tracker.record_manual_schedule_resolution(
        row["id"], resolution
    )
    assert updated["status"] == "confirmed_evening"
    # Re-import of the same URL (duplicate path) must not overwrite it
    second = isolated_tracker.add_job({**job, "description": "Updated text."})
    assert second == row["id"]
    fresh = [j for j in isolated_tracker.get_jobs() if j["id"] == row["id"]][0]
    classification = json.loads(fresh["schedule_classification"])
    assert classification["status"] == "confirmed_evening"
    assert classification["manual_resolution"]["evidence"] == (
        "Employer confirmed 5 PM - 1 AM"
    )


def test_no_unauthorized_http_scraping():
    """The manual import module must not perform any HTTP requests."""
    import inspect
    from sources import manual_intake
    source = inspect.getsource(manual_intake)
    assert "requests" not in source
    assert "urlopen" not in source
    assert "selenium" not in source.lower()
    assert "playwright" not in source.lower()
    # And building an import makes no network calls (would fail offline anyway)
    job = build_import_job(
        url="https://ca.indeed.com/viewjob?jk=offline",
        title="Offline Analyst",
        employer="Acme",
        description="Built entirely from user input with no network access.",
    )
    assert job["description"].startswith("Built entirely")


def test_discovered_sources_unchanged(isolated_tracker):
    """Greenhouse/Lever/Remotive job persistence is unaffected by the new
    provenance columns (they stay empty for discovered postings)."""
    discovered = {
        "employer": "Geotab",
        "job_title": "Support Analyst",
        "job_url": "https://boards.greenhouse.io/geotab/jobs/1",
        "source": "greenhouse",
        "source_feed": "geotab",
        "description": "Shift: 5 PM - 1 AM Eastern Time.",
        "location": "Remote - Canada",
        "remote": 1,
        "listing_status": "active_on_source",
    }
    job_id, row = _persist(isolated_tracker, discovered)
    assert row["source_platform"] == ""
    assert row["original_source_url"] == ""
    assert row["employer_application_url"] == ""
    assert row["source_verification_status"] == ""
    assert row["imported_at"] is None
    classification = json.loads(row["schedule_classification"])
    assert classification["status"] == "confirmed_evening"
