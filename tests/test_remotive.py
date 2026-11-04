import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import requests

from sources.remotive import RemotiveSource


JOB = {
    "id": 101,
    "url": "https://remotive.com/remote-jobs/software-development/sample-role-101",
    "title": "Python Support Engineer",
    "company_name": "Example Hiring Co.",
    "category": "Software Development",
    "job_type": "part_time",
    "publication_date": "2026-11-02T10:00:00",
    "candidate_required_location": "Canada",
    "salary": "$30/hour",
    "description": "<p>Support Python applications during the 5 PM to 11 PM shift.</p>",
}


def test_remotive_api_maps_active_jobs_and_preserves_attributed_listing_url(tmp_path):
    response = Mock(status_code=200)
    response.json.return_value = {"total-job-count": 1, "jobs": [JOB]}
    source = RemotiveSource(cache_path=tmp_path / "remotive.json")

    with patch("sources.remotive.requests.get", return_value=response) as get:
        result = source.search()
        cached = source.search()

    get.assert_called_once()
    assert result["status"] == "ok"
    assert result["retrieved"] == 1
    job = result["jobs"][0]
    assert job["source"] == "remotive"
    assert job["source_feed"] == "remotive"
    assert job["job_url"] == JOB["url"]
    assert job["location"] == "Canada"
    assert job["remote"] is True
    assert job["employment_type"] == "Part-time"
    assert job["listing_status"] == "active_on_source_delayed"
    assert job["last_verified_at"] == result["last_checked"]
    assert job["posting_date"] == "2026-11-02T10:00:00"
    assert cached["status"] == "cached"
    assert cached["jobs"][0]["job_url"] == JOB["url"]


def test_remotive_uses_cache_for_at_least_six_hours(tmp_path):
    cache_path = tmp_path / "remotive.json"
    fetched_at = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    cache_path.write_text(
        json.dumps({"fetched_at": fetched_at, "jobs": [JOB]}),
        encoding="utf-8",
    )
    response = Mock(status_code=200)
    response.json.return_value = {"total-job-count": 1, "jobs": [JOB]}
    source = RemotiveSource(cache_path=cache_path)

    with patch("sources.remotive.requests.get", return_value=response) as get:
        result = source.search()

    get.assert_called_once()
    assert result["status"] == "ok"


def test_remotive_api_errors_are_explicit_and_do_not_reuse_stale_jobs(tmp_path):
    cache_path = tmp_path / "remotive.json"
    fetched_at = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    cache_path.write_text(
        json.dumps({"fetched_at": fetched_at, "jobs": [JOB]}),
        encoding="utf-8",
    )
    source = RemotiveSource(cache_path=cache_path)

    with patch(
        "sources.remotive.requests.get",
        side_effect=requests.exceptions.Timeout("network timeout"),
    ):
        result = source.search()

    assert result["status"] == "error"
    assert result["jobs"] == []
    assert "network timeout" in result["error"]


def test_remotive_rejects_malformed_api_payload(tmp_path):
    response = Mock(status_code=200)
    response.json.return_value = {"jobs": "not-a-list"}
    source = RemotiveSource(cache_path=tmp_path / "remotive.json")

    with patch("sources.remotive.requests.get", return_value=response):
        result = source.search()

    assert result["status"] == "error"
    assert "jobs list" in result["error"]


def test_remotive_payload_without_an_original_listing_url_is_not_imported(tmp_path):
    response = Mock(status_code=200)
    response.json.return_value = {
        "total-job-count": 1,
        "jobs": [{**JOB, "url": ""}],
    }
    source = RemotiveSource(cache_path=tmp_path / "remotive.json")

    with patch("sources.remotive.requests.get", return_value=response):
        result = source.search()

    assert result["status"] == "error"
    assert result["jobs"] == []
    assert "missing its original listing URL" in result["error"]
