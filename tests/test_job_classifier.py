from datetime import datetime, timedelta, timezone

import pytest

from agents.job_classifier import (
    classify_evening_eligibility,
    classify_job,
    french_is_mandatory,
    opportunity_priority_key,
)

def test_classifier_basic():
    job = {'job_title': 'IT Support', 'description': 'Remote Canada evening part-time', 'location': 'Remote - Canada', 'remote': 1,
           'employment_type': 'Part-time', 'schedule_classification': {'confirmed_evening': True, 'part_time': True}}
    res = classify_job(job, {'technical_interests': ['Python'], 'experience_years': 4})
    assert res['canadian_eligibility']['status'] == 'confirmed_compatible'
    assert res['french_requirement']['status'] == 'confirmed_compatible'
    assert res['expiry_status']['status'] == 'confirmed_compatible'

def test_classifier_french():
    job = {'job_title': 'Support', 'description': 'Bilingual French required', 'location': 'Canada', 'remote': 1,
           'schedule_classification': {'schedule_type': 'unknown'}}
    res = classify_job(job, {})
    assert res['french_requirement']['status'] == 'incompatible'


def test_french_preference_or_explicitly_optional_language_is_not_mandatory():
    descriptions = (
        "French is not required.",
        "French preferred, not required.",
        "French is not mandatory.",
        "French proficiency is preferred and English is required.",
    )
    for description in descriptions:
        assert not french_is_mandatory({"description": description})


def test_french_required_wording_is_still_mandatory():
    descriptions = (
        "French is required.",
        "French fluency is mandatory.",
        "Bilingual French required.",
        "Must be fluent in French.",
    )
    for description in descriptions:
        assert french_is_mandatory({"description": description})


@pytest.mark.parametrize(
    ("description", "start", "end"),
    [
        ("5 PM–1 AM", "17:00", "01:00"),
        ("6:00 PM to 2:00 AM", "18:00", "02:00"),
        ("7 PM - 11 PM", "19:00", "23:00"),
        ("Monday-Friday, 5:00pm – 1:00am", "17:00", "01:00"),
    ],
)
def test_evening_hours_preserve_posting_url_and_exact_times(description, start, end):
    source_url = "https://careers.example.test/jobs/123"
    result = classify_evening_eligibility(
        {
            "description": description,
            "job_url": source_url,
            "timezone": "America/Toronto",
        }
    )

    assert result["status"] == "confirmed_evening"
    assert result["start_time"] == start
    assert result["end_time"] == end
    assert result["source_url"] == source_url
    assert result["evidence_sources"][0]["source_url"] == source_url


def test_remote_hours_without_a_toronto_timezone_are_not_confirmed():
    result = classify_evening_eligibility(
        {
            "description": "Remote Canada role, shift from 5 PM to 1 AM",
            "location": "Remote - Canada",
            "remote": True,
            "job_url": "https://careers.example.test/jobs/remote",
        }
    )

    assert result["status"] == "needs_verification"
    assert result["schedule_type"] == "timezone_unverified"
    assert result["timezone"] is None
    assert result["start_time"] == "17:00"
    assert "America/Toronto" in result["reason"]


def test_eastern_remote_hours_and_accepted_ontario_location_use_toronto_time():
    eastern_remote = classify_evening_eligibility(
        {
            "description": "Remote Canada role, shift from 5 PM to 1 AM Eastern Time",
            "location": "Remote - Canada",
            "remote": True,
        }
    )
    local_onsite = classify_evening_eligibility(
        {
            "description": "Shift from 5 PM to 1 AM",
            "location": "Oakville, Ontario",
            "remote": False,
        }
    )

    assert eastern_remote["status"] == "confirmed_evening"
    assert eastern_remote["timezone"] == "America/Toronto"
    assert local_onsite["status"] == "confirmed_evening"
    assert local_onsite["timezone"] == "America/Toronto"


def test_multiple_explicit_shift_ranges_preserve_options_and_require_review_if_mixed():
    result = classify_evening_eligibility(
        {
            "description": (
                "Choose from a 9 AM to 5 PM shift or a 5 PM to 1 AM shift."
            ),
            "location": "Oakville, Ontario",
            "remote": False,
            "job_url": "https://careers.example.test/jobs/multiple",
        }
    )

    assert result["status"] == "needs_verification"
    assert result["schedule_type"] == "multiple_shift_options"
    assert result["schedule_signals"]["multiple_shift_options"] is True
    assert [item["value"] for item in result["evidence_sources"][:2]] == [
        "9 AM to 5 PM",
        "5 PM to 1 AM",
    ]


