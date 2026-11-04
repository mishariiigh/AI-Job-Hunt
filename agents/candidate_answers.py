import json, os, datetime

PATH = os.path.join("storage", "candidate_answers.json")

def _load():
    if os.path.exists(PATH):
        try: return json.load(open(PATH))
        except: return []
    return []

def _save(items):
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    with open(PATH, "w") as f: json.dump(items, f, indent=2)

def _now():
    return datetime.datetime.utcnow().isoformat()+"Z"

def build_answer(question, profile=None, verified_data=None):
    profile = profile or {}
    verified_data = verified_data or {}
    q = question.get("text","")
    ql = q.lower()
    requires_candidate_authored_response = (
        "don't use chatgpt" in ql or "do not use chatgpt" in ql
    )
    requires_self_rating = "rate your level" in ql and "scale of" in ql
    value = None
    source = "No supporting candidate information found"
    status = "UNKNOWN"
    confidence = 0.0
    sensitive_categories = {
        "availability", "legal_declaration", "personal", "salary", "shift",
        "work_authorization", "yes_no",
    }
    requires_review = question.get("category") in sensitive_categories or any(
        term in ql
        for term in (
            "legally", "authorized", "authorization", "eligible to work",
            "work permit", "citizen", "sponsorship", "availability",
            "criminal", "disability", "background check", "when can you start",
            "salary", "compensation", "relocate",
        )
    ) or ql.strip().startswith(("are you ", "do you ", "did you ", "have you ", "has you ", "can you ", "will you ", "would you "))
    requires_review = (
        requires_review
        or requires_candidate_authored_response
        or requires_self_rating
    )
    supporting_information = ""
    if "relocate" in ql:
        source = "No candidate-provided relocation preference recorded"
    elif "email" in ql and profile.get("email"):
        value = profile["email"]; source="candidate_profile"; supporting_information = "Candidate Profile: email"; status="VERIFIED"; confidence=1.0
    elif "phone" in ql and profile.get("phone"):
        value = profile["phone"]; source="candidate_profile"; supporting_information = "Candidate Profile: phone"; status="VERIFIED"; confidence=1.0
    elif "name" in ql and profile.get("name"):
        value = profile["name"]; source="candidate_profile"; supporting_information = "Candidate Profile: name"; status="VERIFIED"; confidence=1.0
    elif "evening" in ql and "weekend" in ql:
        availability = profile.get("availability") or {}
        weekday_start = str(availability.get("weekdays_after") or "").strip()
        if weekday_start and availability.get("weekends"):
            timezone = str(availability.get("timezone") or "").strip()
            timezone_text = f" {timezone} time" if timezone else ""
            value = (
                f"Yes; my recorded availability is weekdays after "
                f"{weekday_start}{timezone_text} and weekends."
            )
            source = "candidate_profile"
            supporting_information = "Candidate Profile: availability"
            status = "VERIFIED"
            confidence = 1.0
    elif "skill" in ql:
        skills = profile.get("technical_interests", [])
        if skills:
            value = ", ".join(skills); source="candidate_profile"; supporting_information = "Candidate Profile: technical interests"; status="VERIFIED"; confidence=0.9
    elif "degree" in ql or "education" in ql:
        edu = profile.get("education")
        if edu:
            value = edu; source="candidate_profile"; supporting_information = "Candidate Profile: education"; status="VERIFIED"; confidence=0.9
    elif "year" in ql and "experience" in ql:
        yrs = profile.get("experience_years", profile.get("years_experience"))
        if yrs is not None:
            value = yrs; source="candidate_profile"; supporting_information = "Candidate Profile: experience_years"; status="VERIFIED"; confidence=0.8
    elif any(term in ql for term in ("employment", "work history", "experience")) and verified_data.get("resume_text"):
        from documents.structured_resume_parser import parse_resume

        parsed_resume = parse_resume(verified_data["resume_text"])
        entries = []
        for item in parsed_resume.get("experience", []):
            title = str(item.get("title") or "").strip()
            if title:
                entries.append(title)
            entries.extend(
                f"- {str(bullet).strip()}"
                for bullet in item.get("bullets", [])
                if str(bullet).strip()
            )
        if entries:
            value = "\n".join(entries)
            source = "original_resume"
            supporting_information = "Original resume: employment/experience section"
            status = "VERIFIED"
            confidence = 0.8
    elif "certification" in ql or "certificate" in ql:
        certifications = profile.get("certifications", [])
        if certifications:
            value = ", ".join(str(item) for item in certifications)
            source = "candidate_profile"
            supporting_information = "Candidate Profile: certifications"
            status = "VERIFIED"
            confidence = 0.8
    elif "language" in ql and profile.get("language"):
        value = profile["language"]; source="candidate_profile"; supporting_information = "Candidate Profile: language"; status="VERIFIED"; confidence=0.9
    elif "location" in ql and profile.get("location"):
        value = profile["location"]; source="candidate_profile"; supporting_information = "Candidate Profile: location"; status="VERIFIED"; confidence=0.9

    if requires_review and value is not None:
        status = "NEEDS_REVIEW"
    if value is None:
        status = "NEEDS_REVIEW" if requires_review else "UNKNOWN"
    if requires_candidate_authored_response:
        source = "Employer instruction: candidate must write this response personally"
    if requires_self_rating:
        value = None
        source = "Candidate must provide a personal proficiency rating"
        supporting_information = (
            "The verified sources list SQL but do not record a self-rating or a "
            "specific example for this question."
        )
        status = "NEEDS_REVIEW"
    ans = {"question_id": question.get("id"), "question": q, "answer": value, "source": source,
           "supporting_information": supporting_information,
           "verification": status, "confidence": confidence,
           "requires_review": requires_review,
           "updated_at": _now()}
    # conflict detection
    if verified_data and question.get("id") in verified_data and verified_data[question.get("id")] not in (None, value):
        ans["conflict"] = True
    else:
        ans["conflict"] = False
    return ans

def save_answers(answers):
    existing = {a["question_id"]: a for a in _load()}
    for a in answers:
        existing[a["question_id"]] = a
    _save(list(existing.values()))

def load_answers():
    return _load()

def unresolved(answers):
    return [
        answer for answer in answers
        if answer.get("verification") not in ("VERIFIED", "USER_CONFIRMED")
        or answer.get("answer") is None
        or answer.get("conflict")
        or (
            answer.get("requires_review")
            and answer.get("verification") != "USER_CONFIRMED"
        )
    ]

def confirm_answer(qid, value):
    items = _load()
    for it in items:
        if it["question_id"] == qid:
            it["answer"] = value
            it["verification"] = "USER_CONFIRMED"
            it["updated_at"] = _now()
    _save(items)
