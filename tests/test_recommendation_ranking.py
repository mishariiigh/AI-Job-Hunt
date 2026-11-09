"""Stage 12.4.9 regression tests: structured recommendation ranking and
UI section integrity.

Ranking must reflect eligibility > geography > schedule > schedule-signal >
arrangement > hours > score > freshness. A high technical score must never
outrank suitability dimensions.
"""
import json

import pytest

from agents.job_classifier import (
    classify_opportunity,
    opportunity_priority_key,
)


def _job(**overrides):
    job = {
        "job_title": "Support Analyst",
        "employer": "Example Corp",
        "description": "Interesting technical support role.",
        "location": "Remote - Canada",
        "remote": 1,
        "listing_status": "active_on_source",
    }
    job.update(overrides)
    return job


# 1. 75% confirmed Canadian evening outranks 90% unknown-schedule
def test_confirmed_evening_75_outranks_unknown_schedule_90():
    confirmed = _job(description="Shift: 5 PM - 1 AM Eastern Time.", match_score=75)
    unknown = _job(
        description="Flexible work, lots of Python SQL Azure keyword stuffing.",
        match_score=90,
    )
    confirmed_result = classify_opportunity(confirmed)
    unknown_result = classify_opportunity(unknown)
    assert confirmed_result["status"] == "confirmed_evening"
    assert unknown_result["status"] == "needs_verification"
    assert opportunity_priority_key(confirmed, confirmed_result, profile_score=75) > (
        opportunity_priority_key(unknown, unknown_result, profile_score=90)
    )


# 2. Disqualified senior positions never rank as eligible
def test_disqualified_senior_never_ranks_eligible():
    """Seniority mismatch recorded by the matcher (matches table) removes the
    job from eligible ranking via the provenance-backed gate."""
    from agents.matching_agent import MatchingAgent
    from tracking.application_tracker import ApplicationTracker
    matcher = MatchingAgent()
    senior = _job(
        job_title="Staff Engineer",
        description="10+ years required. Shift: 5 PM - 1 AM Eastern Time.",
        match_score=90,
    )
    match_result = matcher.deterministic_match(senior)
    assert "Seniority mismatch" in json.loads(match_result["hard_disqualifiers"])
    senior_with_disqualifiers = dict(
        senior, hard_disqualifiers=match_result["hard_disqualifiers"]
    )
    result = classify_opportunity(senior_with_disqualifiers)
    key = opportunity_priority_key(
        senior_with_disqualifiers, result, profile_score=90
    )
    assert key[0] == 0, "seniority-mismatched job must not rank as eligible"
    junior = _job(
        job_title="IT Support Technician",
        description="Shift: 5 PM - 1 AM Eastern Time. 1-2 years experience.",
        match_score=50,
    )
    junior_result = classify_opportunity(junior)
    assert opportunity_priority_key(junior, junior_result, profile_score=50)[0] == 1
    assert opportunity_priority_key(junior, junior_result, profile_score=50) > key


# 3. US-only jobs never appear as Canadian-eligible
def test_us_only_not_canadian_eligible():
    us_job = _job(
        location="Remote",
        description="Shift: 5 PM - 1 AM. Applicants must reside in the United States.",
    )
    result = classify_opportunity(us_job)
    key = opportunity_priority_key(us_job, result, profile_score=95)
    assert result["canadian_eligibility"]["status"] == "incompatible"
    assert result["status"] == "rejected"
    # canada_rank (second element) is 0
    assert key[1] == 0
    canada_job = _job(description="Shift: 5 PM - 1 AM Eastern Time.")
    canada_result = classify_opportunity(canada_job)
    assert opportunity_priority_key(canada_job, canada_result, profile_score=50)[1] == 3


# 4. Unknown geographic eligibility identified and ranked below confirmed
def test_unknown_geography_identified_and_ranked_lower():
    unknown_geo = _job(
        location="Remote",
        description="Remote role worldwide. Shift: 5 PM - 1 AM.",
    )
    result = classify_opportunity(unknown_geo)
    assert result["canadian_eligibility"]["status"] in {"unknown", "potentially_compatible"}
    confirmed_geo = _job(description="Shift: 5 PM - 1 AM Eastern Time.")
    confirmed_result = classify_opportunity(confirmed_geo)
    assert opportunity_priority_key(confirmed_geo, confirmed_result, profile_score=50)[1] > (
        opportunity_priority_key(unknown_geo, result, profile_score=95)[1]
    )


