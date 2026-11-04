import os, tempfile
from database.db import init_db, get_conn
import database.db as dbmod

def test_manual_intake_assessment(tmp_path, monkeypatch):
    dbpath = tmp_path / "t.db"
    monkeypatch.setattr(dbmod, "DB_PATH", str(dbpath))
    init_db()
    from tracking.application_tracker import ApplicationTracker
    tr = ApplicationTracker()
    job = {"employer":"Acme","job_title":"IT Support","job_url":"https://example.org/job/1","source":"manual","description":"Python SQL evening shift 6 PM","location":"Remote - Canada","remote":True,"employment_type":"Part-time","schedule_classification":{"schedule_type":"unknown"}}
    # bypass validation? add_job validates; use a valid URL host
    job["job_url"]="https://boards.greenhouse.io/acme/jobs/1"
    inserted = tr.add_job(job)
    assert inserted is not None
    from agents.matching_agent import MatchingAgent
    m = MatchingAgent()
    job["id"]=inserted
    res = m.score_job(job)
    assert "match_score" in res


def test_manual_intake_app_form():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file("app.py")
    at.run()
    at.sidebar.radio[0].set_value("Settings").run()
    at.sidebar.radio[1].set_value("Manual Job Intake").run()
    # set fields
    at.text_input[0].set_value("IT Support")
    at.text_input[1].set_value("Acme")
    at.text_input[2].set_value("https://boards.greenhouse.io/acme/jobs/2")
    at.text_area[0].set_value("Python SQL evening shift 6 PM remote Canada")
    at.run()
    # submit
    at.button[0].click().run()
    assert len(at.exception) == 0
