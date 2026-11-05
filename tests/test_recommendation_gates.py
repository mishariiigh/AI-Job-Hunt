"""Stage 11 regression tests: strict recommendation gates and schedule rules.

Confirms that technical match scores never override hard gates and that
schedule classification follows the exact rules defined for Stage 11.
"""
import json
import pytest

from agents.job_classifier import (
    classify_evening_eligibility,
    classify_opportunity,
    opportunity_priority_key,
)
from agents.matching_agent import MatchingAgent


def _confirmed_evening_job(**overrides):
    job = {
        "job_title": "Support Analyst",
        "employer": "Example Corp",
        "description": "Evening shift 5 PM - 1 AM.",
        "location": "Remote - Canada",
        "remote": 1,
        "listing_status": "active_on_source",
        "timezone": "America/Toronto",
    }
    job.update(overrides)
    return job


def test_confirmed_5pm_to_1am_is_qualifying_evening():
    result = classify_evening_eligibility(
        _confirmed_evening_job(description="Shift: 5 PM to 1 AM.")
    )
    assert result["status"] == "confirmed_evening"
    assert result["start_time"] == "17:00"
    assert result["end_time"] == "01:00"
    assert result["timezone"] == "America/Toronto"


def test_confirmed_6pm_to_10pm_is_qualifying_evening():
    result = classify_evening_eligibility(
        _confirmed_evening_job(description="Hours: 6 PM - 10 PM, Monday to Friday.")
    )
    assert result["status"] == "confirmed_evening"
    assert result["start_time"] == "18:00"


def test_3pm_to_11pm_is_not_confirmed_evening():
    result = classify_evening_eligibility(
        _confirmed_evening_job(description="Shift hours: 3 PM - 11 PM.")
    )
    assert result["status"] == "incompatible"
    assert result["start_time"] == "15:00"


def test_daytime_only_job_is_not_suitable():
    result = classify_opportunity(
        _confirmed_evening_job(description="Day shift 9 AM - 5 PM.")
    )
    assert result["status"] == "rejected"
    assert result["evening"]["status"] == "incompatible"


def test_unknown_schedule_with_95_technical_match_is_not_confirmed():
    job = _confirmed_evening_job(
        description="Great flexible team. Work on Python, SQL, Azure, APIs.",
        match_score=95,
    )
    result = classify_opportunity(job)
    assert result["status"] == "needs_verification"
    assert result["evening"]["status"] in {"unknown", "needs_verification"}
    # The technical score must not change the category or outrank the gate.
    key = opportunity_priority_key(job, result, profile_score=95)
    confirmed_job = _confirmed_evening_job(
        description="Shift: 5 PM - 1 AM.", match_score=40
    )
    confirmed_result = classify_opportunity(confirmed_job)
    assert confirmed_result["status"] == "confirmed_evening"
    assert opportunity_priority_key(
        confirmed_job, confirmed_result, profile_score=40
    ) > key


def test_rotating_shift_with_daytime_possibilities_needs_verification():
    result = classify_evening_eligibility(
        _confirmed_evening_job(
            description="Rotating shift schedule between day and evening coverage."
        )
    )
    assert result["status"] in {"needs_verification", "unknown"}
    assert result["schedule_type"] == "rotating_shift"
    assert result["confirmed_evening"] is False


def test_on_call_does_not_establish_evening_schedule():
    result = classify_evening_eligibility(
        _confirmed_evening_job(
            description="Provide on-call support for evening escalations."
        )
    )
    assert result["status"] != "confirmed_evening"


def test_flexible_hours_do_not_establish_evening_schedule():
    result = classify_evening_eligibility(
        _confirmed_evening_job(
            description="Flexible hours; evening availability preferred."
        )
    )
    assert result["status"] != "confirmed_evening"


def test_conflicting_metadata_and_description_needs_verification():
    result = classify_evening_eligibility(
        _confirmed_evening_job(
            description="Monday to Friday, 5:00pm – 1:00am",
            shift="Day shift, Monday to Friday",
        )
    )
    assert result["status"] == "needs_verification"
    assert result["conflict"] is True
    assert any(
        item["source"] == "structured_metadata" for item in result["evidence_sources"]
    )