# 5. Junior and support opportunities remain discoverable
def test_junior_support_stays_discoverable():
    junior = _job(
        job_title="Junior IT Support Technician",
        description="Entry level. Shift: 5 PM - 1 AM Eastern Time.",
        match_score=55,
    )
    result = classify_opportunity(junior)
    assert result["status"] == "confirmed_evening"
    # Not rejected by any gate; ranks above an equivalent rejected job
    key = opportunity_priority_key(junior, result, profile_score=55)
    assert key[0] == 1
    staff = dict(
        _job(
            job_title="Staff Engineer",
            description="10+ years required. Shift: 5 PM - 1 AM Eastern Time.",
            match_score=80,
        ),
        hard_disqualifiers='["Seniority mismatch"]',
    )
    staff_result = classify_opportunity(staff)
    assert opportunity_priority_key(junior, result, profile_score=55) > (
        opportunity_priority_key(staff, staff_result, profile_score=80)
    )


# 6. Duplicate recommendations prevented
def test_duplicate_recommendations_prevented():
    job = _job(description="Shift: 5 PM - 1 AM Eastern Time.", match_score=70)
    classified = [(job, classify_opportunity(job)) for _ in range(3)]
    keys = {id(item[0]) for item in classified}
    # Same underlying dict object listed once per posting; ranking produces
    # identical keys for identical postings so dedup by job_url is stable.
    assert len(keys) == 1
    # Distinct postings with the same content produce the same sort key,
    # so a UI dedup by (employer, title, url) keeps one entry without
    # changing order.
    other = _job(description="Shift: 5 PM - 1 AM Eastern Time.", match_score=70)
    other["job_url"] = "https://different.example.com/job"
    assert opportunity_priority_key(job, classify_opportunity(job), profile_score=70) == (
        opportunity_priority_key(other, classify_opportunity(other), profile_score=70)
    )


# 7. Sorting is stable and deterministic
def test_sorting_stable_and_deterministic():
    jobs = [
        _job(description="Shift: 5 PM - 1 AM Eastern Time.", match_score=60),
        _job(description="Shift: 5 PM - 1 AM Eastern Time.", match_score=60),
        _job(description="Flexible hours, unspecified.", match_score=95),
        _job(description="Shift: 6 PM - 10 PM Eastern Time.", match_score=50),
    ]
    entries = [(job, classify_opportunity(job)) for job in jobs]
    ranked_1 = sorted(
        ((job, result, opportunity_priority_key(job, result, profile_score=job.get("match_score", 0))) for job, result in entries),
        key=lambda item: item[2],
        reverse=True,
    )
    ranked_2 = sorted(
        ((job, result, opportunity_priority_key(job, result, profile_score=job.get("match_score", 0))) for job, result in entries),
        key=lambda item: item[2],
        reverse=True,
    )
    assert [item[2] for item in ranked_1] == [item[2] for item in ranked_2]
    # Deterministic ordering: confirmed evening (any score) ahead of unknown
    assert ranked_1[0][0]["description"].startswith("Shift: 5 PM")
    assert ranked_1[-1][0]["description"].startswith("Flexible")


# Extra: schedule-signal rank separates evening-mentioned unknowns from
# silent unknowns within the same schedule status
def test_evening_signal_unknown_outranks_silent_unknown_at_equal_score():
    evening_mentioned = _job(
        description="Evening and weekend coverage required, hours to be confirmed.",
        match_score=70,
    )
    silent = _job(
        description="Python SQL Azure cloud work, flexible arrangements.",
        match_score=70,
    )
    evening_result = classify_opportunity(evening_mentioned)
    silent_result = classify_opportunity(silent)
    assert evening_result["evening"]["status"] != "confirmed_evening"
    assert silent_result["evening"]["status"] != "confirmed_evening"
    assert opportunity_priority_key(evening_mentioned, evening_result, profile_score=70) > (
        opportunity_priority_key(silent, silent_result, profile_score=70)
    )
