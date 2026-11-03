import os, json, tempfile
from documents import profile_suggestions as ps

def test_suggestion_persistence(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "PATH", str(tmp_path / "s.json"))
    profile = {"technical_interests": []}
    p = tmp_path / "p.json"
    p.write_text(json.dumps(profile))
    items = ps.create_suggestions(profile, "Python developer", "resume")
    assert len(items) >= 1
    sid = items[0]["id"]
    ps.set_status(sid, "approved")
    assert any(x["status"]=="approved" for x in ps.list_suggestions())
    ps.apply_approved(str(p))
    newp = json.loads(p.read_text())
    assert "Python" in newp["technical_interests"]