def test_remote_job_excluding_canadian_applicants_is_rejected():
    result = classify_opportunity(
        _confirmed_evening_job(
            description=(
                "Shift: 5 PM - 1 AM. Remote candidates must reside in "
                "the United States."
            ),
            location="Remote",
        )
    )
    assert result["status"] == "rejected"
    assert result["canadian_eligibility"]["status"] == "incompatible"


def test_mississauga_in_person_with_verified_gates_is_confirmed():
    result = classify_opportunity(
        _confirmed_evening_job(
            description="Shift: 5 PM - 1 AM, onsite.",
            location="Mississauga, Ontario",
            remote=0,
        )
    )
    assert result["status"] == "confirmed_evening"


def test_mandatory_french_is_rejected():
    result = classify_opportunity(
        _confirmed_evening_job(
            description="Shift: 5 PM - 1 AM. Bilingual French required."
        )
    )
    assert result["status"] == "rejected"
    assert any("French" in reason for reason in result["reasons"])


def test_missing_keywords_are_not_proof_of_missing_skills():
    matcher = MatchingAgent()
    job = {
        "job_title": "Platform Support",
        "description": "Support tooling built on Go, Rust, and Kafka.",
        "location": "Remote - Canada",
        "remote": 1,
    }
    result = matcher.deterministic_match(job)
    missing = json.loads(result["missing_qualifications"])
    assert any("verify against resume" in item for item in missing)
    assert not any("not evident" in item for item in missing)


def test_specialist_requirements_are_not_satisfied_by_general_sql():
    matcher = MatchingAgent()
    job = {
        "job_title": "Database Reliability Engineer",
        "description": (
            "3+ years of experience working with relational database systems. "
            "Hands-on experience with SQL Server or PostgreSQL administration, "
            "performance tuning, replication, high availability, and disaster "
            "recovery. Experience working in the cloud (AWS, GCP, or Azure). "
            "Experience with IaC tools such as Ansible and Terraform."
        ),
        "location": "Remote or Mississauga",
        "remote": 1,
        "listing_status": "active_on_source",
        "source": "greenhouse",
    }
    assessment = matcher.skills_assessment(job, matcher.profile, "")
    specialist = [
        item
        for item in assessment["requirement_assessments"]
        if item["requirement"]
        in {
            "database administration",
            "production reliability / SRE",
            "database replication / HA / DR",
            "query/schema performance tuning",
            "infrastructure-as-code (Ansible/Terraform)",
        }
    ]
    assert specialist, "specialist requirements should be detected"
    statuses = {item["requirement"]: item["evidence_status"] for item in specialist}
    # General SQL/programming knowledge must not mark these as Demonstrated
    # when no verified evidence exists.
    for requirement, status in statuses.items():
        assert status != "Demonstrated", f"{requirement} was inflated to Demonstrated"


def test_pointclickcare_dbre_regression_stays_out_of_confirmed_evening():
    matcher = MatchingAgent()
    job = {
        "id": 205,
        "job_title": "Int Database Reliability Engineer (DBRE)",
        "employer": "pointclickcare",
        "description": (
            "The Database Reliability Engineer (DBRE) is responsible for managing, "
            "building, maintaining, monitoring, and troubleshooting the cloud-based "
            "database infrastructure. Hands-on experience with SQL Server or "
            "PostgreSQL administration, performance tuning, replication, high "
            "availability, and disaster recovery. Flexible work arrangements."
        ),
        "location": "Remote or Mississauga",
        "remote": 1,
        "employment_type": "Full-Time",
        "source": "greenhouse",
        "listing_status": "active_on_source",
        "match_score": 64.29,
    }
    result = classify_opportunity(job)
    assert result["status"] == "needs_verification"
    assert result["evening"]["status"] != "confirmed_evening"
    assert result["evening"].get("schedule_type") in {
        "unknown",
        "flexible",
        "needs_verification",
    }
    # Technical score stays intact and separate
    assert float(job["match_score"]) == 64.29


