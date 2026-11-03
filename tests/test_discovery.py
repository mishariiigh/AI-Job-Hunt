from tracking.application_tracker import ApplicationTracker
from agents.discovery_agent import DiscoveryAgent


def test_tracker():
    t = ApplicationTracker()
    jobs = t.get_jobs()
    assert isinstance(jobs, list)


def test_discovery_agent():
    d = DiscoveryAgent()
    assert hasattr(d, 'discover')
    assert hasattr(d, 'filter_job')
