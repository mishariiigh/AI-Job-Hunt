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
            "updated_at": "2024-01-01T00:00:00Z"
        }]
    }
    with patch('requests.get', return_value=mock_resp):
        res = gh.search_board("test")
        assert res['status'] == 'ok'
        assert len(res['jobs']) == 1
        assert res['jobs'][0]['job_title'] == "IT Support Technician"


def test_lever_success():
    lev = LeverSource()
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [{
        "text": "Help Desk Analyst",
        "hostedUrl": "https://jobs.lever.co/test/abc123",
        "categories": {"location": "Remote - Canada", "commitment": "Part-time"},
        "descriptionPlain": "Evening support role",
        "createdAt": "2024-01-01T00:00:00Z"
    }]
    with patch('requests.get', return_value=mock_resp):
        res = lev.search_board("test")
        assert res['status'] == 'ok'
        assert len(res['jobs']) == 1


def test_greenhouse_http_error():
    gh = GreenhouseSource()
    mock_resp = Mock()
    mock_resp.status_code = 404
    with patch('requests.get', return_value=mock_resp):
        res = gh.search_board("bad")
        assert res['status'] == 'error'


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


def test_unknown_schedule_allowed():
    d = DiscoveryAgent()
    job = {'shift': 'unknown', 'description': 'IT support', 'job_title': 'Support'}
    assert d.has_evening_shift(job) == True


def test_expired_not_aggressive():
    d = DiscoveryAgent()
    assert d.is_expired({'deadline': None}) == False
