from sources.greenhouse import GreenhouseSource
from sources.lever import LeverSource
from tracking.application_tracker import ApplicationTracker
from agents.discovery_agent import DiscoveryAgent
from unittest.mock import patch, Mock


def test_greenhouse_success():
    gh = GreenhouseSource()
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "jobs": [{
            "id": 123,
            "title": "IT Support Technician",
            "absolute_url": "https://boards.greenhouse.io/test/jobs/123",
            "location": {"name": "Toronto, Canada"},
            "content": "Remote IT support role",
            "updated_at": "2024-01-01T00:00:00Z",
            "first_published": "2023-12-01T00:00:00Z",
        }]
    }
    with patch('requests.get', return_value=mock_resp):
        res = gh.search_board("test")
        assert res['status'] == 'ok'
        assert len(res['jobs']) == 1
        assert res['jobs'][0]['job_title'] == "IT Support Technician"
        assert res['jobs'][0]['posting_date'] == "2023-12-01T00:00:00+00:00"
        assert res['jobs'][0]['source_updated_at'] == "2024-01-01T00:00:00Z"
        assert res['jobs'][0]['source_feed'] == "test"


def test_greenhouse_normalizes_numeric_millisecond_posting_dates():
    response = Mock(status_code=200)
    response.json.return_value = {
        "jobs": [{
            "title": "Support Analyst",
            "absolute_url": "https://boards.greenhouse.io/test/jobs/123",
            "first_published": 1704067200000,
        }]
    }

    with patch("requests.get", return_value=response):
        result = GreenhouseSource().search_board("test")

    assert result["jobs"][0]["posting_date"] == "2024-01-01T00:00:00+00:00"


def test_lever_success():
    lev = LeverSource()
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [{
        "text": "Help Desk Analyst",
        "hostedUrl": "https://jobs.lever.co/test/abc123",
        "categories": {"location": "Remote - Canada", "commitment": "Part-time"},
        "descriptionPlain": "Evening support role",
        "createdAt": 1704067200000,
        "updatedAt": 1704153600000
    }]
    with patch('requests.get', return_value=mock_resp):
        res = lev.search_board("test")
        assert res['status'] == 'ok'
        assert len(res['jobs']) == 1
        assert res['jobs'][0]['posting_date'] == "2024-01-01T00:00:00+00:00"
        assert res['jobs'][0]['source_updated_at'] == "2024-01-02T00:00:00+00:00"


def test_greenhouse_http_error():
    gh = GreenhouseSource()
    mock_resp = Mock()
    mock_resp.status_code = 404
    with patch('requests.get', return_value=mock_resp):
        res = gh.search_board("bad")
        assert res['status'] == 'error'


def test_greenhouse_malformed_feed_does_not_look_like_an_empty_snapshot():
    gh = GreenhouseSource()
    mock_resp = Mock(status_code=200)
    mock_resp.json.return_value = {"unexpected": []}

    with patch('requests.get', return_value=mock_resp):
        result = gh.search_board("test")

    assert result["status"] == "error"
    assert result["jobs"] == []
    assert "jobs must be a list" in result["error"]


def test_greenhouse_skipped_records_mark_the_snapshot_incomplete():
    gh = GreenhouseSource()
    mock_resp = Mock(status_code=200)
    mock_resp.json.return_value = {
        "jobs": [
            {
                "title": "Support Engineer",
                "absolute_url": "https://boards.greenhouse.io/test/jobs/1",
            },
            {"title": "Unlinked posting"},
        ]
    }

    with patch('requests.get', return_value=mock_resp):
        result = gh.search_board("test")

    assert result["status"] == "error"
    assert result["retrieved"] == 1
    assert "snapshot incomplete" in result["error"]


def test_greenhouse_timeout():
    gh = GreenhouseSource()
    import requests
    with patch('requests.get', side_effect=requests.exceptions.Timeout):
        res = gh.search_board("test")
        assert res['status'] == 'error'


def test_lever_invalid_json():
    lev = LeverSource()
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.side_effect = ValueError("bad json")
    with patch('requests.get', return_value=mock_resp):
        res = lev.search_board("test")
        assert res['status'] == 'error'


def test_d2l_employer_feed_maps_original_posting_and_canadian_schedule_text():
    from config.source_config import enabled_tokens, load_sources

    assert "d2l" in enabled_tokens(load_sources(), "greenhouse_boards")

    gh = GreenhouseSource()
    mock_resp = Mock(status_code=200)
    mock_resp.json.return_value = {
        "jobs": [
            {
                "title": "Product Support Analyst",
                "absolute_url": "https://www.d2l.com/careers/jobs/product-support-analyst/7696232/",
                "location": {"name": "Kitchener, Ontario; Remote - Canada"},
                "content": (
                    "Participate in a shift rotation including weekdays, "
                    "evenings, and weekends based on Eastern Time."
                ),
            }
        ]
    }

    with patch("requests.get", return_value=mock_resp):
        result = gh.search_board("d2l")

    assert result["status"] == "ok"
    assert result["jobs"][0]["job_url"].startswith("https://www.d2l.com/")
    assert result["jobs"][0]["source_feed"] == "d2l"


def test_lever_skipped_records_mark_the_snapshot_incomplete():
    lev = LeverSource()
    mock_resp = Mock(status_code=200)
    mock_resp.json.return_value = [
        {
            "text": "Support Engineer",
            "hostedUrl": "https://jobs.lever.co/test/1",
        },
        {"text": "Unlinked posting"},
    ]

    with patch('requests.get', return_value=mock_resp):
        result = lev.search_board("test")

    assert result["status"] == "error"
    assert result["retrieved"] == 1
    assert "snapshot incomplete" in result["error"]


def test_duplicate_prevention():
    t = ApplicationTracker()
    job = {
        'employer': 'Acme',
        'job_title': 'IT Support',
        'job_url': 'https://boards.greenhouse.io/acme/jobs/123',
        'source': 'greenhouse',
        'description': 'test',
        'location': 'Canada',
        'remote': True
    }
    t.add_job(job)
    assert t.job_exists('https://boards.greenhouse.io/acme/jobs/123')
    assert t.job_exists('https://boards.greenhouse.io/acme/jobs/123#frag')  # normalized


def test_canadian_remote_filter():
    d = DiscoveryAgent()
    assert d.is_canadian_remote({'location': 'Toronto, Canada', 'remote': True})
    assert d.is_canadian_remote({'location': '', 'remote': True, 'description': 'Canada-wide remote'})


def test_unknown_schedule_is_not_a_confirmed_evening_shift():
    d = DiscoveryAgent()
    job = {'shift': 'unknown', 'description': 'IT support', 'job_title': 'Support'}
    assert d.has_evening_shift(job) is False
    assert d.has_evening_shift(
        {
            'description': 'Shift starts at 5 PM',
            'job_title': 'Support',
            'location': 'Oakville, Ontario',
        }
    ) is True
    assert d.has_evening_shift(
        {'description': 'Flexible schedule', 'job_title': 'Support'}
    ) is False


def test_expired_not_aggressive():
    d = DiscoveryAgent()
    assert d.is_expired({'deadline': None}) == False
