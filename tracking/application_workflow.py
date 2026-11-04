import json
from datetime import date, datetime

from agents.application_questions import extract_questions, mark_optional
from agents.candidate_answers import build_answer, unresolved
from agents.job_classifier import (
    classify_evening_eligibility,
    classify_opportunity,
)
from agents.matching_agent import MatchingAgent
from documents.application_documents import (
    generate_cover_letter,
    generate_tailored_resume,
)
from documents.resume_manager import get_default, get_resume, list_resumes
from tracking.application_tracker import ApplicationTracker


class ApplicationWorkflowError(ValueError):
    pass


def build_schedule_inquiry(job, profile=None):
    schedule = classify_evening_eligibility(job)
    if not schedule.get("needs_schedule_verification"):
        return ""
    profile = profile or {}
    employer = str(job.get("employer") or "the hiring team").strip()
    title = str(job.get("job_title") or "this role").strip()
    evidence = [
        str(item.get("value") or "").strip()
        for item in schedule.get("evidence_sources", [])
        if item.get("value")
    ]
    if schedule.get("conflict"):
        description_evidence = next(
            (
                str(item.get("value") or "").strip()
                for item in schedule.get("evidence_sources", [])
                if item.get("source") == "job_description"
            ),
            "hours",
        )
        metadata_evidence = next(
            (
                str(item.get("value") or "").strip()
                for item in schedule.get("evidence_sources", [])
                if item.get("source") == "structured_metadata"
            ),
            "schedule metadata",
        )
        evidence_text = (
            f" The description lists {description_evidence}, while the structured "
            f"schedule metadata says {metadata_evidence}."
        )
    else:
        evidence_text = (
            f" I noticed the posting mentions {', '.join(dict.fromkeys(evidence))}."
            if evidence
            else ""
        )
    if schedule.get("conflict"):
        schedule_request = (
            " Could you confirm which schedule is accurate and provide the exact "
            "scheduled start and end times? Please also confirm "
            "whether the role is still open."
        )
        if "5:00 PM" in description_evidence:
            schedule_request += (
                " Does the employer confirm a regular shift starting at or after "
                "5:00 PM Toronto time?"
            )
        schedule_request += (
            " I am also interested in whether a part-time schedule of approximately "
            "20–25 hours per week is an option."
        )
    else:
        schedule_request = (
            " Could you share the exact shift start and end times, how weekday/evening/"
            "weekend rotations are assigned, and whether rotation is required for every "
            "employee? Is a fixed evening-only schedule beginning at or after 5:00 PM "
            "Toronto time available? I am also interested in whether a part-time schedule "
            "of approximately 20–25 hours per week is an option."
        )
    inquiry = (
        f"Hello {employer} hiring team,\n\n"
        f"I’m interested in the {title} position.{evidence_text}{schedule_request}"
    )
    education = str(profile.get("education") or "").strip()
    years = profile.get("experience_years", profile.get("years_experience"))
    try:
        years = float(years)
    except (TypeError, ValueError):
        years = None
    description = str(job.get("description") or "")
    if education and years and "equivalent technical experience" in description.lower():
        years_text = f"{years:g}"
        if "," in education:
            credential, institution = education.rsplit(",", 1)
            education_claim = f"{credential.strip()} from {institution.strip()}"
        else:
            education_claim = education
        if "diploma" in education_claim.lower():
            education_claim = f"a {education_claim}"
        inquiry += (
            "\n\nThe posting recommends a bachelor's degree or equivalent technical "
            f"experience. My education includes {education_claim}, and I have approximately "
            f"{years_text} "
            "years of relevant experience. Would that combination satisfy the "
            "equivalent technical experience recommendation?"
        )
    return inquiry + "\n\nThank you."


def _json(value, default):
    if not value:
        return default
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError):
        return default


def _eligibility(job, evidence="", schedule_resolution=""):
    evaluated_job = dict(job)
    if evidence.strip():
        evaluated_job["description"] = (
            f"{evaluated_job.get('description') or ''}\n"
            f"Employer information verified by candidate: {evidence.strip()}"
        )
    return classify_opportunity(evaluated_job, schedule_resolution)


