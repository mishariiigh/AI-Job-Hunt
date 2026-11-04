import json, os, tempfile
from agents.application_questions import classify_question, extract_questions, mark_optional
from agents.candidate_answers import build_answer, save_answers, load_answers, unresolved, confirm_answer

def test_classify():
    assert classify_question("What is your email?") == "contact"
    assert classify_question("Do you have SQL skills?") == "skills"

def test_extract_required_optional():
    text = "What is your name?\nOptional: salary expectations?"
    qs = mark_optional(extract_questions(text))
    assert len(qs) >= 1
    assert any(q["required"] is False for q in qs)


def test_realistic_job_text_ignores_headings_instructions_and_notices():
    text = """\
How To Apply:
Submit your resume through the employer application page.
Privacy Notice:
How is your information handled according to our privacy policy?
Equal Opportunity Employer:
Are all qualified applicants considered without regard to protected status?
Application Questions:
Are you legally authorized to work in Canada?
Describe your relevant SQL support experience.
"""
    questions = extract_questions(text, source="job_description")
    assert [question["text"] for question in questions] == [
        "Are you legally authorized to work in Canada?",
        "Describe your relevant SQL support experience.",
    ]
    assert all(question["source"] == "job_description" for question in questions)
    assert all(question["required"] for question in questions)


def test_how_to_apply_heading_is_never_an_application_question():
    assert extract_questions("How To Apply:\nApply online now.") == []


def test_d2l_application_questions_keep_required_markers_and_personal_response_notice():
    text = """\
Are you legally eligible to work in Canada where this position is located?*
Are you willing to relocate to the location for which this role is posted?*
Are you available to work evenings and weekends?*
Please rate your level of experience and knowledge in SQL on a scale of 1 to 5, with 1 being basic knowledge and 5 being advanced expertise. Additionally, please briefly describe your experience using SQL in a professional or academic setting?*
What is the main factor that influenced your decision to apply to D2L? (Please don't use ChatGPT, we want to know why YOU applied)
"""
    assert extract_questions(
        "How To Apply:\nSubmit your application through our online career portal."
    ) == []
    questions = extract_questions(text, source="d2l_application_form")
    assert [question["text"] for question in questions] == [
        "Are you legally eligible to work in Canada where this position is located?*",
        "Are you willing to relocate to the location for which this role is posted?*",
        "Are you available to work evenings and weekends?*",
        "Please rate your level of experience and knowledge in SQL on a scale of 1 to 5, with 1 being basic knowledge and 5 being advanced expertise. Additionally, please briefly describe your experience using SQL in a professional or academic setting?*",
        "What is the main factor that influenced your decision to apply to D2L? (Please don't use ChatGPT, we want to know why YOU applied)",
    ]
    assert all(question["source"] == "d2l_application_form" for question in questions)
    relocation_answer = build_answer(
        questions[1], {"location": "Oakville, Ontario, Canada"}
    )
    assert relocation_answer["answer"] is None
    assert relocation_answer["verification"] == "NEEDS_REVIEW"
    assert "relocation preference" in relocation_answer["source"]
    availability_answer = build_answer(
        questions[2],
        {
            "availability": {
                "weekdays_after": "18:00",
                "timezone": "America/Toronto",
                "weekends": True,
            }
        },
    )
    assert availability_answer["answer"] == (
        "Yes; my recorded availability is weekdays after 18:00 "
        "America/Toronto time and weekends."
    )
    assert availability_answer["verification"] == "NEEDS_REVIEW"
    assert availability_answer["source"] == "candidate_profile"
    sql_answer = build_answer(
        questions[3],
        {"technical_interests": ["SQL"]},
        verified_data={"resume_text": "The original resume lists Microsoft SQL Server."},
    )
    assert sql_answer["answer"] is None
    assert sql_answer["verification"] == "NEEDS_REVIEW"
    assert "self-rating" in sql_answer["supporting_information"]
    personal_question = questions[-1]
    answer = build_answer(personal_question, {})
    assert answer["answer"] is None
    assert answer["verification"] == "NEEDS_REVIEW"
    assert "write this response personally" in answer["source"]


def test_verified_answer():
    profile = {"name":"A","email":"a@b.com","technical_interests":["Python"]}
    q = {"id":"q1","text":"What is your email?"}
    a = build_answer(q, profile)
    assert a["verification"] == "VERIFIED"
    assert a["answer"] == "a@b.com"

def test_unknown_answer():
    q = {"id":"q2","text":"Years of experience?"}
    a = build_answer(q, {})
    assert a["verification"] == "UNKNOWN"
    assert a["answer"] is None

def test_persistence():
    d = tempfile.mkdtemp()
    os.environ["ANSWER_PATH"] = os.path.join(d,"a.json")
    # monkeypatch path
    import agents.candidate_answers as ca
    ca.PATH = os.path.join(d,"a.json")
    ans = [{"question_id":"q1","question":"name?","answer":"A","source":"profile","verification":"VERIFIED","confidence":1.0,"updated_at":"x","conflict":False}]
    save_answers(ans)
    assert load_answers()[0]["answer"] == "A"

def test_confirm():
    import agents.candidate_answers as ca
    tmp = tempfile.mkdtemp()
    ca.PATH = os.path.join(tmp,"a.json")
    save_answers([{"question_id":"q1","question":"x?","answer":None,"source":None,"verification":"UNKNOWN","confidence":0.0,"updated_at":"x","conflict":False}])
    confirm_answer("q1","yes")
    assert load_answers()[0]["verification"] == "USER_CONFIRMED"
    assert load_answers()[0]["answer"] == "yes"

def test_unresolved():
    ans = [{"verification":"UNKNOWN","answer":None,"conflict":False},{"verification":"VERIFIED","answer":"x","conflict":False}]
    assert len(unresolved(ans)) == 1
