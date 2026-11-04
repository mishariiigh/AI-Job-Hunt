from docx import Document
from pypdf import PdfReader
import pytest

from documents import resume_export
from documents.application_documents import (
    generate_cover_letter,
    generate_tailored_resume,
    resume_header_details,
)


PROFILE = {
    "name": "",
    "email": "",
    "phone": "",
    "location": "Oakville, Ontario, Canada",
    "education": "Computer Programming Diploma, Sample College",
    "career_direction": "Application development",
    "technical_interests": ["Python", "SQL", "Windows Authentication", "REST APIs"],
}

SOURCE_RESUME = """Alex Morgan
Web Application Developer | Sample Agency IT-01
Oakville, ON | +1 416-555-0101 | alex.morgan@example.test
PROFESSIONAL SUMMARY
IT professional with nearly 5 years of experience supporting internal applications.
TECHNICAL SKILLS
• Languages & Frameworks: Java, Python, SQL, React
• Cloud & Infrastructure: REST APIs, Networking/DNS, Azure
PROFESSIONAL EXPERIENCE
Web Application Developer (IT-01) June 2022 – Present
Sample Agency — Ontario
• Built the Presence System using Windows Authentication.
• Identify and resolve code issues through structured troubleshooting and testing.
EDUCATION
Diploma in Computer Programming
Sample College
"""

JOB = {
    "employer": "Northstar Systems",
    "job_title": "IT Support Analyst",
    "description": (
        "Provide application troubleshooting, Windows authentication, "
        "networking/DNS, REST APIs, and SQL support."
    ),
}


def test_linkedin_resume_header_skips_section_titles_and_finds_candidate_name():
    profile, missing = resume_header_details(
        {},
        """Contact
+1 416-555-0101
alex@example.test
Top Skills
User Interface Design
Languages
IT Professional Development
Program Certificate
Alex Morgan
Web Developer | Sample Agency | Python
Summary
""",
    )

    assert profile["name"] == "Alex Morgan"
    assert profile["email"] == "alex@example.test"
    assert profile["phone"] == "+1 416-555-0101"
    assert missing == []


def test_tailored_resume_uses_single_source_backed_section_hierarchy():
    resume = generate_tailored_resume(PROFILE, SOURCE_RESUME, JOB)

    assert resume.startswith(
        "Alex Morgan\nalex.morgan@example.test | +1 416-555-0101"
    )
    assert resume.count("PROFESSIONAL SUMMARY") == 1
    assert resume.count("TECHNICAL SKILLS") == 1
    assert resume.count("EDUCATION") == 1
    assert "Web Application Developer June 2022 – Present" in resume
    assert "Identify and resolve code issues through structured troubleshooting and testing." in resume
    assert "IT-01" not in resume.upper()
    assert resume.index("REST APIs") < resume.index("Java, Python, SQL")


def test_cover_letter_is_job_specific_and_uses_verified_resume_evidence():
    letter = generate_cover_letter(PROFILE, SOURCE_RESUME, JOB)

    assert letter.startswith("Alex Morgan\nalex.morgan@example.test")
    assert "Dear Northstar Systems Hiring Team" in letter
    assert "IT Support Analyst position with Northstar Systems" in letter
    assert "Built the Presence System using Windows Authentication." in letter
    assert "Computer Programming Diploma, Sample College" in letter
    assert "career direction" not in letter.lower()
    assert "led a team" not in letter.lower()


def test_pdf_and_docx_render_consistent_resume_hierarchy_and_pages(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(resume_export, "EXPORT_DIR", str(tmp_path))
    bullets = "\n".join(
        f"• Verified application support task {index}: investigated SQL and API issues."
        for index in range(55)
    )
    content = (
        "Taylor Candidate\n"
        "taylor@example.test | 555-0101 | Oakville, Ontario\n"
        "Target role: Support Analyst | Northstar Systems\n\n"
        "PROFESSIONAL SUMMARY\n"
        "Application support specialist with verified troubleshooting experience.\n\n"
        "TECHNICAL SKILLS\n"
        "• Databases: SQL, PostgreSQL\n\n"
        "PROFESSIONAL EXPERIENCE\n"
        f"Support Analyst 2020 – Present\nNorthstar Systems\n{bullets}\n"
    )
    pdf_path = resume_export.export_pdf(content, "resume.pdf", compact=True)
    docx_path = resume_export.export_docx(content, "resume.docx")
    pdf = PdfReader(pdf_path)
    docx = Document(docx_path)
    extracted_pdf = "\n".join(page.extract_text() or "" for page in pdf.pages)
    docx_text = "\n".join(paragraph.text for paragraph in docx.paragraphs)

    assert len(pdf.pages) == 2
    assert "Taylor Candidate" in extracted_pdf
    assert "TECHNICAL SKILLS" in extracted_pdf
    assert "Support Analyst" in extracted_pdf
    assert "Verified application support task 54" in extracted_pdf
    assert docx.sections[0].page_width.inches == pytest.approx(8.5)
    assert docx.sections[0].left_margin.inches == pytest.approx(0.68, abs=0.001)
    assert "Taylor Candidate" in docx_text
    assert "TECHNICAL SKILLS" in docx_text
    assert "Verified application support task 54" in docx_text
    assert any(
        paragraph.text == "TECHNICAL SKILLS"
        and paragraph.paragraph_format.keep_with_next
        for paragraph in docx.paragraphs
    )


def test_pdf_and_docx_reject_structured_documents_without_verified_header(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(resume_export, "EXPORT_DIR", str(tmp_path))
    content = "PROFESSIONAL SUMMARY\nA candidate summary."

    with pytest.raises(ValueError, match="verified candidate name"):
        resume_export.export_pdf(content, "missing-header.pdf")
    with pytest.raises(ValueError, match="verified candidate name"):
        resume_export.export_docx(content, "missing-header.docx")


def test_docx_starts_projects_on_new_page_when_prior_resume_content_is_long(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(resume_export, "EXPORT_DIR", str(tmp_path))
    experience = "\n".join(
        f"• Verified work history detail {index}: maintained applications and resolved technical issues."
        for index in range(28)
    )
    content = (
        "Taylor Candidate\n"
        "taylor@example.test | 555-0101\n\n"
        "PROFESSIONAL EXPERIENCE\n"
        f"Support Analyst 2020 – Present\nNorthstar Systems\n{experience}\n"
        "PROJECT EXPERIENCE\n"
        "• Built a source-documented application project.\n"
    )
    path = resume_export.export_docx(content, "long-resume.docx")
    document = Document(path)
    project_heading = next(
        paragraph for paragraph in document.paragraphs
        if paragraph.text == "PROJECT EXPERIENCE"
    )

    assert project_heading.paragraph_format.page_break_before is True


def test_cover_letter_exports_have_identity_and_employer_in_both_formats(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(resume_export, "EXPORT_DIR", str(tmp_path))
    letter = generate_cover_letter(PROFILE, SOURCE_RESUME, JOB)
    pdf_path = resume_export.export_pdf(letter, "letter.pdf")
    docx_path = resume_export.export_docx(letter, "letter.docx")
    pdf_text = "\n".join(
        page.extract_text() or "" for page in PdfReader(pdf_path).pages
    )
    docx_text = "\n".join(
        paragraph.text for paragraph in Document(docx_path).paragraphs
    )

    assert len(PdfReader(pdf_path).pages) == 1
    for text in (pdf_text, docx_text):
        assert "Alex Morgan" in text
        assert "Northstar Systems" in text
        assert "IT Support Analyst" in text
        assert "Windows Authentication" in text