def _assessment(
    job, profile, eligibility, evidence="", resume_text="", schedule_resolution=""
):
    evaluated_job = dict(job)
    if evidence.strip():
        evaluated_job["description"] = (
            f"{evaluated_job.get('description') or ''}\n{evidence.strip()}"
        )
    return MatchingAgent(profile).unified_suitability(
        evaluated_job, profile, resume_text, schedule_resolution
    )


def _question_answers(job, profile, supplied_text="", previous=None, resume_text=""):
    previous_by_text = {
        answer.get("question"): answer for answer in (previous or [])
    }
    questions = mark_optional(
        [
            *extract_questions(
                job.get("description") or "", source="job_description"
            ),
            *extract_questions(
                supplied_text or "",
                source="supplied_application_information",
            ),
        ]
    )
    unique_questions = []
    seen = set()
    for question in questions:
        key = question["text"].casefold()
        if key not in seen:
            unique_questions.append(question)
            seen.add(key)
    answers = []
    for question in unique_questions:
        answer = build_answer(
            question, profile, verified_data={"resume_text": resume_text}
        )
        old = previous_by_text.get(question["text"])
        if old:
            answer["answer"] = old.get("answer")
            answer["verification"] = old.get("verification", answer["verification"])
            answer["requires_review"] = (
                answer["requires_review"] or old.get("requires_review", False)
            )
        answer["required"] = question.get("required", True)
        answer["question_source"] = question.get("source", "")
        answers.append(answer)
    return answers


def _missing_information(job, profile, resume, eligibility, assessment, answers):
    missing = []
    if not any(value for value in profile.values()):
        missing.append("The verified Candidate Profile could not be loaded.")
    if not job.get("description"):
        missing.append("The full employer job description is missing.")
    if eligibility["status"] == "needs_verification":
        missing.extend(eligibility["reasons"])
    elif eligibility["status"] == "rejected":
        missing.extend(eligibility["reasons"])
    if not resume or not (resume.get("text") or "").strip():
        missing.append("Select or add the original resume before approval.")
    if eligibility["status"] == "confirmed_evening":
        if assessment.get("reason") and not assessment.get("eligible"):
            missing.append(assessment["reason"])
        missing.extend(assessment.get("mandatory_gaps", []))
        missing.extend(
            "Mandatory qualification requires your verification (not marked missing): "
            + requirement
            for requirement in assessment.get("requirements_requiring_review", [])
        )
    if resume:
        from documents.application_documents import resume_header_details
        _, missing_header_fields = resume_header_details(
            profile, resume.get("text") or ""
        )
        if missing_header_fields:
            missing.append(
                "Resume header needs verified information: "
                + ", ".join(missing_header_fields)
                + ". Update Candidate Profile or the original resume."
            )
    for answer in unresolved(answers):
        if answer.get("required", True):
            missing.append(f"Employer question needs an answer or review: {answer['question']}")
    return list(dict.fromkeys(missing))


def prepare_application_draft(
    job_id,
    allow_new_version=False,
    resume_id=None,
    supplied_questions="",
    tracker=None,
):
    tracker = tracker or ApplicationTracker()
    job = tracker.get_job(job_id)
    if not job:
        raise ApplicationWorkflowError(f"Job {job_id} does not exist.")
    eligibility = _eligibility(job)
    if eligibility["status"] == "rejected":
        raise ApplicationWorkflowError(
            "This job is rejected by the eligibility rules and cannot become an application draft: "
            + "; ".join(eligibility["reasons"])
        )

    matcher = MatchingAgent()
    profile = matcher.load_profile()
    list_resumes()
    resume = get_resume(resume_id) if resume_id else get_default()
    if resume_id and not resume:
        raise ApplicationWorkflowError("The selected original resume no longer exists.")
    if not resume:
        resume = None

    resume_text = resume.get("text", "") if resume else ""
    assessment = _assessment(
        job, profile, eligibility, resume_text=resume_text
    )
    answers = _question_answers(
        job, profile, supplied_questions, resume_text=resume_text
    )
    schedule_inquiry = build_schedule_inquiry(job, profile)
    tailored_resume = generate_tailored_resume(profile, resume_text, job)
    cover_letter = generate_cover_letter(profile, resume_text, job)
    missing = _missing_information(
        job, profile, resume, eligibility, assessment, answers
    )
    status = "Needs information" if missing else "Draft"
    resume_version = ""
    if resume:
        resume_version = f"{resume.get('id', '')}:{resume.get('filename', '')}"

    draft = {
        "status": status,
        "resume_id": resume.get("id") if resume else None,
        "resume_filename": resume.get("filename") if resume else None,
        "resume_version": resume_version,
        "tailored_resume": tailored_resume,
        "cover_letter": cover_letter,
        "answers": json.dumps(answers),
        "additional_questions": supplied_questions or "",
        "schedule_inquiry": schedule_inquiry,
        "eligibility_status": eligibility["status"],
        "eligibility_reasons": json.dumps(eligibility["reasons"]),
        "eligibility_verification": "",
        "schedule_resolution": "",
        "qualification_assessment": json.dumps(assessment),
        "missing_information": json.dumps(missing),
        "notes": "Draft generated from the selected job and verified candidate sources.",
    }
    application_id, created = tracker.create_application_draft(
        job_id, draft, allow_new_version=allow_new_version
    )
    return {
        "application": tracker.get_application(application_id),
        "created": created,
        "eligibility": eligibility,
        "assessment": assessment,
        "missing_information": missing,
    }


