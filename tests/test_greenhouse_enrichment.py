"""Stage 12.3 regression tests: Greenhouse detail enrichment.

All HTTP is mocked; all databases are temporary. Lever and Remotive are
verified unaffected. Production data is never touched.
"""
import json
import sqlite3
from unittest.mock import patch, MagicMock

import pytest

import database.db as db_module
import sources.greenhouse as gh
from sources.greenhouse import (
    GreenhouseSource,
    fetch_job_detail,
    _extract_employment_type,
    _extract_offices,
    _extract_metadata_fields,
)
from tracking.application_tracker import ApplicationTracker


@pytest.fixture
def isolated_tracker(tmp_path, monkeypatch):
    db_file = tmp_path / "test_enrich.db"
    monkeypatch.setattr(db_module, "DB_PATH", str(db_file))
    db_module.init_db()
    yield ApplicationTracker()


FEED_PAYLOAD = {
    "jobs": [
        {
            "id": 12345,
            "title": "Evening Support Analyst",
            "absolute_url": "https://boards.greenhouse.io/acme-corp/jobs/12345",
            "content": "<p>Shift: 5 PM - 1 AM Eastern Time.</p>",
            "location": {"name": "Remote - Canada"},
            "offices": [{"name": "Toronto"}, {"name": "Remote"}],
            "metadata": [
                {"name": "Employment Type", "value": "Part-time"},
                {"name": "Education", "value": "Diploma in Computer Programming"},
            ],
            "first_published": "2026-01-02T10:00:00-05:00",
            "updated_at": "2026-01-04T08:00:00-05:00",
            "close_date": "2026-02-01T00:00:00-05:00",
        }
    ]
}


def _mock_feed(payload):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = payload
    return response


# --- helpers: endpoint construction and field extraction ---

def test_detail_endpoint_construction():
    assert (
        "https://boards-api.greenhouse.io/v1/boards/d2l/jobs/7696196?content=true"
        == _detail_url("d2l", 7696196)
    )


