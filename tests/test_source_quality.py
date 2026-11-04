import sqlite3

from agents.discovery_agent import DiscoveryAgent
from database import db
from tracking.application_tracker import ApplicationTracker


def _job(job_url, **overrides):
    return {
        "employer": "Example Technical Co.",
        "job_title": "Application Support Analyst",
        "job_url": job_url,
        "source": "greenhouse",
        "source_feed": "example",
        "description": "Provide application support to Canadian customers.",
        "location": "Remote, Canada",
        "remote": True,
        "shift": "unknown",
        "employment_type": "Part-time",
        "posting_date": "2026-11-02T10:00:00",
        "last_verified_at": "2026-11-04T10:00:00-05:00",
        "listing_status": "active_on_source",
        **overrides,
    }


def test_source_snapshots_refresh_existing_jobs_without_creating_duplicates():
    tracker = ApplicationTracker()
    first = _job("https://jobs.example.com/role/1")
    first_id = tracker.add_job(first)
    second = _job("https://jobs.example.com/role/2")
    second_id = tracker.add_job(second)

    assert first_id != second_id
    records = tracker.get_jobs()
    assert all(record["possible_repost_count"] == 2 for record in records)

    tracker.update_source_snapshot(
        "greenhouse",
        "example",
        [first["job_url"]],
        "2026-11-04T11:00:00-05:00",
    )
    refreshed = tracker.get_jobs()
    first_record = next(record for record in refreshed if record["id"] == first_id)
    second_record = next(record for record in refreshed if record["id"] == second_id)

    assert first_record["listing_status"] == "active_on_source"
    assert second_record["listing_status"] == "not_listed_on_source"
    assert second_record["last_verified_at"] == "2026-11-04T11:00:00-05:00"


def test_discovery_updates_known_listing_instead_of_reporting_it_as_new(monkeypatch):
    agent = DiscoveryAgent()
    current_job = _job("https://jobs.example.com/role/current")
    status = {
        "board": "example",
        "status": "ok",
        "error": None,
        "retrieved": 1,
    }

    class Feed:
        def search(self, _boards):
            return {"jobs": [current_job], "statuses": [status]}

    class EmptyFeed:
        def search(self, _boards):
            return {"jobs": [], "statuses": []}

    class EmptyRemotive:
        def search(self):
            return {
                "jobs": [],
                "status": "cached",
                "error": None,
                "warnings": [],
                "retrieved": 0,
                "last_checked": "2026-11-04T10:00:00+00:00",
            }

    class Matcher:
        def score_job(self, _job):
            return {}

        def save_match(self, _job_id, _result):
            return None

    monkeypatch.setattr(agent, "greenhouse", Feed())
    monkeypatch.setattr(agent, "lever", EmptyFeed())
    monkeypatch.setattr(agent, "remotive", EmptyRemotive())
    monkeypatch.setattr("agents.matching_agent.MatchingAgent", Matcher)

    first, first_stats = agent.discover(["example"], [])
    assert len(first) == 1
    assert first_stats["new_saved"] == 1

    current_job["description"] = "Updated description with current application support details."
    current_job["source_updated_at"] = "2026-11-04T11:30:00-05:00"
    second, second_stats = agent.discover(["example"], [])
    saved = agent.tracker.get_job(first[0]["id"])

    assert second == []
    assert second_stats["new_saved"] == 0
    assert second_stats["previously_known"] == 1
    assert "Updated description" in saved["description"]
    assert saved["listing_status"] == "active_on_source"


def test_incomplete_feed_does_not_mark_unseen_jobs_as_missing(monkeypatch):
    agent = DiscoveryAgent()
    existing = _job("https://jobs.example.com/role/current")
    job_id = agent.tracker.add_job(existing)
    original = agent.tracker.get_job(job_id)

    class IncompleteFeed:
        def search(self, _boards):
            return {
                "jobs": [],
                "statuses": [
                    {
                        "board": "example",
                        "status": "error",
                        "retrieved": 0,
                        "error": "Source snapshot incomplete",
                    }
                ],
            }

    class EmptyFeed:
        def search(self, _boards):
            return {"jobs": [], "statuses": []}

    class EmptyRemotive:
        def search(self):
            return {
                "jobs": [],
                "status": "cached",
                "error": None,
                "warnings": [],
                "retrieved": 0,
                "last_checked": "2026-11-04T10:00:00+00:00",
            }

    monkeypatch.setattr(agent, "greenhouse", IncompleteFeed())
    monkeypatch.setattr(agent, "lever", EmptyFeed())
    monkeypatch.setattr(agent, "remotive", EmptyRemotive())

    agent.discover(["example"], [])
    updated = agent.tracker.get_job(job_id)

    assert updated["listing_status"] == original["listing_status"]
    assert updated["last_verified_at"] == original["last_verified_at"]


def test_discovery_keeps_uncertain_remote_jobs_for_analysis_but_rejects_bad_fit():
    agent = DiscoveryAgent()
    unknown_remote = {
        "job_title": "Cloud Support Engineer",
        "location": "Remote",
        "remote": True,
        "description": "Technical support for cloud systems.",
        "job_url": "https://jobs.example.com/remote",
    }
    rejected_location = {
        "job_title": "Software Developer",
        "location": "Toronto, Ontario",
        "remote": False,
        "description": "Software development.",
        "job_url": "https://jobs.example.com/toronto",
    }
    rejected_language = {
        "job_title": "IT Support Specialist",
        "location": "Remote, Canada",
        "remote": True,
        "description": "French language skills are required.",
        "job_url": "https://jobs.example.com/french",
    }

    assert agent.filter_job(unknown_remote) == (True, "Passed")
    assert unknown_remote["job_category"] == "IT and application support"
    assert agent.filter_job(rejected_location)[0] is False
    assert agent.filter_job(rejected_language) == (False, "French required")


def test_legacy_job_schema_migration_adds_freshness_and_feed_fields(tmp_path, monkeypatch):
    legacy_db = tmp_path / "legacy.db"
    monkeypatch.setattr(db, "DB_PATH", str(legacy_db))
    connection = sqlite3.connect(legacy_db)
    connection.execute(
        """
        CREATE TABLE jobs (
            id INTEGER PRIMARY KEY,
            employer TEXT,
            job_title TEXT,
            job_url TEXT,
            source TEXT,
            discovered_at TEXT
        )
        """
    )
    connection.execute(
        """
        INSERT INTO jobs (employer, job_title, job_url, source, discovered_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            "Stripe",
            "Support Engineer",
            "https://jobs.example.com/stripe",
            "greenhouse",
            "2026-11-03T10:00:00",
        ),
    )
    connection.commit()
    connection.close()

    db.init_db()
    connection = db.get_conn()
    try:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(jobs)")
        }
        migrated = connection.execute(
            "SELECT source_feed, last_verified_at, listing_status FROM jobs"
        ).fetchone()
    finally:
        connection.close()

    assert {
        "job_category",
        "source_feed",
        "source_updated_at",
        "last_verified_at",
        "listing_status",
        "schedule_classification",
        "repost_group_key",
    } <= columns
    assert migrated["source_feed"] == "stripe"
    assert migrated["last_verified_at"] == "2026-11-03T10:00:00"
    assert migrated["listing_status"] == "active_on_source"