def application_readiness(application, tracker=None):
    tracker = tracker or ApplicationTracker()
    job = tracker.get_job(application["job_id"])
    if not job:
        return False, ["The linked job is no longer available."], None, None
    profile = MatchingAgent().load_profile()
    evidence = application.get("eligibility_verification") or ""
    schedule_resolution = application.get("schedule_resolution") or ""
    eligibility = _eligibility(job, evidence, schedule_resolution)
    resume = get_resume(application.get("resume_id")) if application.get("resume_id") else None
    assessment = _assessment(
        job,
        profile,
        eligibility,
        evidence,
        resume.get("text", "") if resume else "",
        schedule_resolution,
    )
    answers = _json(application.get("answers"), [])
    missing = _missing_information(job, profile, resume, eligibility, assessment, answers)
    if not (application.get("tailored_resume") or "").strip():
        missing.append("Tailored resume is missing.")
    if not (application.get("cover_letter") or "").strip():
        missing.append("Cover letter is missing.")
    return not missing, list(dict.fromkeys(missing)), eligibility, assessment


def save_application_review(
    application_id,
    *,
    tailored_resume,
    cover_letter,
    answers,
    eligibility_verification="",
    schedule_resolution_value="",
    schedule_resolution_source="",
    schedule_resolution_evidence="",
    supplied_questions="",
    schedule_inquiry=None,
    resume_id=None,
    tracker=None,
):
    tracker = tracker or ApplicationTracker()
    application = tracker.get_application(application_id)
    if not application:
        raise ApplicationWorkflowError(f"Application {application_id} does not exist.")
    if application.get("status") in {"Submitted", "Manually submitted"}:
        raise ApplicationWorkflowError("A submitted application cannot be edited.")

    job = tracker.get_job(application["job_id"])
    if not job:
        raise ApplicationWorkflowError("The linked job is no longer available.")
    profile = MatchingAgent().load_profile()
    selected_resume_id = resume_id or application.get("resume_id")
    resume = get_resume(selected_resume_id) if selected_resume_id else None
    if resume_id and not resume:
        raise ApplicationWorkflowError("The selected original resume no longer exists.")
    if schedule_resolution_value in {"confirmed_evening", "incompatible"}:
        source = str(schedule_resolution_source or "").strip()
        resolution_evidence = str(schedule_resolution_evidence or "").strip()
        if not source or not resolution_evidence:
            raise ApplicationWorkflowError(
                "A schedule resolution requires its source and supporting evidence."
            )
        schedule_resolution = json.dumps(
            {
                "value": schedule_resolution_value,
                "source": source,
                "evidence": resolution_evidence,
                "timestamp": datetime.now().astimezone().isoformat(),
            }
        )
    elif schedule_resolution_value == "unresolved":
        schedule_resolution = ""
    else:
        schedule_resolution = application.get("schedule_resolution") or ""
    parsed_answers = _json(answers, [])
    merged_answers = _question_answers(
        job,
        profile,
        supplied_questions,
        previous=parsed_answers,
        resume_text=resume.get("text", "") if resume else "",
    )
    inquiry_text = (
        str(schedule_inquiry)
        if schedule_inquiry is not None
        else str(application.get("schedule_inquiry") or "")
    )
    eligibility = _eligibility(
        job, eligibility_verification, schedule_resolution
    )
    assessment = _assessment(
        job,
        profile,
        eligibility,
        eligibility_verification,
        resume.get("text", "") if resume else "",
        schedule_resolution,
    )
    missing = _missing_information(
        job, profile, resume, eligibility, assessment, merged_answers
    )
    if not (tailored_resume or "").strip():
        missing.append("Tailored resume is missing.")
    if not (cover_letter or "").strip():
        missing.append("Cover letter is missing.")
    status = "Needs information" if missing else "Ready for review"
    resolution_record = _json(schedule_resolution, {})
    return tracker.update_application(
        application_id,
        {
            "tailored_resume": tailored_resume,
            "cover_letter": cover_letter,
            "answers": json.dumps(merged_answers),
            "additional_questions": supplied_questions or "",
            "schedule_inquiry": inquiry_text,
            "resume_id": selected_resume_id,
            "resume_filename": resume.get("filename") if resume else None,
            "resume_version": (
                f"{resume.get('id', '')}:{resume.get('filename', '')}" if resume else ""
            ),
            "eligibility_verification": eligibility_verification or "",
            "schedule_resolution": schedule_resolution,
            "eligibility_status": eligibility["status"],
            "eligibility_reasons": json.dumps(eligibility["reasons"]),
            "qualification_assessment": json.dumps(assessment),
            "missing_information": json.dumps(list(dict.fromkeys(missing))),
            "status": status,
        },
        event_type=(
            "schedule_conflict_resolved"
            if resolution_record
            else "review_saved"
        ),
        details=(
            f"source={resolution_record.get('source')}; "
            f"timestamp={resolution_record.get('timestamp')}"
            if resolution_record
            else ""
        ),
    )