def _detail_url(token, job_id):
    # Exercise the real function by capturing the URL it requests
    with patch("sources.greenhouse.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {}
        fetch_job_detail(token, job_id)
        url = mock_get.call_args[0][0]
    return url


def test_extract_employment_type_from_metadata():
    assert (
        _extract_employment_type([{"name": "Employment Type", "value": "Part-time"}])
        == "Part-time"
    )


def test_extract_offices():
    assert (
        _extract_offices([{"name": "Toronto"}, {"name": "Remote"}, {"name": "Toronto"}])
        == "Toronto; Remote"
    )


def test_extract_metadata_education_and_experience():
    fields = _extract_metadata_fields([
        {"name": "Employment Type", "value": "Full-time"},
        {"name": "Education Level", "value": "College diploma"},
        {"name": "Years of Experience", "value": "3+"},
    ])
    assert fields == {
        "employment_type": "Full-time",
        "education_required": "College diploma",
        "experience_required": "3+",
    }


# --- feed mapping ---

def test_feed_mapping_publication_date(isolated_tracker):
    source = GreenhouseSource()
    with patch("sources.greenhouse.requests.get", return_value=_mock_feed(FEED_PAYLOAD)):
        result = source.search_board("acme-corp")
    job = result["jobs"][0]
    assert job["posting_date"].startswith("2026-01-02")


def test_feed_mapping_application_deadline(isolated_tracker):
    source = GreenhouseSource()
    with patch("sources.greenhouse.requests.get", return_value=_mock_feed(FEED_PAYLOAD)):
        result = source.search_board("acme-corp")
    assert result["jobs"][0]["deadline"].startswith("2026-02-01")


def test_feed_mapping_offices(isolated_tracker):
    source = GreenhouseSource()
    with patch("sources.greenhouse.requests.get", return_value=_mock_feed(FEED_PAYLOAD)):
        result = source.search_board("acme-corp")
    assert result["jobs"][0]["office_locations"] == "Toronto; Remote"


def test_feed_persists_metadata_and_employment_type(isolated_tracker):
    source = GreenhouseSource()
    with patch("sources.greenhouse.requests.get", return_value=_mock_feed(FEED_PAYLOAD)):
        result = source.search_board("acme-corp")
    job = result["jobs"][0]
    isolated_tracker.add_job(job)
    conn = sqlite3.connect(db_module.DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM jobs WHERE job_url = ?",
        (job["job_url"],),
    ).fetchone()
    conn.close()
    assert row["employment_type"] == "Part-time"
    assert row["education_required"] == "Diploma in Computer Programming"
    assert json.loads(row["gh_metadata"])[0]["value"] == "Part-time"
    assert row["gh_job_id"] == "12345" or row["gh_job_id"] == 12345 or str(row["gh_job_id"]) == "12345"
    assert row["office_locations"] == "Toronto; Remote"
    assert row["enriched_at"]


# --- error handling and fallbacks ---

def test_missing_optional_fields_produce_empty_not_none(isolated_tracker):
    source = GreenhouseSource()
    minimal = {"jobs": [{
        "id": 1,
        "title": "T",
        "absolute_url": "https://boards.greenhouse.io/acme-corp/jobs/1",
        "content": "text",
        "location": {"name": "Remote"},
        # no metadata, offices, first_published, close_date
    }]}
    with patch("sources.greenhouse.requests.get", return_value=_mock_feed(minimal)):
        result = source.search_board("acme-corp")
    job = result["jobs"][0]
    assert job["office_locations"] == ""
    assert job["gh_metadata"] == ""
    assert job["employment_type"] == ""
    assert job["posting_date"] in ("", None)
    assert job["deadline"] in ("", None)


def test_detail_fetch_malformed_json_returns_none():
    response = MagicMock()
    response.status_code = 200
    response.json.side_effect = ValueError("bad json")
    with patch("sources.greenhouse.requests.get", return_value=response):
        assert fetch_job_detail("acme-corp", 1) is None


def test_detail_fetch_404_returns_none():
    response = MagicMock()
    response.status_code = 404
    with patch("sources.greenhouse.requests.get", return_value=response):
        assert fetch_job_detail("acme-corp", 1) is None


def test_detail_fetch_429_returns_none():
    response = MagicMock()
    response.status_code = 429
    with patch("sources.greenhouse.requests.get", return_value=response):
        assert fetch_job_detail("acme-corp", 1) is None


def test_detail_fetch_500_returns_none():
    response = MagicMock()
    response.status_code = 500
    with patch("sources.greenhouse.requests.get", return_value=response):
        assert fetch_job_detail("acme-corp", 1) is None


def test_detail_fetch_network_timeout_returns_none():
    import requests as requests_module
    with patch(
        "sources.greenhouse.requests.get",
        side_effect=requests_module.exceptions.Timeout(),
    ):
        assert fetch_job_detail("acme-corp", 1) is None


def test_enrichment_failure_preserves_feed_record(isolated_tracker):
    """A job with no metadata/offices is still stored complete from the feed."""
    source = GreenhouseSource()
    with patch("sources.greenhouse.requests.get", return_value=_mock_feed(FEED_PAYLOAD)):
        result = source.search_board("acme-corp")
    job = dict(result["jobs"][0])
    job.pop("gh_metadata")
    job.pop("office_locations")
    job.pop("gh_job_id")
    job_id = isolated_tracker.add_job(job)
    assert job_id
    conn = sqlite3.connect(db_module.DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT description, employment_type, schedule_classification FROM jobs WHERE id = ?",
        (job_id,),
    ).fetchone()
    conn.close()
    assert "5 PM - 1 AM" in row["description"]
    classification = json.loads(row["schedule_classification"])
    assert classification["status"] == "confirmed_evening"


def test_duplicate_prevention(isolated_tracker):
    source = GreenhouseSource()
    with patch("sources.greenhouse.requests.get", return_value=_mock_feed(FEED_PAYLOAD)):
        result = source.search_board("acme-corp")
    job = result["jobs"][0]
    first = isolated_tracker.add_job(job)
    second = isolated_tracker.add_job(job)
    assert first == second
    conn = sqlite3.connect(db_module.DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    conn.close()
    assert count == 1


def test_enriched_fields_not_overwritten_by_empty(isolated_tracker):
    """A refresh carrying empty enrichment fields must not clobber existing data."""
    source = GreenhouseSource()
    with patch("sources.greenhouse.requests.get", return_value=_mock_feed(FEED_PAYLOAD)):
        result = source.search_board("acme-corp")
    job = result["jobs"][0]
    isolated_tracker.add_job(job)
    # Refresh with a payload missing all enrichment fields
    degraded = dict(job)
    degraded["gh_metadata"] = ""
    degraded["office_locations"] = ""
    degraded["gh_job_id"] = ""
    isolated_tracker.refresh_job_listing(degraded)
    conn = sqlite3.connect(db_module.DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM jobs WHERE job_url = ?", (job["job_url"],)
    ).fetchone()
    conn.close()
    assert row["office_locations"] == "Toronto; Remote"
    assert row["gh_metadata"] != ""
    assert row["gh_job_id"] != ""
    assert row["enriched_at"]


def test_manual_resolution_survives_enrichment_refresh(isolated_tracker):
    url = "https://boards.greenhouse.io/acme-corp/jobs/12345"
    manual = {
        "status": "confirmed_evening",
        "schedule_type": "confirmed_evening",
        "manual_resolution": {
            "value": "confirmed_evening",
            "source": "https://employer.example.com/careers/1",
            "evidence": "Employer confirmed evening shift",
            "timestamp": "2026-01-05T10:00:00-05:00",
        },
    }
    isolated_tracker.add_job({
        "employer": "Example Corp",
        "job_title": "Support Analyst",
        "job_url": url,
        "source": "greenhouse",
        "description": "Hours not stated.",
        "location": "Remote - Canada",
        "remote": 1,
        "listing_status": "active_on_source",
        "schedule_classification": manual,
        "gh_job_id": 12345,
        "gh_metadata": json.dumps(FEED_PAYLOAD["jobs"][0]["metadata"]),
        "office_locations": "Toronto; Remote",
    })
    isolated_tracker.refresh_job_listing({
        "employer": "Example Corp",
        "job_title": "Support Analyst",
        "job_url": url,
        "source": "greenhouse",
        "description": "Hours not stated.",
        "location": "Remote - Canada",
        "remote": 1,
        "listing_status": "active_on_source",
        "gh_job_id": 12345,
        "gh_metadata": json.dumps(FEED_PAYLOAD["jobs"][0]["metadata"]),
        "office_locations": "Toronto; Remote",
    })
    conn = sqlite3.connect(db_module.DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT schedule_classification, gh_metadata, office_locations FROM jobs WHERE job_url = ?",
        (url,),
    ).fetchone()
    conn.close()
    classification = json.loads(row["schedule_classification"])
    assert classification["status"] == "confirmed_evening"
    assert classification["manual_resolution"]["evidence"] == (
        "Employer confirmed evening shift"
    )
    assert classification["manual_evidence_needs_reverification"] is False
    assert row["gh_metadata"] != ""
    assert row["office_locations"] == "Toronto; Remote"


def test_lever_and_remotive_unaffected(isolated_tracker, monkeypatch):
    """Lever and Remotive payloads carry no enrichment fields; persistence of
    their jobs must work unchanged and never write enrichment columns."""
    job = {
        "employer": "PointClickCare",
        "job_title": "IT Analyst",
        "job_url": "https://jobs.lever.co/pointclickcare/abc",
        "source": "lever",
        "description": "Daytime role 9 AM - 5 PM.",
        "location": "Mississauga, Ontario",
        "remote": 0,
        "listing_status": "active_on_source",
    }
    isolated_tracker.add_job(job)
    remotive_job = {
        "employer": "Remote Co",
        "job_title": "Python Dev",
        "job_url": "https://remotive.com/remote-jobs/1",
        "source": "remotive",
        "description": "Remote software development.",
        "location": "Remote",
        "remote": 1,
        "listing_status": "active_on_source_delayed",
    }
    isolated_tracker.add_job(remotive_job)
    conn = sqlite3.connect(db_module.DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = {
        r["source"]: r
        for r in conn.execute(
            "SELECT source, gh_job_id, gh_metadata, enriched_at FROM jobs"
        ).fetchall()
    }
    conn.close()
    for source_name in ("lever", "remotive"):
        assert rows[source_name]["gh_job_id"] == ""
        assert rows[source_name]["gh_metadata"] == ""
        assert rows[source_name]["enriched_at"] is None


def test_request_efficiency_repeated_discovery_cycles(isolated_tracker):
    """A second discovery cycle with the same feed must not issue extra
    detail requests; feed parsing uses the list endpoint only."""
    source = GreenhouseSource()
    with patch(
        "sources.greenhouse.requests.get", return_value=_mock_feed(FEED_PAYLOAD)
    ) as mock_get:
        source.search_board("acme-corp")
        first_call_count = mock_get.call_count
        source.search_board("acme-corp")
        second_call_count = mock_get.call_count
    # One request per search_board call; no per-job detail requests
    assert first_call_count == 1
    assert second_call_count == 2
    assert second_call_count - first_call_count == 1


def test_one_failed_enrichment_does_not_stop_discovery(isolated_tracker):
    """If one board request fails, other boards still return jobs."""
    source = GreenhouseSource()
    ok_response = _mock_feed(FEED_PAYLOAD)
    fail_response = MagicMock()
    fail_response.status_code = 500
    fail_response.json.side_effect = ValueError()
    responses = [fail_response, ok_response]

    def fake_get(url, **kwargs):
        return responses.pop(0) if len(responses) > 1 else ok_response

    with patch("sources.greenhouse.requests.get", side_effect=fake_get):
        result = source.search(["acme-corp", "widgets"])
    assert result["jobs"], "other board jobs must survive one board failure"