def test_multiple_explicit_evening_ranges_can_confirm_without_rotation():
    result = classify_evening_eligibility(
        {
            "description": "Available shifts are 5 PM to 1 AM or 6 PM to 2 AM.",
            "location": "Oakville, Ontario",
            "remote": False,
        }
    )

    assert result["status"] == "confirmed_evening"
    assert result["schedule_signals"]["multiple_shift_options"] is True
    assert len(result["evidence_sources"]) == 3


def test_evening_labels_and_rotations_require_exact_hours_and_verification():
    cases = (
        "Evening shift",
        "Second shift",
        "Closing shift",
        "Night shift",
        "Weekend evening coverage",
        "Rotating shifts include evenings and weekends",
    )
    for description in cases:
        result = classify_evening_eligibility({"description": description})
        assert result["status"] != "confirmed_evening"
        assert result["needs_schedule_verification"] is True
        assert result["schedule_signals"]["evening_shift"] or result["schedule_signals"]["weekend_evening"]
        assert result["evidence_sources"]


def test_24_hour_on_call_and_global_coverage_are_context_not_shift_confirmation():
    for description, signal in (
        ("The service runs 24/7.", "continuous_operations"),
        ("The role participates in an on-call rotation.", "on_call"),
        ("Join a global coverage team across time zones.", "global_coverage"),
        ("Provide after-hours support as needed.", "after_hours_support"),
    ):
        result = classify_evening_eligibility({"description": description})
        assert result["status"] != "confirmed_evening"
        assert result["schedule_signals"][signal] is True
        assert result["needs_schedule_verification"] is True


def test_rotating_evening_hours_need_confirmation_of_consistent_assignment():
    result = classify_evening_eligibility(
        {
            "description": (
                "Participate in a rotating shift including evenings, "
                "with an evening shift from 6:00 PM to 2:00 AM."
            ),
            "job_url": "https://careers.example.test/jobs/rotating",
        }
    )
    assert result["status"] == "needs_verification"
    assert result["schedule_type"] == "rotating_shift"
    assert result["start_time"] == "18:00"
    assert result["source_url"] == "https://careers.example.test/jobs/rotating"


def test_verified_d2l_style_evening_rotation_is_potential_not_confirmed():
    result = classify_evening_eligibility(
        {
            "description": (
                "Participate in a shift rotation including weekdays, "
                "evenings, and weekends based on Eastern Time."
            ),
            "job_url": "https://www.d2l.com/careers/jobs/product-support-analyst/7696232/",
        }
    )
    assert result["status"] == "unknown"
    assert result["schedule_type"] == "rotating_shift"
    assert result["schedule_signals"]["rotating_shift"] is True
    assert result["schedule_signals"]["evening_shift"] is True
    assert result["schedule_signals"]["weekend_evening"] is True
    assert result["source_url"].startswith("https://www.d2l.com/")


def test_asl_description_and_day_shift_metadata_conflict_is_never_auto_confirmed():
    result = classify_evening_eligibility(
        {
            "description": "Monday to Friday, 5:00pm – 1:00am",
            "shift": "Day shift, Monday to Friday",
            "job_url": "https://ca.indeed.com/viewjob?jk=03fe2c1d035076a0",
        }
    )
    assert result["status"] == "needs_verification"
    assert result["conflict"] is True
    assert result["start_time"] == "17:00"
    assert result["end_time"] == "01:00"
    assert all(
        evidence["source_url"].startswith("https://")
        for evidence in result["evidence_sources"]
    )


def test_confirmed_schedule_ranks_above_high_score_unknown_schedule():
    confirmed = {
        "location": "Remote, Canada",
        "remote": True,
        "description": "Shift 5 PM to 10 PM",
        "timezone": "America/Toronto",
        "listing_status": "active_on_source",
        "match_score": 45,
    }
    unknown = {
        "location": "Remote, Canada",
        "remote": True,
        "description": "Flexible schedule",
        "listing_status": "active_on_source",
        "match_score": 99,
    }
    assert opportunity_priority_key(confirmed) > opportunity_priority_key(unknown)

