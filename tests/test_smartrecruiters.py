"""Stage 12.5.1 regression tests: SmartRecruiters source and board expansion.

All HTTP is mocked; all databases are temporary.
"""
import json
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

import database.db as db_module
from sources.smartrecruiters import SmartRecruitersSource
from tracking.application_tracker import ApplicationTracker
from agents.job_classifier import classify_opportunity


def _ok_response(payload):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = payload
    return response


def _posting(pid="p1", title="Support Analyst", city="Toronto", country="CA",
             region="Ontario", remote=False, description="<p>5 PM - 1 AM.</p>",
             released="2026-01-02T10:00:00-05:00", company="Acme"):
    return {
        "id": pid,
        "name": title,
        "company": {"name": company, "id": "acme"},
        "location": {"city": city, "region": region, "country": country},
        "remote": remote,
        "releasedDate": released,
        "jobAd": {"sections": {"jobDescription": {"text": description}}},
    }


def _page(content, total=None, offset=0):
    payload = {"content": content, "offset": offset}
    if total is not None:
        payload["totalFound"] = total
    return payload


@pytest.fixture
def isolated_tracker(tmp_path, monkeypatch):
    db_file = tmp_path / "test_sr.db"
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


# 1. Successful retrieval
def test_successful_retrieval(isolated_tracker):
    source = SmartRecruitersSource()
    with patch(
        "sources.smartrecruiters.requests.Session.get",
        return_value=_ok_response(_page([_posting()], total=1)),
    ):
        result = source.search(["acme"])
    assert result["retrieved"] == 1
    job = result["jobs"][0]
    assert job["employer"] == "Acme"
    assert job["job_title"] == "Support Analyst"
    assert job["location"] == "Toronto, Ontario, Canada"
    assert job["source"] == "smartrecruiters"
    assert result["statuses"][0]["status"] == "ok"


# 2. Pagination
def test_pagination(isolated_tracker):
    source = SmartRecruitersSource()
    pages = [
        _ok_response(_page([_posting(f"p{i}") for i in range(3)], total=4)),
        _ok_response(_page([_posting("p3")], total=4, offset=3)),
    ]
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return pages.pop(0)

    with patch("sources.smartrecruiters.requests.Session.get", side_effect=fake_get):
        result = source.fetch_company_postings("acme")
    assert result["retrieved"] == 4
    assert len(calls) == 2
    assert calls[0]["offset"] == 0
    assert calls[1]["offset"] == 3


# 3. Canadian and non-Canadian locations
def test_canadian_and_non_canadian_locations(isolated_tracker):
    source = SmartRecruitersSource()
    payload = _page([
        _posting("p1", city="Toronto", country="CA"),
        _posting("p2", city="San Francisco", region="California", country="US"),
    ], total=2)
    with patch(
        "sources.smartrecruiters.requests.Session.get",
        return_value=_ok_response(payload),
    ):
        result = source.search(["acme"])
    canadian = result["jobs"][0]
    us = result["jobs"][1]
    assert "Toronto" in canadian["location"]
    assert "San Francisco" in us["location"]
    # Both enter the pipeline; eligibility logic rejects the US posting
    job_id, row = _persist(isolated_tracker, canadian)
    opp = classify_opportunity(row)
    assert opp["canadian_eligibility"]["status"] == "confirmed_compatible"
    job_id_us, row_us = _persist(isolated_tracker, us)
    opp_us = classify_opportunity(row_us)
    assert opp_us["canadian_eligibility"]["status"] == "incompatible"


# 4. Missing location information
def test_missing_location(isolated_tracker):
    source = SmartRecruitersSource()
    payload = _page([{
        "id": "p1", "name": "Remote Dev",
        "company": {"name": "Acme"},
        "jobAd": {"sections": {"jobDescription": {"text": "x" * 40}}},
    }], total=1)
    with patch(
        "sources.smartrecruiters.requests.Session.get",
        return_value=_ok_response(payload),
    ):
        result = source.search(["acme"])
    job = result["jobs"][0]
    assert job["location"] == ""
    assert job["remote"] is False  # never inferred from absence
    job_id, row = _persist(isolated_tracker, job)
    assert row["location"] == ""