def test_full_time_ranks_below_equivalent_part_time():
    part_time = _confirmed_evening_job(
        description="Shift: 5 PM - 1 AM. Part-time, 20-25 hours per week.",
        employment_type="Part-time",
    )
    full_time = _confirmed_evening_job(
        description="Shift: 5 PM - 1 AM. Full-time.",
        employment_type="Full-time",
    )
    matcher = MatchingAgent()
    part_result = matcher.deterministic_match(part_time)
    full_result = matcher.deterministic_match(full_time)
    assert part_result["match_score"] > full_result["match_score"]
    part_opp = classify_opportunity(part_time)
    full_opp = classify_opportunity(full_time)
    assert opportunity_priority_key(part_time, part_opp) > opportunity_priority_key(
        full_time, full_opp
    )


def test_genuine_mandatory_gap_is_confirmed_missing():
    matcher = MatchingAgent()
    profile = dict(matcher.profile)
    profile["confirmed_missing_qualifications"] = ["ED"]
    job = {
        "job_title": "EDI Analyst",
        "description": "EDI experience is required. SQL is required.",
        "location": "Remote - Canada",
        "remote": 1,
    }
    assessment = matcher.skills_assessment(job, profile, "")
    by_name = {
        item["requirement"]: item["evidence_status"]
        for item in assessment["requirement_assessments"]
    }
    assert by_name.get("EDI") == "Confirmed missing"
    assert assessment["missing_required"] == ["EDI"]


# --- Stage 11 correction: specialist evidence must be operational, not generic ---

def test_generic_sql_does_not_establish_database_administration():
    from agents.matching_agent import MatchingAgent as M
    profile = M().profile
    # Profile contains generic "SQL" as a technical interest
    status, _, _ = M._candidate_requirement_evidence(
        "database administration", profile, "Managed SQL queries and reports."
    )
    assert status == "Not evidenced"


def test_generic_database_experience_does_not_establish_replication_or_dr():
    from agents.matching_agent import MatchingAgent as M
    status, _, _ = M._candidate_requirement_evidence(
        "database replication / HA / DR",
        M().profile,
        "Worked with databases and data entry.",
    )
    assert status == "Not evidenced"


def test_generic_azure_familiarity_does_not_establish_cloud_infrastructure():
    from agents.matching_agent import MatchingAgent as M
    for resume in (
        "Familiar with Azure services.",
        "Used cloud storage for files.",
        "Experience with the AWS console.",
    ):
        status, _, _ = M._candidate_requirement_evidence(
            "cloud infrastructure experience", M().profile, resume
        )
        assert status != "Demonstrated", resume
        assert status != "Transferable", resume


def test_genuine_operational_experience_still_qualifies_as_transferable():
    from agents.matching_agent import MatchingAgent as M
    status, evidence, source = M._candidate_requirement_evidence(
        "database administration",
        M().profile,
        "Administered production SQL Server databases and performed backups.",
    )
    assert status == "Transferable"
    assert "Administered production SQL Server" in evidence
    status_sre, _, _ = M._candidate_requirement_evidence(
        "production reliability / SRE",
        M().profile,
        "Provided application support and incident troubleshooting.",
    )
    assert status_sre == "Transferable"


def test_transferable_is_never_represented_as_demonstrated():
    from agents.matching_agent import MatchingAgent as M
    matcher = M()
    job = {
        "job_title": "Database Reliability Engineer",
        "description": (
            "Database administration is required. Production reliability "
            "experience is required."
        ),
        "location": "Remote - Canada",
        "remote": 1,
    }
    assessment = matcher.skills_assessment(job, matcher.profile, "")
    for item in assessment["requirement_assessments"]:
        if item["requirement"] == "database administration":
            assert item["evidence_status"] != "Demonstrated"
        if item["requirement"] == "production reliability / SRE":
            assert item["evidence_status"] != "Demonstrated"


def test_toronto_in_person_with_unknown_schedule_stays_needs_verification():
    result = classify_opportunity({
        "job_title": "Support Analyst",
        "employer": "X",
        "description": "Great team, hybrid work environment.",
        "location": "Toronto, Ontario",
        "remote": 0,
        "listing_status": "active_on_source",
    })
    assert result["status"] == "needs_verification"
    assert result["evening"]["status"] == "unknown"
    # Location alone never confirms the schedule
    confirmed = classify_opportunity({
        "job_title": "Support Analyst",
        "employer": "X",
        "description": "Evening shift 5 PM - 1 AM.",
        "location": "Toronto, Ontario",
        "remote": 0,
        "listing_status": "active_on_source",
    })
    assert confirmed["status"] == "confirmed_evening"
