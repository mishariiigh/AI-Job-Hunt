import json

import pytest

from agents.matching_agent import MatchingAgent
from documents import linkedin_import, resume_export, resume_manager
from documents.profile_compare import compare_structured
from tracking.application_tracker import ApplicationTracker
from tracking.application_workflow import (
    ApplicationWorkflowError,
    application_readiness,
    approve_application,
    mark_manually_submitted,
    mark_submission_failed,
    prepare_application_draft,
    regenerate_documents,
    retry_failed_submission,
    save_application_review,
    submission_capability,
)


PROFILE = {
    "name": "Taylor Candidate",
    "email": "taylor@example.test",
    "phone": "555-0101",
    "location": "Oakville, Ontario, Canada",
    "education": "Computer Programming Diploma, Algonquin College",
    "experience_years": 4,
    "career_direction": "AI automation and software development",
    "technical_interests": ["Python", "SQL"],
    "language": "English",
}
RESUME_TEXT = """Taylor Candidate
Experience
Software Developer, Northstar 2020-2023
- Built Python automation tools.
Education
Computer Programming Diploma, Algonquin College 2019
Skills
Python, SQL
IT-01 designation
"""


@pytest.fixture
def workflow_setup(tmp_path, monkeypatch):
    index = tmp_path / "resumes" / "index.json"
    parsed = tmp_path / "resumes" / "parsed"
    monkeypatch.setattr(resume_manager, "INDEX", str(index))
    monkeypatch.setattr(resume_manager, "PARSED_DIR", str(parsed))
    monkeypatch.setattr(MatchingAgent, "load_profile", lambda self: PROFILE)

    resume_path = tmp_path / "candidate.txt"
    resume_path.write_text(RESUME_TEXT, encoding="utf-8")
    resume_id = resume_manager.add_resume(
        "candidate.txt", str(resume_path), RESUME_TEXT
    )

    tracker = ApplicationTracker()
    job_id = tracker.add_job(
        {
            "employer": "Northstar Systems",
            "job_title": "Python Support Analyst",
            "job_url": "https://careers.northstar.example/apply/42",
            "source": "unit-test",
            "location": "Oakville, Ontario, Canada",
            "remote": 0,
            "employment_type": "Part-time",
            "listing_status": "active_on_source",
            "last_verified_at": "2026-11-04T10:00:00-05:00",
            "description": (
                "Canadian residents may apply. Shift runs 5:00 PM to 10:00 PM. "
                "Required skills: Python and SQL. Computer Programming Diploma preferred."
            ),
            "status": "discovered",
        }
    )
    return tracker, job_id, resume_id


def test_draft_creation_is_linked_persistent_and_duplicate_safe(workflow_setup):
    tracker, job_id, resume_id = workflow_setup

    first = prepare_application_draft(job_id, tracker=tracker)
    duplicate = prepare_application_draft(job_id, tracker=tracker)

    assert first["created"] is True
    assert first["application"]["job_id"] == job_id
    assert first["application"]["resume_id"] == resume_id
    assert first["application"]["job_description"].startswith("Canadian residents")
    assert first["application"]["status"] == "Draft"
    assert duplicate["created"] is False
    assert duplicate["application"]["id"] == first["application"]["id"]
    assert len(tracker.get_applications()) == 1

    new_version = prepare_application_draft(
        job_id, allow_new_version=True, tracker=tracker
    )
    assert new_version["created"] is True
    assert new_version["application"]["version_number"] == 2
    assert len(tracker.get_applications()) == 2
    assert len(tracker.get_application_events(first["application"]["id"])) == 1


def test_schedule_inquiry_is_editable_persistent_and_never_sent(workflow_setup):
    tracker, job_id, _ = workflow_setup
    from database.db import get_conn

    connection = get_conn()
    connection.execute(
        "UPDATE jobs SET description = ? WHERE id = ?",
        (
            "Canadian residents may apply. The support team rotates between weekdays, "
            "evenings and weekends. SQL support is required.",
            job_id,
        ),
    )
    connection.commit()
    connection.close()

    application = prepare_application_draft(job_id, tracker=tracker)["application"]
    inquiry = application["schedule_inquiry"]
    assert "Northstar Systems" in inquiry
    assert "Python Support Analyst" in inquiry
    assert "5:00 PM Toronto time" in inquiry
    assert "20–25 hours per week" in inquiry
    assert tracker.get_application_events(application["id"])

    edited = inquiry.replace("Could you confirm", "Would you please confirm")
    saved = save_application_review(
        application["id"],
        tailored_resume=application["tailored_resume"],
        cover_letter=application["cover_letter"],
        answers=application["answers"],
        schedule_inquiry=edited,
        tracker=tracker,
    )
    reloaded = tracker.get_application(application["id"])
    assert saved["schedule_inquiry"] == edited
    assert reloaded["schedule_inquiry"] == edited
    assert reloaded["submission_state"] == "NOT_SUBMITTED"
    assert reloaded.get("submitted_at") is None


