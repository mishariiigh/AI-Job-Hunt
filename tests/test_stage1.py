import os
import json
import tempfile
from documents import structured_resume_parser
from documents import resume_manager
from documents import profile_suggestions as ps
from documents import profile_compare


def test_structured_parser_basic():
    text = """
    John Doe
    john@example.com
    123-456-7890
    
    Summary
    Experienced IT Support professional
    
    Skills
    Python, SQL, Azure, Networking
    
    Experience
    IT Support Technician | 2020 - Present
    - Provided technical support
    - Resolved tickets
    
    Education
    Computer Programming Diploma
    
    Certifications
    CompTIA A+
    
    Projects
    Job Automation Tool
    - Automated workflows
    """
    parsed = structured_resume_parser.parse_resume(text)
    assert parsed is not None
    assert 'skills' in parsed
    assert 'experience' in parsed
    assert 'education' in parsed
    assert isinstance(parsed['skills'], list)
    assert len(parsed['skills']) > 0


def test_structured_parser_to_json():
    parsed = structured_resume_parser.parse_resume("Skills\nPython\nSQL")
    json_str = structured_resume_parser.parse_to_json("Skills\nPython")
    assert isinstance(json_str, str)
    data = json.loads(json_str)
    assert 'skills' in data


def test_resume_manager_parsed_json(tmp_path, monkeypatch):
    # Use temp paths
    import documents.resume_manager as rm
    test_index = tmp_path / "index.json"
    test_parsed_dir = tmp_path / "parsed"
    monkeypatch.setattr(rm, "INDEX", str(test_index))
    monkeypatch.setattr(rm, "PARSED_DIR", str(test_parsed_dir))
    rid = rm.add_resume("test.pdf", "/tmp/test.pdf", "hello skills Python", name="Test Resume")
    parsed = {"skills": ["Python"], "experience": []}
    result = rm.save_parsed_json(rid, parsed)
    assert result is True
    retrieved = rm.get_parsed_json(rid)
    assert retrieved is not None
    assert "Python" in retrieved.get("skills", [])


def test_profile_compare_basic():
    profile = {"technical_interests": ["Python", "SQL", "Azure"]}
    resume_text = "I have experience with Python and JavaScript"
    result = profile_compare.compare(profile, resume_text)
    assert isinstance(result, dict)
    assert 'in_both' in result or 'missing_in_resume' in result


def test_profile_suggestions_approval_persistence(tmp_path, monkeypatch):
    import documents.profile_suggestions as ps
    monkeypatch.setattr(ps, "PATH", str(tmp_path / "s.json"))
    profile = {"technical_interests": []}
    p = tmp_path / "p.json"
    p.write_text(json.dumps(profile))
    items = ps.create_suggestions(profile, "Python developer with SQL", "resume")
    assert len(items) >= 1
    sid = items[0]["id"]
    ps.set_status(sid, "approved")
    assert any(x["status"] == "approved" for x in ps.list_suggestions())
    changed = ps.apply_approved(str(p))
    assert changed
    newp = json.loads(p.read_text())
    assert "Python" in newp["technical_interests"]


def test_linkedin_pdf_upload_support():
    # Check that app accepts pdf for linkedin upload
    from documents.resume_parser import extract_text
    import os
    # Use existing pdf
    pdf_path = "/Users/m10/Desktop/Ai Job application Agent/ai-job-hunter/storage/resumes/Ghanem%20Mishari%20Resume.pdf"
    if os.path.exists(pdf_path):
        text = extract_text(pdf_path)
        assert isinstance(text, str)
    # If not found with encoded name, try actual
    pdf_path2 = "/Users/m10/Desktop/Ai Job application Agent/ai-job-hunter/storage/resumes/Ghanem Mishari Resume.pdf"
    if os.path.exists(pdf_path2):
        text = extract_text(pdf_path2)
        assert isinstance(text, str)