def regenerate_documents(application_id, resume_id=None, tracker=None):
    tracker = tracker or ApplicationTracker()
    application = tracker.get_application(application_id)
    if not application:
        raise ApplicationWorkflowError(f"Application {application_id} does not exist.")
    job = tracker.get_job(application["job_id"])
    selected_id = resume_id or application.get("resume_id")
    resume = get_resume(selected_id) if selected_id else None
    if not resume:
        raise ApplicationWorkflowError("Choose an existing original resume to regenerate documents.")
    profile = MatchingAgent().load_profile()
    return {
        "tailored_resume": generate_tailored_resume(profile, resume.get("text", ""), job),
        "cover_letter": generate_cover_letter(profile, resume.get("text", ""), job),
        "resume_id": resume["id"],
        "resume_filename": resume.get("filename"),
        "resume_version": f"{resume.get('id', '')}:{resume.get('filename', '')}",
    }


def approve_application(application_id, tracker=None):
    tracker = tracker or ApplicationTracker()
    application = tracker.get_application(application_id)
    if not application:
        raise ApplicationWorkflowError(f"Application {application_id} does not exist.")
    ready, missing, eligibility, assessment = application_readiness(application, tracker)
    if not ready:
        raise ApplicationWorkflowError(
            "Approval is blocked: " + "; ".join(missing)
        )
    if eligibility["status"] != "confirmed_evening":
        raise ApplicationWorkflowError("Eligibility is not confirmed.")
    if not assessment.get("eligible") or assessment.get("mandatory_gaps"):
        raise ApplicationWorkflowError("Mandatory qualification requirements are not met.")
    if application.get("status") in {"Submitted", "Manually submitted"}:
        raise ApplicationWorkflowError("This application has already been submitted.")
    if application.get("status") in {"Approved", "Submission failed"}:
        raise ApplicationWorkflowError(
            "This application cannot be approved from its current status."
        )
    try:
        return tracker.update_application(
            application_id,
            {
                "status": "Approved",
                "approved_at": datetime.now().isoformat(),
                "submission_state": "APPROVED",
            },
            event_type="approved_by_candidate",
            expected_status=application.get("status"),
        )
    except ValueError as error:
        raise ApplicationWorkflowError(str(error)) from error


