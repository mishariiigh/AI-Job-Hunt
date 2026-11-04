from agents.submission_recovery import classify_timeout, handle_http
from agents.submission_locks import acquire, release, is_locked

def test_timeout_classification():
    assert classify_timeout("before_send") == "RETRY_SAFE"
    assert classify_timeout("after_send_unknown") == "UNKNOWN_OUTCOME"

def test_http_classification():
    assert handle_http(429) == "RATE_LIMITED"
    assert handle_http(503) == "SERVER_ERROR"
    assert handle_http(404) == "CLIENT_ERROR"

def test_persistent_lock():
    ok1, owner1 = acquire("app1")
    assert ok1
    ok2, owner2 = acquire("app1")
    assert not ok2
    assert release("app1", owner1)
    ok3, _ = acquire("app1")
    assert ok3
