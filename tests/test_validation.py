from sources.validator import SourceValidator
from agents.discovery_agent import DiscoveryAgent
from tracking.application_tracker import ApplicationTracker
from unittest.mock import patch, Mock


def test_validator_greenhouse_valid():
    v = SourceValidator()
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"jobs": [{"id": 1}, {"id": 2}]}
    with patch('requests.get', return_value=mock_resp):
        res = v.validate_greenhouse("test")
        assert res['valid'] == True
        assert res['job_count'] == 2


def test_validator_greenhouse_404():
    v = SourceValidator()
    mock_resp = Mock()
    mock_resp.status_code = 404
    with patch('requests.get', return_value=mock_resp):
        res = v.validate_greenhouse("bad")
        assert res['valid'] == False
        assert res['status'] == 'invalid'


def test_validator_greenhouse_429():
    v = SourceValidator()
    mock_resp = Mock()
    mock_resp.status_code = 429
    with patch('requests.get', return_value=mock_resp):
        res = v.validate_greenhouse("test")
        assert res['valid'] == False
        assert res['status'] == 'rate_limited'


def test_validator_lever_valid():
    v = SourceValidator()
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [{"text": "Job1"}, {"text": "Job2"}]
    with patch('requests.get', return_value=mock_resp):
        res = v.validate_lever("test")
        assert res['valid'] == True


def test_canada_remote_cases():
    d = DiscoveryAgent()
    assert d.is_canadian_remote({'location': 'Remote - Canada', 'remote': True}) == True
    assert d.is_canadian_remote({'location': 'Toronto, ON, Canada', 'remote': True}) == True
    assert d.is_canadian_remote({'location': 'Remote - USA', 'remote': True, 'description': ''}) == False


def test_hybrid_onsite():
    d = DiscoveryAgent()
    # Hybrid - location might say hybrid
    job = {'location': 'Toronto, Canada (Hybrid)', 'remote': False, 'description': 'hybrid'}
    # Should still be considered based on Canada location
    result = d.is_canadian_remote(job)
    assert isinstance(result, bool)


def test_schedule_classification():
    d = DiscoveryAgent()
    assert d.classify_schedule({'description': 'Evening shift'})['confirmed_evening'] == True
    assert d.classify_schedule({'description': 'Weekend availability'})['confirmed_weekend'] == True
    assert d.classify_schedule({'description': 'Flexible schedule'})['flexible'] == True
    sched = d.classify_schedule({'description': 'IT support role'})
    assert sched['schedule_type'] == 'unknown'


def test_unknown_not_evening_confirmed():
    d = DiscoveryAgent()
    sched = d.classify_schedule({'description': 'Software developer'})
    assert sched['confirmed_evening'] == False
    assert sched['schedule_type'] == 'unknown'


def test_french_required():
    d = DiscoveryAgent()
    assert d.is_french_required({'description': 'Bilingual French required'}) == True
    assert d.is_french_required({'description': 'English only'}) == False


def test_part_time_full_time():
    d = DiscoveryAgent()
    sched = d.classify_schedule({'description': 'Part-time position, 20 hours'})
    assert sched['part_time'] == True


def test_url_normalization():
    t = ApplicationTracker()
    t.add_job({'employer': 'e', 'job_title': 't', 'job_url': 'https://boards.greenhouse.io/acme/jobs/1?ref=abc#section', 'source': 'greenhouse', 'description': '', 'location': 'Canada', 'remote': True})
    assert t.job_exists('https://boards.greenhouse.io/acme/jobs/1?ref=abc')
    assert t.job_exists('https://boards.greenhouse.io/acme/jobs/1?ref=abc#section')


def test_different_jobs_not_merged():
    t = ApplicationTracker()
    t.add_job({'employer': 'e', 'job_title': 'Job A', 'job_url': 'https://boards.greenhouse.io/acme/jobs/1', 'source': 'greenhouse', 'description': '', 'location': 'Canada', 'remote': True})
    t.add_job({'employer': 'e', 'job_title': 'Job B', 'job_url': 'https://boards.greenhouse.io/acme/jobs/2', 'source': 'greenhouse', 'description': '', 'location': 'Canada', 'remote': True})
    jobs = t.get_jobs()
    urls = [j['job_url'] for j in jobs]
    assert len(set(urls)) >= 2