def mark_manually_submitted(
    application_id,
    submitted_on=None,
    confirmation_ref="",
    follow_up_date=None,
    tracker=None,
):
    tracker = tracker or ApplicationTracker()
    application = tracker.get_application(application_id)
    if not application:
        raise ApplicationWorkflowError(f"Application {application_id} does not exist.")
    if application.get("status") == "Manually submitted":
        raise ApplicationWorkflowError("This application is already recorded as submitted.")
    if application.get("status") != "Approved":
        raise ApplicationWorkflowError("Approve this application before recording manual submission.")
    ready, missing, eligibility, assessment = application_readiness(application, tracker)
    if not ready:
        raise ApplicationWorkflowError(
            "Manual submission is blocked because readiness changed: "
            + "; ".join(missing)
        )
    if eligibility["status"] != "confirmed_evening":
        raise ApplicationWorkflowError("Eligibility is no longer confirmed.")
    if not assessment.get("eligible") or assessment.get("mandatory_gaps"):
        raise ApplicationWorkflowError("Mandatory qualification requirements are not met.")
    submitted_date = submitted_on or date.today().isoformat()
    try:
        datetime.fromisoformat(submitted_date)
    except (TypeError, ValueError) as error:
        raise ApplicationWorkflowError("Enter a valid submission date.") from error
    if follow_up_date:
        try:
            datetime.fromisoformat(follow_up_date)
        except (TypeError, ValueError) as error:
            raise ApplicationWorkflowError("Enter a valid follow-up date.") from error
    try:
        return tracker.update_application(
            application_id,
            {
                "status": "Manually submitted",
                "submission_state": "MANUALLY_SUBMITTED",
                "submission_method": "manual",
                "confirmation_ref": confirmation_ref or "",
                "submitted_at": submitted_date,
                "applied_at": submitted_date,
                "follow_up_date": follow_up_date or None,
            },
            event_type="manual_submission_recorded",
            details="Candidate reported submission through the employer application page.",
            expected_status="Approved",
        )
    except ValueError as error:
        raise ApplicationWorkflowError(str(error)) from error


def mark_submission_failed(application_id, details="", tracker=None):
    tracker = tracker or ApplicationTracker()
    application = tracker.get_application(application_id)
    if not application:
        raise ApplicationWorkflowError(f"Application {application_id} does not exist.")
    if application.get("status") != "Approved":
        raise ApplicationWorkflowError("Only an approved application can be marked as submission failed.")
    try:
        return tracker.update_application(
            application_id,
            {
                "status": "Submission failed",
                "submission_state": "FAILED",
                "submission_method": "manual",
            },
            event_type="manual_submission_failed",
            details=details or "Candidate reported that the employer page did not accept the application.",
            expected_status="Approved",
        )
    except ValueError as error:
        raise ApplicationWorkflowError(str(error)) from error


def retry_failed_submission(application_id, tracker=None):
    tracker = tracker or ApplicationTracker()
    application = tracker.get_application(application_id)
    if not application:
        raise ApplicationWorkflowError(f"Application {application_id} does not exist.")
    if application.get("status") != "Submission failed":
        raise ApplicationWorkflowError("Only a failed manual submission can be retried.")
    ready, missing, _, _ = application_readiness(application, tracker)
    if not ready:
        raise ApplicationWorkflowError(
            "Manual submission retry is blocked: " + "; ".join(missing)
        )
    try:
        return tracker.update_application(
            application_id,
            {"status": "Approved", "submission_state": "APPROVED"},
            event_type="manual_submission_retry_approved",
            details="Candidate returned to the employer page after a reported failure.",
            expected_status="Submission failed",
        )
    except ValueError as error:
        raise ApplicationWorkflowError(str(error)) from error


def submission_capability():
    return {
        "automated_submission_supported": False,
        "method": "manual",
        "reason": (
            "No authorized employer submission adapter or employer-issued credentials "
            "are configured. Greenhouse Harvest credentials are employer-controlled; "
            "Lever submission requires employer account credentials or authorized OAuth. "
            "LinkedIn Apply Connect is an ATS integration, not a general candidate API."
        ),
    }