from agents.job_classifier import canadian_eligibility

def test_priority_orders_canadian_eligibility_before_schedule_and_keeps_rejected_last():
    canadian_unknown_schedule = {
        "location": "Remote, Canada",
        "remote": True,
        "description": "Flexible schedule",
        "listing_status": "active_on_source",
        "match_score": 50,
    }
    unknown_canada_confirmed_schedule = {
        "location": "Remote",
        "remote": True,
        "description": "5 PM to 10 PM Eastern Time",
        "listing_status": "active_on_source",
        "match_score": 99,
    }
    rejected = {
        "location": "Remote, USA",
        "remote": True,
        "description": "5 PM to 10 PM Eastern Time",
        "listing_status": "active_on_source",
    }

    assert opportunity_priority_key(canadian_unknown_schedule) > (
        opportunity_priority_key(unknown_canada_confirmed_schedule)
    )
    assert opportunity_priority_key(canadian_unknown_schedule) > opportunity_priority_key(rejected)


def test_freshness_priority_parses_unix_millisecond_posting_dates():
    now = datetime.now(timezone.utc)
    base = {
        "location": "Oakville, Ontario",
        "remote": False,
        "description": "Shift from 5 PM to 10 PM",
        "listing_status": "active_on_source",
        "match_score": 50,
    }
    recent = {
        **base,
        "posting_date": str(int(now.timestamp() * 1000)),
    }
    stale = {
        **base,
        "posting_date": str(int((now - timedelta(days=300)).timestamp() * 1000)),
    }

    assert opportunity_priority_key(recent) > opportunity_priority_key(stale)


def test_ce_canada():
    assert canadian_eligibility({'location':'Remote - Canada','description':'Remote within Canada'})['status']=='confirmed_compatible'

def test_ce_us_only():
    assert canadian_eligibility({'location':'Remote - USA','description':'US only'})['status']=='incompatible'

def test_ce_worldwide():
    assert canadian_eligibility({'location':'Remote','description':'Remote worldwide'})['status']=='potentially_compatible'

def test_ce_north_america():
    assert canadian_eligibility({'location':'Remote','description':'Remote within North America'})['status']=='potentially_compatible'

def test_ce_unknown():
    assert canadian_eligibility({'location':'','description':''})['status']=='unknown'

from agents.job_classifier import schedule_evidence

def test_sched_evening():
    assert schedule_evidence({
        'description':'Evening shift after 6 PM',
        'timezone': 'America/Toronto',
    })['evening']['status']=='confirmed_compatible'

def test_sched_flexible():
    assert schedule_evidence({'description':'Flexible hours'})['evening']['status']=='potentially_compatible'

def test_sched_weekend():
    assert schedule_evidence({'description':'Weekend availability'})['weekend']['status']=='confirmed_compatible'

def test_sched_missing():
    assert schedule_evidence({'description':'Software developer'})['evening']['status'] in ('unknown','potentially_compatible')

def test_sched_fulltime():
    se = schedule_evidence({'description':'Full-time software developer'})
    assert se['evening']['status'] in ('unknown','potentially_compatible')

from agents.job_classifier import classify_evening_eligibility, classify_opportunity

def test_ee_5pm():
    assert classify_evening_eligibility({
        'description':'5 PM - 10 PM',
        'timezone': 'America/Toronto',
    })['status']=='confirmed_evening'

def test_ee_6pm():
    assert classify_evening_eligibility({
        'description':'6 PM - 11 PM',
        'timezone': 'America/Toronto',
    })['status']=='confirmed_evening'

def test_ee_4pm():
    assert classify_evening_eligibility({
        'description':'4 PM - 10 PM',
        'timezone': 'America/Toronto',
    })['status']=='incompatible'

def test_ee_day():
    assert classify_evening_eligibility({
        'description':'9 AM - 5 PM',
        'timezone': 'America/Toronto',
    })['status']=='incompatible'

def test_ee_unknown_flex():
    assert classify_evening_eligibility({'description':'Flexible hours'})['status']=='unknown'

def test_ee_unknown_247():
    assert classify_evening_eligibility({'description':'24/7 operations'})['status']=='unknown'

def test_ee_evening_shift_word():
    assert classify_evening_eligibility({'description':'Evening shift'})['status']=='unknown'

def test_ee_second_shift():
    assert classify_evening_eligibility({'description':'Second shift position'})['status']=='unknown'

