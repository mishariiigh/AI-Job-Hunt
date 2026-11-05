"""Stage 12.2 regression tests: schedule classification persisted at ingest.

Uses isolated temporary databases and mocked discovery sources; the
production database is never touched.
"""
import json
import sqlite3

import pytest

import database.db as db_module
from agents.discovery_agent import DiscoveryAgent
from tracking.application_tracker import ApplicationTracker


@pytest.fixture
def isolated_tracker(tmp_path, monkeypatch):
    db_file = tmp_path / "test_jobs.db"
    monkeypatch.setattr(db_module, "DB_PATH", str(db_file))
    db_module.init_db()
    yield ApplicationTracker()


def _rows(tracker, url):
    conn = sqlite3.connect(db_module.DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM jobs WHERE job_url = ?", (url,)
    ).fetchone()
    conn.close()
    return row


def _insert_evening_job(tracker, url="https://jobs.example.com/evening"):
    return tracker.add_job({
        "employer": "Example Corp",
        "job_title": "Evening Support Analyst",
        "job_url": url,
        "source": "greenhouse",
        "description": "Shift: 5 PM - 1 AM Eastern Time.",
        "location": "Remote - Canada",
        "remote": 1,
        "listing_status": "active_on_source",
    })


def test_new_job_insertion_stores_populated_classification(isolated_tracker):
    job_id = _insert_evening_job(isolated_tracker)
    assert job_id
    row = _rows(isolated_tracker, "https://jobs.example.com/evening")
    classification = json.loads(row["schedule_classification"])
    assert classification["status"] == "confirmed_evening"
    assert classification["start_time"] == "17:00"
    assert classification["timezone"] == "America/Toronto"
    assert classification["evidence"]


def test_refresh_updates_classification_when_schedule_evidence_changes(
    isolated_tracker,
):
    _insert_evening_job(isolated_tracker)
    isolated_tracker.refresh_job_listing({
        "employer": "Example Corp",
        "job_title": "Evening Support Analyst",
        "job_url": "https://jobs.example.com/evening",
        "source": "greenhouse",
        # Employer now publishes daytime hours
        "description": "Shift changed: 9 AM - 5 PM Eastern Time.",
        "location": "Remote - Canada",
        "remote": 1,
        "listing_status": "active_on_source",
    })
    row = _rows(isolated_tracker, "https://jobs.example.com/evening")
    classification = json.loads(row["schedule_classification"])
    assert classification["status"] == "incompatible"
    assert classification["start_time"] == "09:00"


def test_unchanged_refresh_preserves_correct_classification(isolated_tracker):
    _insert_evening_job(isolated_tracker)
    before = _rows(isolated_tracker, "https://jobs.example.com/evening")
    isolated_tracker.refresh_job_listing({
        "employer": "Example Corp",
        "job_title": "Evening Support Analyst",
        "job_url": "https://jobs.example.com/evening",
        "source": "greenhouse",
        "description": "Shift: 5 PM - 1 AM Eastern Time.",
        "location": "Remote - Canada",
        "remote": 1,
        "listing_status": "active_on_source",
    })
    after = _rows(isolated_tracker, "https://jobs.example.com/evening")
    assert json.loads(after["schedule_classification"]) == json.loads(
        before["schedule_classification"]
    )


def test_unknown_schedule_persists_as_needs_verification(isolated_tracker):
    isolated_tracker.add_job({
        "employer": "Example Corp",
        "job_title": "Support Analyst",
        "job_url": "https://jobs.example.com/unknown",
        "source": "greenhouse",
        "description": "Great team and interesting work.",
        "location": "Remote - Canada",
        "remote": 1,
        "listing_status": "active_on_source",
    })
    row = _rows(isolated_tracker, "https://jobs.example.com/unknown")
    classification = json.loads(row["schedule_classification"])
    assert classification["status"] == "unknown"
    assert classification["needs_schedule_verification"] is True
    assert classification["confirmed_evening"] is False