def test_d2l_inquiry_covers_rotation_evening_only_and_education_equivalency(workflow_setup):
    tracker, job_id, _ = workflow_setup
    from database.db import get_conn

    connection = get_conn()
    connection.execute(
        """
        UPDATE jobs
        SET employer = ?, job_title = ?, job_url = ?, location = ?, remote = 1,
            description = ?, listing_status = 'active_on_source'
        WHERE id = ?
        """,
        (
            "D2L",
            "Product Support Analyst",
            "https://www.d2l.com/careers/jobs/product-support-analyst/7696232/",
            "Remote - Canada",
            (
                "Participate in a shift rotation including weekdays, evenings, and "
                "weekends based on Eastern Time. Education Recommendations: "
                "Bachelor's degree in Computer Science or equivalent technical experience."
            ),
            job_id,
        ),
    )
    connection.commit()
    connection.close()

    application = prepare_application_draft(job_id, tracker=tracker)["application"]
    inquiry = application["schedule_inquiry"]
    assert "exact shift start and end times" in inquiry
    assert "whether rotation is required for every employee" in inquiry
    assert "fixed evening-only schedule" in inquiry
    assert "a Computer Programming Diploma from Algonquin College" in inquiry
    assert "approximately 4 years of relevant experience" in inquiry
    assert "equivalent technical experience recommendation" in inquiry
    assert tracker.get_application(application["id"])["schedule_inquiry"] == inquiry
    assert application["submission_state"] == "NOT_SUBMITTED"
    assert application.get("submitted_at") is None


def test_schedule_conflict_inquiry_names_both_sources_and_asks_for_resolution():
    from tracking.application_workflow import build_schedule_inquiry

    inquiry = build_schedule_inquiry(
        {
            "employer": "ASL Distribution / Fastfrate",
            "job_title": "After-Hours IT Support Analyst",
            "job_url": "https://ca.indeed.com/viewjob?jk=03fe2c1d035076a0",
            "location": "Oakville, Ontario",
            "description": "Monday to Friday, 5:00 PM to 1:00 AM.",
            "shift": "Day shift",
        }
    )
    assert "description lists 5:00 PM to 1:00 AM" in inquiry
    assert "structured schedule metadata says Day shift" in inquiry
    assert "which schedule is accurate" in inquiry
    assert "exact scheduled start and end times" in inquiry
    assert "regular shift starting at or after 5:00 PM" in inquiry
    assert "rotations are assigned" not in inquiry