def test_ee_24h():
    assert classify_evening_eligibility({
        'description':'17:00-22:00',
        'timezone': 'America/Toronto',
    })['status']=='confirmed_evening'

def test_conflicting_description_hours_and_structured_day_shift_need_verification():
    result = classify_evening_eligibility({
        "description": "Shift: 5:00 PM - 1:00 AM",
        "shift": "Day shift",
        "job_url": "https://jobs.example.test/1",
    })
    assert result["status"] == "needs_verification"
    assert result["conflict"] is True
    assert result["evidence_sources"][0] == {
        "source": "job_description",
        "value": "5:00 PM - 1:00 AM",
        "classification": "evening",
        "source_url": "https://jobs.example.test/1",
        "start_time": "17:00",
        "end_time": "01:00",
        "timezone_basis": "not stated",
    }
    assert result["evidence_sources"][1] == {
        "source": "structured_metadata",
        "value": "Day shift",
        "classification": "day",
        "source_url": "https://jobs.example.test/1",
    }
    opportunity = classify_opportunity(
        {
            "location": "Oakville, Ontario",
            "description": "Shift: 5:00 PM - 1:00 AM",
            "shift": "Day shift",
            "remote": 0,
        }
    )
    assert opportunity["status"] == "needs_verification"
    assert any("conflict" in reason.lower() for reason in opportunity["reasons"])


def test_explicit_evening_hours_without_conflicting_metadata_remain_confirmed():
    result = classify_evening_eligibility({
        "description": "Shift: 5:00 PM - 1:00 AM",
        "shift": "Evening shift",
        "timezone": "America/Toronto",
    })
    assert result["status"] == "confirmed_evening"
    assert result["conflict"] is False


def test_missing_hours_and_misleading_shift_label_are_not_confirmed():
    assert classify_evening_eligibility({
        "description": "IT support role",
        "shift": "Evening shift",
    })["status"] == "unknown"
    assert classify_evening_eligibility({
        "description": "IT support role",
        "shift": "Day shift",
    })["status"] == "unknown"


def test_structured_hours_conflicting_with_description_hours_need_verification():
    result = classify_evening_eligibility({
        "description": "Shift: 5:00 PM - 1:00 AM",
        "shift": "9:00 AM - 5:00 PM",
    })
    assert result["status"] == "needs_verification"
    assert result["conflict"] is True

def test_ee_explicit_start_without_end():
    result = classify_evening_eligibility({
        'description':'The shift starts at 5:30 PM',
        'timezone': 'America/Toronto',
    })
    assert result['status'] == 'confirmed_evening'
    assert result['start_time'] == '17:30'

def test_ee_invalid_explicit_start_is_not_confirmed():
    assert classify_evening_eligibility({'description':'The shift starts at 25:00'})['status']=='unknown'

def test_ce_canada_mention_without_residency_is_not_confirmed():
    result = canadian_eligibility({'location':'Remote','description':'Our teams work with customers in Canada'})
    assert result['status'] == 'potentially_compatible'

def test_ce_us_job_does_not_pass_on_canada_mention():
    result = canadian_eligibility({'location':'Remote, USA','description':'We also have customers in Canada'})
    assert result['status'] == 'incompatible'

def test_ce_remote_us_location_code_is_not_canadian():
    result = canadian_eligibility({'location':'Remote - US','description':'We also have customers in Canada'})
    assert result['status'] == 'incompatible'

def test_ce_us_residency_restriction_is_incompatible():
    result = canadian_eligibility({'location':'Remote','description':'Only US residents may apply'})
    assert result['status'] == 'incompatible'

def test_ce_explicit_remote_canada_location():
    result = canadian_eligibility({'location':'Remote, Canada','remote':1})
    assert result['status'] == 'confirmed_compatible'

def test_opportunity_unknown_shift_needs_verification():
    result = classify_opportunity({
        'location':'Remote, Canada',
        'remote':1,
        'description':'Software support specialist',
        'shift':'unknown',
    })
    assert result['status'] == 'needs_verification'
    assert any('shift' in reason for reason in result['reasons'])

def test_opportunity_remote_canada_with_exact_evening_start_is_confirmed():
    result = classify_opportunity({
        'location':'Remote, Canada',
        'remote':1,
        'description':'Support specialist. Shift: 5 PM - 10 PM.',
        'timezone': 'America/Toronto',
        'listing_status':'active_on_source',
    })
    assert result['status'] == 'confirmed_evening'