@pytest.mark.parametrize(
    "description",
    [
        "Flexible hours; evening availability preferred.",
        "Rotating shift schedule between day and evening coverage.",
        "Provide on-call support with evening escalations.",
        "Support a 24/7 operations environment.",
        "After-hours support rotation for global teams.",
    ],
)
def test_vague_schedule_language_never_becomes_confirmed_evening(
    isolated_tracker, description,
):
    isolated_tracker.add_job({
        "employer": "Example Corp",
        "job_title": "Support Analyst",
        "job_url": f"https://jobs.example.com/{abs(hash(description))}",
        "source": "greenhouse",
        "description": description,
        "location": "Remote - Canada",
        "remote": 1,
        "listing_status": "active_on_source",
    })
    # Recompute URL deterministically for lookup
    url = f"https://jobs.example.com/{abs(hash(description))}"
    row = _rows(isolated_tracker, url)
    classification = json.loads(row["schedule_classification"])
    assert classification["status"] != "confirmed_evening"
    assert classification["confirmed_evening"] is False


def test_verified_5pm_start_classified_correctly(isolated_tracker):
    _insert_evening_job(isolated_tracker)
    row = _rows(isolated_tracker, "https://jobs.example.com/evening")
    classification = json.loads(row["schedule_classification"])
    assert classification["status"] == "confirmed_evening"


def test_manual_schedule_resolution_is_not_overwritten(isolated_tracker):
    manual = {
        "status": "confirmed_evening",
        "schedule_type": "confirmed_evening",
        "start_time": "17:00",
        "end_time": "01:00",
        "timezone": "America/Toronto",
        "manual_resolution": {
            "value": "confirmed_evening",
            "source": "https://employer.example.com/careers/job-1",
            "evidence": "Employer confirmed shift 5 PM - 1 AM by email",
            "timestamp": "2026-01-01T12:00:00-05:00",
        },
    }
    isolated_tracker.add_job({
        "employer": "Example Corp",
        "job_title": "Support Analyst",
        "job_url": "https://jobs.example.com/manual",
        "source": "greenhouse",
        "description": "Hours not stated in posting.",
        "location": "Remote - Canada",
        "remote": 1,
        "listing_status": "active_on_source",
        "schedule_classification": manual,
    })
    # Refresh with a description that does NOT state qualifying hours:
    # the manual resolution must survive.
    isolated_tracker.refresh_job_listing({
        "employer": "Example Corp",
        "job_title": "Support Analyst",
        "job_url": "https://jobs.example.com/manual",
        "source": "greenhouse",
        "description": "Hours not stated in posting.",
        "location": "Remote - Canada",
        "remote": 1,
        "listing_status": "active_on_source",
        "schedule_classification": manual,
    })
    row = _rows(isolated_tracker, "https://jobs.example.com/manual")
    classification = json.loads(row["schedule_classification"])
    assert classification["status"] == "confirmed_evening"
    assert classification["manual_resolution"]["value"] == "confirmed_evening"


def test_discovery_persists_classification_through_add_and_refresh(
    isolated_tracker, monkeypatch,
):
    """End-to-end with mocked sources: ingest + refresh path persists
    classification, and recommendation behavior is unchanged."""
    agent = DiscoveryAgent()
    job = {
        "employer": "Mock Corp",
        "job_title": "NOC Technician",
        "job_url": "https://jobs.example.com/noc",
        "source": "greenhouse",
        "source_feed": "mock",
        "description": "Evening shift 6 PM - 10 PM Eastern Time monitoring.",
        "location": "Remote - Canada",
        "remote": 1,
        "listing_status": "active_on_source",
    }
    passed, _ = agent.filter_job(dict(job))
    assert passed
    # filter_job itself attaches the classification
    prepared = dict(job)
    agent.filter_job(prepared)
    assert prepared["schedule_classification"]["status"] == "confirmed_evening"
    job_id = isolated_tracker.add_job(prepared)
    row = _rows(isolated_tracker, "https://jobs.example.com/noc")
    classification = json.loads(row["schedule_classification"])
    assert classification["status"] == "confirmed_evening"
    assert classification["start_time"] == "18:00"
    # Recommendation classification from the stored row agrees
    stored = dict(row)
    from agents.job_classifier import classify_opportunity
    opportunity = classify_opportunity(stored)
    assert opportunity["status"] in {"confirmed_evening", "needs_verification"}