def test_schema_migration_versions_existing_duplicate_job_records():
    from database.db import get_conn

    conn = get_conn()
    cursor = conn.execute(
        """
        INSERT INTO jobs (employer, job_title, job_url, source, description, location)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "Legacy Employer",
            "Legacy Role",
            "https://legacy.example/job/1",
            "unit-test",
            "Legacy description",
            "Oakville, Ontario",
        ),
    )
    job_id = cursor.lastrowid
    conn.executemany(
        "INSERT INTO applications (job_id, status) VALUES (?, ?)",
        ((job_id, "Draft"), (job_id, "Draft")),
    )
    conn.commit()
    conn.close()

    tracker = ApplicationTracker()

    versions = sorted(
        application["version_number"]
        for application in tracker.get_applications()
    )
    assert versions == [1, 2]


def test_generation_uses_source_content_without_it01_or_fabrication(workflow_setup):
    import hashlib

    tracker, job_id, _ = workflow_setup
    original_path = resume_manager.get_default()["path"]
    original_hash = hashlib.sha256(open(original_path, "rb").read()).hexdigest()
    application = prepare_application_draft(job_id, tracker=tracker)["application"]
    resume = application["tailored_resume"]
    letter = application["cover_letter"]

    assert "2020-2023" in resume
    assert "Built Python automation tools." in resume
    assert "IT-01" not in resume.upper()
    assert resume.index("Python") < resume.index("SQL")
    assert "Northstar Systems" in resume
    assert resume.count("Taylor Candidate") == 1
    assert "Python Support Analyst" in letter
    assert "Northstar Systems" in letter
    assert "Computer Programming Diploma, Algonquin College" in letter
    assert "led a team" not in letter.lower()
    assert resume.count("Software Developer, Northstar 2020-2023") == 1
    assert hashlib.sha256(open(original_path, "rb").read()).hexdigest() == original_hash


def test_unverified_eligibility_blocks_approval_until_resolved(workflow_setup):
    tracker, job_id, _ = workflow_setup
    from database.db import get_conn

    db = get_conn()
    db.execute(
        "UPDATE jobs SET description = ? WHERE id = ?",
        (
            "Canadian residents may apply. Python and SQL experience preferred.",
            job_id,
        ),
    )
    db.commit()
    db.close()

    prepared = prepare_application_draft(job_id, tracker=tracker)
    application = prepared["application"]
    assert application["status"] == "Needs information"
    assert application["eligibility_status"] == "needs_verification"
    with pytest.raises(ApplicationWorkflowError, match="Approval is blocked"):
        approve_application(application["id"], tracker)

    saved = save_application_review(
        application["id"],
        tailored_resume=application["tailored_resume"],
        cover_letter=application["cover_letter"],
        answers=application["answers"],
        eligibility_verification="The employer posting confirms shifts run 5:00 PM to 10:00 PM.",
        tracker=tracker,
    )
    ready, missing, eligibility, _ = application_readiness(saved, tracker)
    assert eligibility["status"] == "confirmed_evening"
    assert ready is True, missing
    assert missing == []
    assert approve_application(application["id"], tracker)["status"] == "Approved"


def test_rejected_job_cannot_create_application_draft(workflow_setup):
    tracker, job_id, _ = workflow_setup
    from database.db import get_conn

    conn = get_conn()
    conn.execute(
        "UPDATE jobs SET location = ?, description = ? WHERE id = ?",
        ("Dallas, Texas, USA", "US residents only. 5:00 PM to 10:00 PM.", job_id),
    )
    conn.commit()
    conn.close()

    with pytest.raises(ApplicationWorkflowError, match="rejected"):
        prepare_application_draft(job_id, tracker=tracker)
    assert tracker.get_applications() == []


def test_mandatory_qualification_gap_blocks_approval(workflow_setup):
    tracker, job_id, _ = workflow_setup
    from database.db import get_conn

    conn = get_conn()
    conn.execute(
        "UPDATE jobs SET description = ? WHERE id = ?",
        (
            "Canadian residents may apply. Shift starts at 5:00 PM. "
            "Required skills: Python and SQL. Bachelor's degree required.",
            job_id,
        ),
    )
    conn.commit()
    conn.close()

    application = prepare_application_draft(job_id, tracker=tracker)["application"]
    ready, missing, _, assessment = application_readiness(application, tracker)
    assert not assessment["mandatory_gaps"]
    bachelor = next(
        item for item in assessment["requirement_assessments"]
        if item["requirement"] == "Bachelor's degree"
    )
    assert bachelor["evidence_status"] == "Not evidenced"
    assert "Bachelor's degree" in assessment["requirements_requiring_review"]
    assert not ready
    assert any("not marked missing" in item.lower() for item in missing)
    with pytest.raises(ApplicationWorkflowError, match="Approval is blocked"):
        approve_application(application["id"], tracker)


def test_experience_requirement_blocks_and_preferred_education_does_not(workflow_setup):
    tracker, job_id, _ = workflow_setup
    from database.db import get_conn

    conn = get_conn()
    conn.execute(
        "UPDATE jobs SET description = ? WHERE id = ?",
        (
            "Canadian residents may apply. Shift starts at 5:00 PM. "
            "Required skills: Python and SQL. Bachelor's degree preferred.",
            job_id,
        ),
    )
    conn.commit()
    conn.close()
    application = prepare_application_draft(job_id, tracker=tracker)["application"]
    ready, missing, _, assessment = application_readiness(application, tracker)
    assert ready is True, missing
    assert "education requirement not met" not in assessment["mandatory_gaps"]

    conn = get_conn()
    conn.execute(
        "UPDATE jobs SET description = ? WHERE id = ?",
        (
            "Canadian residents may apply. Shift starts at 5:00 PM. "
            "Required skills: Python and SQL. At least 5 years of experience required.",
            job_id,
        ),
    )
    conn.commit()
    conn.close()
    newer_application = prepare_application_draft(
        job_id, allow_new_version=True, tracker=tracker
    )["application"]
    ready, missing, _, assessment = application_readiness(newer_application, tracker)
    assert ready is False
    assert any("5 years of experience" in gap.lower() for gap in assessment["mandatory_gaps"])
    assert missing


def test_unverified_requirement_is_not_called_missing_but_blocks_review(workflow_setup):
    tracker, job_id, _ = workflow_setup
    from database.db import get_conn

    conn = get_conn()
    conn.execute(
        "UPDATE jobs SET description = ? WHERE id = ?",
        (
            "Canadian residents may apply. Shift starts at 5:00 PM. "
            "Required qualifications: EDI, RF scanners/peripherals, and TCP/IP networking.",
            job_id,
        ),
    )
    conn.commit()
    conn.close()
    application = prepare_application_draft(job_id, tracker=tracker)["application"]
    ready, missing, _, assessment = application_readiness(application, tracker)
    assert not ready
    assert not assessment["mandatory_gaps"]
    assert set(assessment["requirements_requiring_review"]) == {
        "EDI",
        "RF scanners/peripherals",
        "networking/TCP/IP",
    }
    assert all("not marked missing" in item.lower() for item in missing if "qualification" in item.lower())


def test_manual_schedule_conflict_resolution_is_audited_and_never_submits(workflow_setup):
    tracker, job_id, _ = workflow_setup
    from database.db import get_conn
    from datetime import datetime

    conn = get_conn()
    conn.execute(
        "UPDATE jobs SET description = ?, shift = ? WHERE id = ?",
        (
            "Canadian residents may apply. Shift runs 5:00 PM to 1:00 AM. "
            "Required skills: Python and SQL. Computer Programming Diploma preferred.",
            "Day shift",
            job_id,
        ),
    )
    conn.commit()
    conn.close()

    application = prepare_application_draft(job_id, tracker=tracker)["application"]
    ready, missing, eligibility, _ = application_readiness(application, tracker)
    assert eligibility["status"] == "needs_verification"
    assert eligibility["evening"]["conflict"] is True
    assert not ready
    assert any("conflict" in item.lower() for item in missing)
    assert application["submission_state"] == "NOT_SUBMITTED"
    assert application.get("submitted_at") is None

    saved = save_application_review(
        application["id"],
        tailored_resume=application["tailored_resume"],
        cover_letter=application["cover_letter"],
        answers=application["answers"],
        schedule_resolution_value="confirmed_evening",
        schedule_resolution_source="Employer email",
        schedule_resolution_evidence="Employer confirmed the shift is 5:00 PM to 1:00 AM.",
        tracker=tracker,
    )
    resolution = json.loads(saved["schedule_resolution"])
    datetime.fromisoformat(resolution["timestamp"])
    assert resolution["source"] == "Employer email"
    assert resolution["value"] == "confirmed_evening"
    ready, _, eligibility, _ = application_readiness(saved, tracker)
    assert eligibility["status"] == "confirmed_evening"
    assert ready is True
    assert saved["submission_state"] == "NOT_SUBMITTED"
    assert saved.get("submitted_at") is None
    assert any(
        event["event_type"] == "schedule_conflict_resolved"
        for event in tracker.get_application_events(application["id"])
    )


def test_resume_header_uses_verified_profile_or_original_resume(workflow_setup):
    from documents.application_documents import (
        generate_tailored_resume,
        resume_header_details,
    )

    profile = {}
    source_resume = (
        "Taylor Candidate\n"
        "taylor@example.test | 416-555-0101\n"
        "Experience\nSoftware Developer 2020-2023\n"
    )
    header, missing = resume_header_details(profile, source_resume)
    assert missing == []
    assert header["name"] == "Taylor Candidate"
    assert header["email"] == "taylor@example.test"
    assert header["phone"] == "416-555-0101"
    generated = generate_tailored_resume(
        profile,
        source_resume,
        {"job_title": "Support Analyst", "employer": "Northstar"},
    )
    assert generated.startswith("Taylor Candidate\n")
    assert generated.count("Taylor Candidate") == 1
    assert "taylor@example.test | 416-555-0101" in generated


def test_missing_resume_header_fields_are_reported_in_readiness(workflow_setup, monkeypatch):
    tracker, job_id, resume_id = workflow_setup
    from documents import resume_manager

    resume_manager.update_resume(
        resume_id,
        text="Experience\nSoftware Developer 2020-2023\nPython support.",
    )
    monkeypatch.setattr(MatchingAgent, "load_profile", lambda self: {})
    application = prepare_application_draft(job_id, tracker=tracker)["application"]
    _, missing, _, _ = application_readiness(application, tracker)
    header_warning = next(
        item for item in missing if item.startswith("Resume header needs")
    )
    assert "candidate name" in header_warning
    assert "email or phone number" in header_warning


def test_questions_have_provenance_and_sensitive_answers_need_review(workflow_setup):
    tracker, job_id, _ = workflow_setup
    question = "Are you legally authorized to work in Canada?"
    prepared = prepare_application_draft(
        job_id, supplied_questions=question, tracker=tracker
    )
    application = prepared["application"]
    answers = json.loads(application["answers"])

    assert len(answers) == 1
    assert answers[0]["question"] == question
    assert answers[0]["answer"] is None
    assert answers[0]["supporting_information"] == ""
    assert answers[0]["requires_review"] is True
    assert answers[0]["question_source"] == "supplied_application_information"
    assert not application_readiness(application, tracker)[0]

    answers[0]["answer"] = "Yes, I am legally authorized to work in Canada."
    answers[0]["verification"] = "USER_CONFIRMED"
    saved = save_application_review(
        application["id"],
        tailored_resume=application["tailored_resume"],
        cover_letter=application["cover_letter"],
        answers=answers,
        supplied_questions=question,
        tracker=tracker,
    )
    updated = json.loads(saved["answers"])
    assert updated[0]["verification"] == "USER_CONFIRMED"


def test_application_instructions_and_headings_do_not_block_readiness(workflow_setup):
    tracker, job_id, _ = workflow_setup
    from database.db import get_conn

    conn = get_conn()
    conn.execute(
        "UPDATE jobs SET description = ? WHERE id = ?",
        (
            "Canadian residents may apply. Shift runs 5:00 PM to 10:00 PM. "
            "Required skills: Python and SQL. Computer Programming Diploma preferred.\n"
            "How To Apply:\nSubmit your resume on the employer website.\n"
            "Privacy Notice:\nYour information is protected.",
            job_id,
        ),
    )
    conn.commit()
    conn.close()
    application = prepare_application_draft(job_id, tracker=tracker)["application"]
    assert json.loads(application["answers"]) == []
    ready, missing, _, _ = application_readiness(application, tracker)
    assert ready is True, missing


def test_employment_question_uses_original_resume_as_supporting_information(workflow_setup):
    tracker, job_id, _ = workflow_setup
    application = prepare_application_draft(
        job_id,
        supplied_questions="Describe your employment history?",
        tracker=tracker,
    )["application"]
    answer = json.loads(application["answers"])[0]
    assert "Software Developer, Northstar 2020-2023" in answer["answer"]
    assert answer["source"] == "original_resume"
    assert answer["supporting_information"] == (
        "Original resume: employment/experience section"
    )


def test_document_exports_are_downloadable_files(tmp_path, monkeypatch, workflow_setup):
    tracker, job_id, _ = workflow_setup
    monkeypatch.setattr(resume_export, "EXPORT_DIR", str(tmp_path / "exports"))
    application = prepare_application_draft(job_id, tracker=tracker)["application"]
    docx_path = resume_export.export_docx(
        application["tailored_resume"], "resume.docx"
    )
    pdf_path = resume_export.export_pdf(
        application["cover_letter"], "letter.pdf"
    )

    assert (tmp_path / "exports" / "resume.docx").stat().st_size > 0
    assert (tmp_path / "exports" / "letter.pdf").stat().st_size > 0
    assert docx_path.endswith("resume.docx")
    assert pdf_path.endswith("letter.pdf")
    escaped_path = resume_export.export_pdf("text", "../../outside.pdf")
    assert escaped_path.startswith(str(tmp_path / "exports"))
    assert not (tmp_path / "outside.pdf").exists()


def test_compact_resume_pdf_pagination_uses_two_pages(tmp_path, monkeypatch):
    from pypdf import PdfReader

    monkeypatch.setattr(resume_export, "EXPORT_DIR", str(tmp_path / "exports"))
    content = "\n".join(
        f"Verified work history details for role {index}: Python and SQL support."
        for index in range(90)
    )
    path = resume_export.export_pdf(content, "compact-resume.pdf", compact=True)
    assert len(PdfReader(path).pages) == 2


def test_manual_submission_is_approved_audited_and_idempotent(workflow_setup):
    tracker, job_id, _ = workflow_setup
    application = prepare_application_draft(job_id, tracker=tracker)["application"]
    approve_application(application["id"], tracker)
    submitted = mark_manually_submitted(
        application["id"],
        submitted_on="2025-11-03",
        confirmation_ref="REF-123",
        follow_up_date="2025-11-17",
        tracker=tracker,
    )
    assert submitted["status"] == "Manually submitted"
    assert submitted["submission_state"] == "MANUALLY_SUBMITTED"
    assert submitted["submission_method"] == "manual"
    assert submitted["confirmation_ref"] == "REF-123"
    assert submitted["follow_up_date"] == "2025-11-17"
    assert any(
        event["event_type"] == "manual_submission_recorded"
        for event in tracker.get_application_events(application["id"])
    )
    with pytest.raises(ApplicationWorkflowError, match="already recorded"):
        mark_manually_submitted(application["id"], tracker=tracker)


def test_submission_failure_can_only_be_retried_after_readiness(workflow_setup):
    tracker, job_id, _ = workflow_setup
    application = prepare_application_draft(job_id, tracker=tracker)["application"]
    approve_application(application["id"], tracker)
    failed = mark_submission_failed(application["id"], "Employer page error", tracker)
    assert failed["status"] == "Submission failed"
    retried = retry_failed_submission(application["id"], tracker)
    assert retried["status"] == "Approved"
    assert retried["submission_state"] == "APPROVED"


def test_submission_capability_is_manual_only():
    capability = submission_capability()
    assert capability["automated_submission_supported"] is False
    assert capability["method"] == "manual"
    assert "employer-controlled" in capability["reason"]


def test_job_card_prepare_action_opens_review_without_exceptions(workflow_setup):
    from streamlit.testing.v1 import AppTest

    _, _, _ = workflow_setup
    app = AppTest.from_file("app.py").run(timeout=20)
    app.sidebar.radio[0].set_value("Recommended Jobs").run(timeout=20)
    assert len(app.exception) == 0

    prepare_button = next(
        button for button in app.button if button.label == "Prepare Application"
    )
    prepare_button.click().run(timeout=20)

    assert len(app.exception) == 0
    assert app.sidebar.radio[0].value == "My Applications"
    assert app.sidebar.radio[1].value == "Application Review"
    assert any(element.value == "Application Review" for element in app.title)


def test_linkedin_pdf_import_extracts_fields_and_detects_duplicate_content(
    tmp_path, monkeypatch
):
    from reportlab.pdfgen import canvas
    from io import BytesIO

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    for index, line in enumerate(
        (
            "Experience",
            "Software Developer | Northstar 2020-2023",
            "- Built Python and SQL automation",
            "Education",
            "Computer Programming Diploma, Algonquin College",
            "Skills",
            "Python, SQL, React",
            "Certifications",
            "Azure Fundamentals",
        )
    ):
        pdf.drawString(40, 750 - index * 24, line)
    pdf.save()
    content = buffer.getvalue()
    monkeypatch.setattr(linkedin_import, "IMPORT_DIR", str(tmp_path / "linkedin"))
    monkeypatch.setattr(
        linkedin_import, "INDEX_PATH", str(tmp_path / "linkedin" / "imports.json")
    )

    imported = linkedin_import.import_linkedin_pdf(content, "linkedin.pdf")
    duplicate = linkedin_import.import_linkedin_pdf(content, "renamed-copy.pdf")
    parsed = imported["parsed"]

    assert "Software Developer" in imported["text"]
    assert parsed["experience"]
    assert parsed["education"]
    assert "Python" in parsed["skills"]
    assert parsed["certifications"]
    assert imported["duplicate"] is False
    assert duplicate["duplicate"] is True
    comparison = compare_structured(PROFILE, parsed)
    assert "Python" in comparison["skills"]["in_both"]
    assert comparison["experience"]["imported"]
    assert comparison["education"]["imported"]