def test_opportunity_rejects_nonlocal_in_person_job():
    result = classify_opportunity({
        'location':'Ottawa, Ontario',
        'remote':0,
        'description':'Shift: 5 PM - 10 PM.',
    })
    assert result['status'] == 'rejected'
    # Toronto is inside the acceptable geographic area
    toronto = classify_opportunity({
        'location':'Toronto, Ontario',
        'remote':0,
        'description':'Shift: 5 PM - 10 PM.',
        'listing_status': 'active_on_source',
    })
    assert toronto['status'] == 'confirmed_evening'


def test_schedule_categories_keep_nights_rotations_flexibility_and_day_labels_distinct():
    overnight = classify_evening_eligibility({
        "description": "Overnight support shift, 10 PM to 6 AM",
        "timezone": "America/Toronto",
    })
    rotating = classify_evening_eligibility({
        "description": "Rotating shifts across the operations team"
    })
    flexible = classify_evening_eligibility({
        "description": "Flexible schedule"
    })
    day = classify_evening_eligibility({
        "description": "IT support role",
        "shift": "Day shift",
    })
    unknown_247 = classify_evening_eligibility({
        "description": "The center operates 24/7"
    })

    assert overnight["status"] == "confirmed_evening"
    assert overnight["schedule_type"] == "confirmed_overnight"
    assert rotating["schedule_type"] == "rotating_shift"
    assert rotating["status"] == "unknown"
    assert flexible["schedule_type"] == "flexible"
    assert flexible["status"] == "unknown"
    assert day["schedule_type"] == "day_shift"
    assert day["status"] == "unknown"
    assert unknown_247["schedule_type"] == "unknown"
    assert unknown_247["status"] == "unknown"


def test_canadian_cities_are_recognized_but_unapproved_in_person_city_is_rejected():
    assert canadian_eligibility({"location": "Toronto"})["status"] == "confirmed_compatible"
    result = classify_opportunity({
        "location": "Ottawa, Ontario",
        "remote": 0,
        "description": "Shift 5 PM - 10 PM",
        "listing_status": "active_on_source",
    })
    assert result["status"] == "rejected"
    assert any(
        "outside Oakville, Mississauga, and Toronto" in reason
        for reason in result["reasons"]
    )


def test_freshness_and_missing_source_status_block_current_match_claims():
    job = {
        "location": "Remote, Canada",
        "remote": 1,
        "description": "Support specialist. Shift: 5 PM - 10 PM.",
        "source": "greenhouse",
        "job_url": "https://jobs.example.test/1",
    }
    assert classify_opportunity(job)["status"] == "needs_verification"
    assert classify_opportunity({
        **job,
        "listing_status": "not_listed_on_source",
    })["status"] == "rejected"


def test_french_mandatory_wording_blocks_opportunity():
    result = classify_opportunity({
        "location": "Remote, Canada",
        "remote": True,
        "description": "French language skills are required.",
        "listing_status": "active_on_source",
    })
    assert result["status"] == "rejected"
    assert "French is a mandatory requirement" in result["reasons"]


def test_remotive_listing_requires_employer_verification_even_with_explicit_evening_hours():
    result = classify_opportunity({
        "location": "Canada",
        "remote": True,
        "description": "Support role with an explicit 5 PM to 11 PM shift.",
        "source": "remotive",
        "job_url": "https://remotive.com/remote-jobs/sample",
        "listing_status": "active_on_source_delayed",
    })
    assert result["status"] == "needs_verification"
    assert any("24 hours" in reason for reason in result["reasons"])


def test_opportunity_labels_separate_confirmed_potential_conflict_and_rejected():
    from agents.job_classifier import opportunity_status_label

    assert opportunity_status_label({
        "status": "confirmed_evening",
        "evening": {"conflict": False},
    }) == "Confirmed Evening"
    assert opportunity_status_label({
        "status": "needs_verification",
        "evening": {"conflict": False},
    }) == "Potential Evening"
    assert opportunity_status_label({
        "status": "needs_verification",
        "evening": {"conflict": True},
    }) == "Schedule Conflict"
    assert opportunity_status_label({
        "status": "rejected",
        "evening": {"conflict": False},
    }) == "Not Suitable"