# 5. Missing descriptions
def test_missing_description(isolated_tracker):
    source = SmartRecruitersSource()
    payload = _page([{
        "id": "p1", "name": "Dev Role",
        "company": {"name": "Acme"},
        "location": {"city": "Toronto", "country": "CA"},
        "remote": True,
    }], total=1)
    with patch(
        "sources.smartrecruiters.requests.Session.get",
        return_value=_ok_response(payload),
    ):
        result = source.search(["acme"])
    job = result["jobs"][0]
    assert job["description"] == ""


# 6. Duplicate postings
def test_duplicate_postings(isolated_tracker):
    source = SmartRecruitersSource()
    with patch(
        "sources.smartrecruiters.requests.Session.get",
        return_value=_ok_response(_page([_posting()], total=1)),
    ):
        result = source.search(["acme"])
    job = result["jobs"][0]
    first = isolated_tracker.add_job(job)
    second = isolated_tracker.add_job(job)
    assert first == second
    conn = sqlite3.connect(db_module.DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    conn.close()
    assert count == 1


# 7. Malformed responses
def test_malformed_json(isolated_tracker):
    source = SmartRecruitersSource()
    response = MagicMock()
    response.status_code = 200
    response.json.side_effect = ValueError("bad")
    with patch("sources.smartrecruiters.requests.Session.get", return_value=response):
        result = source.fetch_company_postings("acme")
    assert result["status"] == "error"
    assert "Malformed" in result["error"]


def test_malformed_shape(isolated_tracker):
    source = SmartRecruitersSource()
    with patch(
        "sources.smartrecruiters.requests.Session.get",
        return_value=_ok_response({"unexpected": "shape"}),
    ):
        result = source.fetch_company_postings("acme")
    assert result["status"] == "error"
    assert "shape" in result["error"]


# 8. HTTP errors
def test_http_404(isolated_tracker):
    source = SmartRecruitersSource()
    response = MagicMock()
    response.status_code = 404
    with patch("sources.smartrecruiters.requests.Session.get", return_value=response):
        result = source.fetch_company_postings("missingco")
    assert result["status"] == "error"
    assert "404" in result["error"]


def test_http_429_partial_results_kept(isolated_tracker):
    source = SmartRecruitersSource()
    responses = [
        _ok_response(_page([_posting("p1")], total=50)),
        MagicMock(status_code=429),
    ]
    with patch(
        "sources.smartrecruiters.requests.Session.get",
        side_effect=lambda *a, **k: responses.pop(0),
    ):
        result = source.fetch_company_postings("acme")
    assert result["status"] == "error"
    assert "429" in result["error"]
    assert result["retrieved"] == 1  # first page kept


def test_http_500_partial_results_kept(isolated_tracker):
    source = SmartRecruitersSource()
    responses = [
        _ok_response(_page([_posting("p1")], total=50)),
        MagicMock(status_code=503),
    ]
    with patch(
        "sources.smartrecruiters.requests.Session.get",
        side_effect=lambda *a, **k: responses.pop(0),
    ):
        result = source.fetch_company_postings("acme")
    assert result["status"] == "error"
    assert "503" in result["error"]
    assert result["retrieved"] == 1


def test_network_timeout(isolated_tracker):
    import requests as requests_module
    source = SmartRecruitersSource()
    with patch(
        "sources.smartrecruiters.requests.Session.get",
        side_effect=requests_module.exceptions.ConnectionError("down"),
    ):
        result = source.fetch_company_postings("acme")
    assert result["status"] == "error"
    assert "Network failure" in result["error"]
    assert result["jobs"] == []


# 9. Source attribution
def test_source_attribution(isolated_tracker):
    source = SmartRecruitersSource()
    with patch(
        "sources.smartrecruiters.requests.Session.get",
        return_value=_ok_response(_page([_posting(pid="abc-123")], total=1)),
    ):
        result = source.search(["acme"])
    job = result["jobs"][0]
    assert job["source"] == "smartrecruiters"
    assert job["source_feed"] == "acme"
    assert job["external_job_id"] == "abc-123"
    assert job["job_url"].startswith("https://jobs.smartrecruiters.com/acme/")
    job_id, row = _persist(isolated_tracker, job)
    assert row["source"] == "smartrecruiters"
    assert row["source_feed"] == "acme"


# 10. Existing eligibility and recommendation pipeline compatibility
def test_pipeline_compatibility_confirmed_evening(isolated_tracker):
    source = SmartRecruitersSource()
    posting = _posting(
        pid="evening1",
        title="Evening Support Analyst",
        city="Mississauga",
        country="CA",
        description="Shift: 5 PM - 1 AM Eastern Time, on-site.",
    )
    with patch(
        "sources.smartrecruiters.requests.Session.get",
        return_value=_ok_response(_page([posting], total=1)),
    ):
        result = source.search(["acme"])
    job_id, row = _persist(isolated_tracker, result["jobs"][0])
    opportunity = classify_opportunity(row)
    assert opportunity["status"] in {"confirmed_evening", "needs_verification"}
    # Canadian eligibility confirmed via structured country field
    assert opportunity["canadian_eligibility"]["status"] == "confirmed_compatible"


def test_unknown_schedule_stays_unconfirmed(isolated_tracker):
    source = SmartRecruitersSource()
    posting = _posting(
        pid="flex1",
        title="Developer",
        city="Toronto",
        country="CA",
        description="Flexible hours; evening availability preferred.",
    )
    with patch(
        "sources.smartrecruiters.requests.Session.get",
        return_value=_ok_response(_page([posting], total=1)),
    ):
        result = source.search(["acme"])
    job_id, row = _persist(isolated_tracker, result["jobs"][0])
    classification = json.loads(row["schedule_classification"])
    assert classification["status"] != "confirmed_evening"
    assert classification["confirmed_evening"] is False


def test_manual_resolution_survives_smartrecruiters_refresh(isolated_tracker):
    from tracking.application_tracker import ManualResolutionError
    manual = {
        "status": "confirmed_evening",
        "schedule_type": "confirmed_evening",
        "manual_resolution": {
            "value": "confirmed_evening",
            "source": "https://employer.example.com/1",
            "evidence": "Employer confirmed evening",
            "timestamp": "2026-11-05T10:00:00-05:00",
        },
    }
    job = {
        "employer": "Acme",
        "job_title": "Support Analyst",
        "job_url": "https://jobs.smartrecruiters.com/acme/res-1",
        "source": "smartrecruiters",
        "source_feed": "acme",
        "description": "Hours not stated.",
        "location": "Toronto, Ontario, CA",
        "remote": 0,
        "listing_status": "active_on_source",
        "schedule_classification": manual,
    }
    isolated_tracker.add_job(job)
    isolated_tracker.refresh_job_listing({**job, "description": "Hours not stated."})
    row = _persist(isolated_tracker, job)[1]
    classification = json.loads(row["schedule_classification"])
    assert classification["status"] == "confirmed_evening"
    assert classification["manual_resolution"]["evidence"] == (
        "Employer confirmed evening"
    )


def test_greenhouse_lever_remotive_unchanged(isolated_tracker):
    """Existing sources persist unchanged; no cross-source contamination."""
    for source_name, url in [
        ("greenhouse", "https://boards.greenhouse.io/geotab/jobs/1"),
        ("lever", "https://jobs.lever.co/pointclickcare/abc"),
        ("remotive", "https://remotive.com/remote-jobs/1"),
    ]:
        job_id, row = _persist(isolated_tracker, {
            "employer": "E",
            "job_title": "T",
            "job_url": url,
            "source": source_name,
            "description": "Some description text long enough.",
            "location": "Remote - Canada",
            "remote": 1,
            "listing_status": "active_on_source",
        })
        assert row["source"] == source_name
        assert row["external_job_id"] == ""
