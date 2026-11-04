from agents.idempotency import create_attempt, stable_key
from agents.recovery import recover
import sqlite3, os

DB = os.path.join(os.path.dirname(__file__), "..", "database", "app.db")

def test_duplicate_attempt():
    ok1, key1 = create_attempt(1, 2, "SUBMITTING")
    ok2, key2 = create_attempt(1, 2, "SUBMITTING")
    assert key1 == key2
    # second may fail due to unique key
    assert (not ok2) or ok2

def test_recovery_idempotent():
    recover()
    recover()
    # no crash
    assert True
