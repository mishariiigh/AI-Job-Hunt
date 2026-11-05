
import json
import re
from datetime import datetime, time
from sources.date_utils import normalize_source_timestamp


_CANADA_RESIDENCY_PATTERNS = (
    r"remote\s+(?:within|in)\s+canada",
    r"canada[- ]wide",
    r"canada\s+only",
    r"must\s+(?:reside|be based)\s+in\s+canada",
    r"(?:canadian\s+residents?|residents?\s+of\s+canada)",
    r"(?:eligible|authorized)\s+to\s+work\s+in\s+canada",
    r"open\s+to\s+applicants?\s+(?:residing|based)\s+in\s+canada",
)

_US_ONLY_PATTERNS = (
    r"\bus\s*[- ]only\b",
    r"\bunited states only\b",
    r"\bremote within the united states\b",
    r"\bremote within the us\b",
    r"\bmust\s+(?:reside|be based)\s+in\s+(?:the\s+)?(?:us|united states)\b",
    r"\bonly\s+(?:us|united states)\s+residents?\b",
    r"\b(?:us|united states)\s+residents?\s+only\b",
)

_FRENCH_MANDATORY_PATTERNS = (
    r"\b(?:french|français)(?:\s+(?:language|fluency|proficiency|skills?)){0,2}\s+"
    r"(?:(?:is|are)\s+)?(?:required|mandatory|essential|necessary|needed|a requirement)\b",
    r"\b(?:required|mandatory|essential|necessary|needed)\s+"
    r"(?:french|français)(?:\s+(?:language|fluency|proficiency|skills?)){0,2}\b",
    r"\b(?:fluency|proficiency|command|knowledge|ability)\s+(?:in|of)\s+"
    r"(?:french|français)\b.{0,24}\b(?:required|mandatory|essential|necessary|needed)\b",
    r"\b(?:must|need to|needs to|have to)\s+(?:be\s+)?(?:fluent|bilingual)\s+"
    r"(?:in\s+)?(?:french|français)\b",
    r"\bbilingual\s+(?:in\s+)?(?:french|français)\b.{0,20}\b(?:required|mandatory)\b",
)

_FRENCH_NOT_REQUIRED_PATTERNS = (
    r"\bnot\s+(?:a\s+)?(?:required|mandatory|requirement|essential|necessary|needed)\b",
    r"\bnot\s+(?:be\s+)?(?:fluent|bilingual)\b",
)


def _text(value):
    return str(value or "").lower()


def _is_remote(job):
    return job.get("remote") in (1, True, "1", "true", "yes", "remote")


def french_is_mandatory(job):
    text = f"{_text(job.get('job_title'))} {_text(job.get('description'))}"
    for sentence in re.split(r"[\n.!?;]+", text):
        if not re.search(r"\b(?:french|français)\b", sentence):
            continue
        if any(re.search(pattern, sentence) for pattern in _FRENCH_NOT_REQUIRED_PATTERNS):
            continue
        if any(re.search(pattern, sentence) for pattern in _FRENCH_MANDATORY_PATTERNS):
            return True
    return False


def schedule_evidence(job):
    text = f"{job.get('description', '')} {job.get('employment_type', '')}".lower()
    classified = classify_evening_eligibility(job)
    evidence = classified.get("evidence", [])
    if classified["status"] == "confirmed_evening":
        evening_status = "confirmed_compatible"
        evening_reason = classified["reason"]
        confidence = "high"
    elif classified["status"] == "incompatible":
        evening_status = "incompatible"
        evening_reason = classified["reason"]
        confidence = "high"
    elif classified.get("conflict"):
        evening_status = "unknown"
        evening_reason = classified["reason"]
        confidence = "low"
    elif "flexible" in text:
        evening_status = "potentially_compatible"
        evening_reason = "flexible schedule, not confirmed evening"
        confidence = "medium"
    else:
        evening_status = "unknown"
        evening_reason = classified["reason"]
        confidence = "low"

    weekend_status = "unknown"
    weekend_reason = "no schedule evidence"
    if re.search(r"\b(?:weekends?|saturdays?|sundays?)\b", text):
        weekend_status = "confirmed_compatible"
        weekend_reason = "explicit weekend evidence"
        evidence = [*evidence, "weekend"]
    return {
        "evening": {
            "status": evening_status,
            "reason": evening_reason,
            "schedule_type": classified.get("schedule_type", "unknown"),
            "schedule_label": classified.get("schedule_label"),
            "evidence": evidence,
            "evidence_sources": classified.get("evidence_sources", []),
            "conflict": classified.get("conflict", False),
            "confidence": confidence,
        },
        "weekend": {"status": weekend_status, "reason": weekend_reason, "evidence": evidence, "confidence": confidence},
    }

def canadian_eligibility(job):
    loc = _text(job.get("location"))
    desc = _text(job.get("description"))
    country = _text(job.get("country")).upper()
    canada_location = bool(
        re.search(r"\bcanada\b|\bcanadian\b", loc)
        or re.search(r"\b(?:oakville|mississauga|toronto|ottawa|montreal|vancouver|calgary|edmonton|winnipeg|halifax)\b", loc)
        or re.search(r",\s*(?:on|ontario|bc|ab|qc|mb|sk|ns|nb|nl|pe)\b", loc)
    )
    explicit_canada = any(re.search(pattern, desc) for pattern in _CANADA_RESIDENCY_PATTERNS)
    us_only = any(re.search(pattern, f"{loc} {desc}") for pattern in _US_ONLY_PATTERNS)

    if us_only:
        return {
            "status": "incompatible",
            "evidence": ["explicit US-only restriction"],
            "reason": "Applicants residing in Canada are excluded",
            "confidence": "high",
        }
    if country == "CA":
        return {
            "status": "confirmed_compatible",
            "evidence": ["country=CA"],
            "reason": "Posting country is Canada",
            "confidence": "high",
        }
    if explicit_canada:
        return {
            "status": "confirmed_compatible",
            "evidence": ["explicit Canadian residency/work eligibility"],
            "reason": "Posting explicitly accepts applicants in Canada",
            "confidence": "high",
        }
    if canada_location:
        return {
            "status": "confirmed_compatible",
            "evidence": ["Canadian location"],
            "reason": "Posting location is in Canada",
            "confidence": "high",
        }
    if country == "US" or re.search(r"\b(?:us|usa|united states)\b", loc):
        return {
            "status": "incompatible",
            "evidence": ["US posting location"],
            "reason": "Posting is restricted to the United States or has no Canadian eligibility evidence",
            "confidence": "high",
        }
    if re.search(r"\bremote within north america\b", desc):
        return {
            "status": "potentially_compatible",
            "evidence": ["North America"],
            "reason": "North America is listed, but Canadian eligibility is not explicit",
            "confidence": "medium",
        }
    if "remote worldwide" in desc or "anywhere in the world" in desc:
        return {
            "status": "potentially_compatible",
            "evidence": ["worldwide remote"],
            "reason": "Worldwide remote is stated, but confirm Canadian eligibility",
            "confidence": "medium",
        }
    if "canada" in desc or "canadian" in desc:
        return {
            "status": "potentially_compatible",
            "evidence": ["Canada mentioned without residency eligibility"],
            "reason": "Canada is mentioned, but applicant eligibility is not explicit",
            "confidence": "low",
        }
    return {
        "status": "unknown",
        "evidence": [],
        "reason": "Canadian applicant eligibility is not stated",
        "confidence": "low",
    }

def _cls(value):
    return value if value in ("confirmed_compatible", "potentially_compatible", "incompatible", "unknown") else "unknown"


def classify_job(job, profile=None):
    from agents.discovery_agent import DiscoveryAgent

    d = DiscoveryAgent()
    profile = profile or {}
    text = f"{job.get('job_title','')} {job.get('description','')}".lower()
    location = (job.get('location') or '').lower()

    ce = canadian_eligibility(job)
    canadian = ce["status"]

    work_arrangement = "confirmed_compatible" if job.get('remote') else ("potentially_compatible" if 'hybrid' in location else "unknown")

    geo = "confirmed_compatible" if any(c in location for c in ['oakville','mississauga','toronto']) else ("unknown" if not location else "potentially_compatible")

    schedule = job.get('schedule_classification') or {}
    if isinstance(schedule, str):
        try:
            import json
            schedule = json.loads(schedule)
        except Exception:
            schedule = {}
    se = schedule_evidence(job)
    evening = se["evening"]["status"]
    weekend = se["weekend"]["status"]

    emp_type = job.get('employment_type') or 'unknown'
    hours = "potentially_compatible" if emp_type else "unknown"
    if emp_type.lower() in ("part-time", "part time", "contract"):
        hours = "confirmed_compatible"

    french = "incompatible" if french_is_mandatory(job) else "confirmed_compatible"

    tech = "confirmed_compatible" if any(s.lower() in text for s in profile.get('technical_interests', [])) else "unknown"

    qual = "potentially_compatible"
    if profile.get('experience_years', 0) >= 4:
        qual = "confirmed_compatible"

    expired = "incompatible" if d.is_expired(job) else "confirmed_compatible"

    return {
        "canadian_eligibility": {"status": canadian, "reason": ce["reason"], "evidence": ce["evidence"], "confidence": ce["confidence"]},
        "work_arrangement": {"status": work_arrangement, "reason": "remote/hybrid/onsite"},
        "geographic_suitability": {"status": geo, "reason": "location evidence"},
        "evening_compatibility": {"status": evening, "reason": se["evening"]["reason"], "evidence": se["evening"]["evidence"], "confidence": se["evening"]["confidence"]},
        "weekend_compatibility": {"status": weekend, "reason": se["weekend"]["reason"], "evidence": se["weekend"]["evidence"], "confidence": se["weekend"]["confidence"]},
        "employment_type_hours": {"status": hours, "reason": "employment type"},
        "french_requirement": {"status": french, "reason": "french requirement"},
        "technical_relevance": {"status": tech, "reason": "skill keywords"},
        "candidate_qualification_match": {"status": qual, "reason": "profile comparison"},
        "expiry_status": {"status": expired, "reason": "deadline"},
    }


try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

def _parse_time(s):
    s = s.lower().replace(" ", "")
    m = re.fullmatch(r'(\d{1,2})(?::(\d{2}))?(am|pm)', s)
    if not m:
        return None
    h = int(m.group(1))
    mm = int(m.group(2)) if m.group(2) else 0
    if not 1 <= h <= 12 or not 0 <= mm <= 59:
        return None
    ap = m.group(3)
    if ap == 'pm' and h != 12:
        h += 12
    if ap == 'am' and h == 12:
        h = 0
    return time(h, mm)

def _extract_shift_hours(text):
    time_pattern = r"\d{1,2}(?::\d{2})?\s*(?:am|pm)"
    separator = r"(?:-|–|—|\bto\b)"
    options = _extract_shift_hour_options(text)
    if options:
        return options[0]
    after_match = re.search(
        r"\b(?:after|from)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm))\b",
        text,
        re.I,
    )
    if after_match:
        start = _parse_time(after_match.group(1))
        if start is not None:
            return start, None, after_match.group(0)
    start_match = re.search(
        r"\b(?:shift\s+)?(?:starts?|begins?|starting|beginning)\s+(?:at\s+)?"
        r"(\d{1,2}(?::\d{2})?\s*(?:am|pm)|\d{1,2}:\d{2})\b",
        text,
        re.I,
    )
    if start_match:
        raw_start = start_match.group(1)
        if re.search(r"(?:am|pm)", raw_start, re.I):
            start = _parse_time(raw_start)
        else:
            try:
                hour, minute = (int(value) for value in raw_start.split(":"))
                start = time(hour, minute)
            except ValueError:
                start = None
        if start is not None:
            return start, None, start_match.group(0)
    return None


def _extract_shift_hour_options(text):
    time_pattern = r"\d{1,2}(?::\d{2})?\s*(?:am|pm)"
    separator = r"(?:-|–|—|\bto\b)"
    patterns = (
        re.compile(
            r"(?<!\d)(\d{1,2}:\d{2})\s*"
            + separator
            + r"\s*(\d{1,2}:\d{2})(?!\d)",
            re.I,
        ),
        re.compile(
            r"(" + time_pattern + r")\s*" + separator + r"\s*(" + time_pattern + r")",
            re.I,
        ),
    )
    matches = []
    for pattern in patterns:
        for match in pattern.finditer(text):
            try:
                if ":" in match.group(1) and not re.search(r"(?:am|pm)", match.group(1), re.I):
                    start_hour, start_minute = (int(value) for value in match.group(1).split(":"))
                    end_hour, end_minute = (int(value) for value in match.group(2).split(":"))
                    start = time(start_hour, start_minute)
                    end = time(end_hour, end_minute)
                else:
                    start = _parse_time(match.group(1))
                    end = _parse_time(match.group(2))
            except ValueError:
                continue
            if start is not None and end is not None:
                matches.append((match.start(), (start, end, match.group(0))))
    return [value for _, value in sorted(matches, key=lambda item: item[0])]


def _metadata_schedule_text(job):
    values = []
    shift = str(job.get("shift") or "").strip()
    if shift and shift.lower() not in {"unknown", "none", "n/a"}:
        values.append(shift)
    classification = job.get("schedule_classification") or {}
    if isinstance(classification, str):
        try:
            import json
            classification = json.loads(classification)
        except (TypeError, ValueError):
            values.append(classification)
            classification = {}
    if isinstance(classification, dict):
        for key in ("schedule_type", "shift", "label", "schedule", "shift_type"):
            if classification.get(key):
                values.append(str(classification[key]))
    return " ".join(
        value for value in values
        if value.strip() and value.strip().lower() not in {"unknown", "none", "n/a"}
    ).strip()


def _schedule_timezone(job, text):
    declared_timezone = str(
        job.get("timezone") or job.get("time_zone") or ""
    ).strip()
    timezone_text = declared_timezone or str(text or "")
    if re.search(
        r"\b(?:America/Toronto|Eastern(?: Standard| Daylight)? Time|"
        r"ET|EST|EDT)\b",
        timezone_text,
        re.I,
    ):
        return "America/Toronto", declared_timezone or "Eastern Time"

    other_timezone = re.search(
        r"\b(?:Pacific|Mountain|Central|Atlantic|Newfoundland)"
        r"(?: Standard| Daylight)? Time\b|\b(?:PST|PDT|MST|MDT|CST|CDT|"
        r"AST|ADT|NST|NDT|UTC|GMT)\b|"
        r"\bAmerica/(?!Toronto\b)[A-Za-z_]+(?:/[A-Za-z_]+)?\b",
        timezone_text,
        re.I,
    )
    if other_timezone:
        return None, other_timezone.group(0)
    if declared_timezone:
        return None, declared_timezone

    location = str(job.get("location") or "")
    local_work_location = bool(
        re.search(r"\b(?:Oakville|Mississauga|Toronto)\b", location, re.I)
    )
    is_remote = _is_remote(job) or "remote" in location.lower()
    if local_work_location and not is_remote:
        return "America/Toronto", "local Ontario work location"
    return None, ""


def _schedule_label(text):
    if re.search(
        r"\b(?:day|days|morning|first|1st)\s+shift\b",
        text,
        re.I,
    ) or re.fullmatch(r"\s*(?:day|morning|first|1st)\s*", text, re.I):
        return "day"
    if re.search(
        r"\b(?:evening|second|2nd|closing|night|overnight)\s+shift\b|\bovernight\b",
        text,
        re.I,
    ) or re.fullmatch(r"\s*(?:evening|second|2nd|closing|night|overnight)\s*", text, re.I):
        return "evening"
    return None


def _schedule_signals(text):
    normalized = str(text or "")
    lower = normalized.lower()
    patterns = {
        "evening_shift": r"\b(?:evening|second|2nd|closing|night|overnight)\s+shift\b|\bovernight\b|\bevenings?\b",
        "weekend_evening": r"\bweekend(?:s)?\b.{0,50}\b(?:evenings?|nights?|second|closing)\b|\b(?:evenings?|nights?|second|closing)\b.{0,50}\bweekend(?:s)?\b",
        "rotating_shift": r"\b(?:rotating|rotational|rotation)\s+shifts?\b|\bshift\s+rotation\b",
        "after_hours_support": r"\bafter[- ]hours?\b",
        "on_call": r"\bon[- ]call\b",
        "continuous_operations": r"\b24\s*/\s*7\b|\b24[- ]hour(?:s)?\b|\bround[- ]the[- ]clock\b",
        "global_coverage": r"\bglobal\s+(?:support|coverage|team|operations)\b|\bacross\s+(?:multiple\s+)?time zones\b",
        "multiple_shift_options": r"\bmultiple\s+shift\s+options\b|\bshift options\b|\bvarious shifts\b",
    }
    return {
        name: bool(re.search(pattern, lower, re.I))
        for name, pattern in patterns.items()
    }


def classify_evening_eligibility(job, schedule_resolution=None):
    description = str(job.get("description") or "")
    metadata = _metadata_schedule_text(job)
    combined_text = f"{description} {metadata}"
    signals = _schedule_signals(combined_text)
    source_url = str(job.get("job_url") or "")
    description_hour_options = _extract_shift_hour_options(description)
    metadata_hour_options = _extract_shift_hour_options(metadata)
    if not description_hour_options:
        first_description_hours = _extract_shift_hours(description)
        if first_description_hours:
            description_hour_options = [first_description_hours]
    if not metadata_hour_options:
        first_metadata_hours = _extract_shift_hours(metadata)
        if first_metadata_hours:
            metadata_hour_options = [first_metadata_hours]
    description_hours = description_hour_options[0] if description_hour_options else None
    metadata_hours = metadata_hour_options[0] if metadata_hour_options else None
    hour_options = description_hour_options or metadata_hour_options
    label = _schedule_label(metadata)
    timezone, timezone_evidence = _schedule_timezone(job, combined_text)
    timezone_is_toronto = timezone == "America/Toronto"
    if len(description_hour_options) > 1 or len(metadata_hour_options) > 1:
        signals["multiple_shift_options"] = True
    evidence_sources = []
    for option in description_hour_options:
        evidence_sources.append({
            "source": "job_description",
            "value": option[2],
            "classification": "evening" if option[0].hour >= 17 else "day",
            "source_url": source_url,
            "start_time": option[0].strftime("%H:%M"),
            "end_time": option[1].strftime("%H:%M") if option[1] else None,
            "timezone_basis": timezone_evidence or "not stated",
        })
    if metadata:
        evidence_sources.append({
            "source": "structured_metadata",
            "value": metadata,
            "classification": label or "unclassified",
            "source_url": source_url,
        })
    for option in metadata_hour_options:
        evidence_sources.append({
            "source": "structured_metadata_hours",
            "value": option[2],
            "classification": "evening" if option[0].hour >= 17 else "day",
            "source_url": source_url,
            "start_time": option[0].strftime("%H:%M"),
            "end_time": option[1].strftime("%H:%M") if option[1] else None,
            "timezone_basis": timezone_evidence or "not stated",
        })

    hours = description_hours or metadata_hours
    descriptions_match_metadata = any(
        description_option[0] == metadata_option[0]
        and (
            description_option[1] is None
            or metadata_option[1] is None
            or description_option[1] == metadata_option[1]
        )
        for description_option in description_hour_options
        for metadata_option in metadata_hour_options
    )
    mixed_shift_options = len(
        {"evening" if option[0].hour >= 17 else "day" for option in hour_options}
    ) > 1
    conflict = bool(
        (
            description_hour_options
            and metadata_hour_options
            and not descriptions_match_metadata
        )
        or (
            hour_options
            and label
            and any(
                ("evening" if option[0].hour >= 17 else "day") != label
                for option in hour_options
            )
        )
    )
    schedule_label = label
    description_text = description.lower()
    if signals["weekend_evening"]:
        evidence_sources.append({
            "source": "job_description",
            "value": "weekend evening coverage",
            "classification": "potential_evening",
            "source_url": source_url,
        })
    elif signals["evening_shift"]:
        evidence_sources.append({
            "source": "job_description",
            "value": "evening/night/second/closing shift mentioned",
            "classification": "potential_evening",
            "source_url": source_url,
        })
    if signals["rotating_shift"]:
        evidence_sources.append({
            "source": "job_description",
            "value": "rotating shift schedule",
            "classification": "rotation_requires_verification",
            "source_url": source_url,
        })
    for signal, label_text in (
        ("after_hours_support", "after-hours support"),
        ("on_call", "on-call coverage"),
        ("continuous_operations", "24/7 or round-the-clock operations"),
        ("global_coverage", "global coverage"),
        ("multiple_shift_options", "multiple shift options"),
    ):
        if signals[signal]:
            evidence_sources.append({
                "source": "job_description",
                "value": label_text,
                "classification": "context_only",
                "source_url": source_url,
            })

    if conflict:
        schedule_type = "needs_verification"
    elif mixed_shift_options:
        schedule_type = "multiple_shift_options"
    elif hours and hours[0].hour < 17:
        schedule_type = "day_shift"
    elif hours and (
        hours[0].hour >= 22
        or (hours[1] is not None and hours[1] <= hours[0])
    ):
        schedule_type = "confirmed_overnight"
    elif hours:
        schedule_type = "confirmed_evening"
    elif label == "day":
        schedule_type = "day_shift"
    elif signals["rotating_shift"]:
        schedule_type = "rotating_shift"
    elif signals["evening_shift"]:
        schedule_type = "needs_verification"
    elif signals["after_hours_support"] or signals["multiple_shift_options"]:
        schedule_type = "needs_verification"
    elif re.search(r"\bflexible\b", f"{description_text} {metadata.lower()}"):
        schedule_type = "flexible"
    else:
        schedule_type = "unknown"

    if conflict:
        result = {
            "status": "needs_verification",
            "schedule_type": schedule_type,
            "schedule_label": schedule_label,
            "start_time": hours[0].strftime("%H:%M"),
            "end_time": hours[1].strftime("%H:%M") if hours[1] else None,
            "timezone": timezone,
            "timezone_evidence": timezone_evidence or None,
            "evidence": [item["value"] for item in evidence_sources],
            "evidence_sources": evidence_sources,
            "source_url": source_url,
            "schedule_signals": signals,
            "needs_schedule_verification": True,
            "conflict": True,
            "reason": "Shift hours conflict with structured schedule metadata; review both sources.",
            "confidence": "low",
        }
    elif hours and mixed_shift_options:
        result = {
            "status": "needs_verification",
            "schedule_type": "multiple_shift_options",
            "schedule_label": schedule_label,
            "start_time": hours[0].strftime("%H:%M"),
            "end_time": hours[1].strftime("%H:%M") if hours[1] else None,
            "timezone": timezone,
            "timezone_evidence": timezone_evidence or None,
            "evidence": [item["value"] for item in evidence_sources],
            "evidence_sources": evidence_sources,
            "source_url": source_url,
            "schedule_signals": signals,
            "needs_schedule_verification": True,
            "conflict": False,
            "reason": (
                "The posting lists both day and evening hours; confirm that "
                "the evening option is available for this role."
            ),
            "confidence": "low",
        }
    elif hours and not timezone_is_toronto:
        result = {
            "status": "needs_verification",
            "schedule_type": (
                "rotating_shift"
                if signals["rotating_shift"]
                else "timezone_unverified"
            ),
            "schedule_label": schedule_label,
            "start_time": hours[0].strftime("%H:%M"),
            "end_time": hours[1].strftime("%H:%M") if hours[1] else None,
            "timezone": None,
            "timezone_evidence": timezone_evidence or None,
            "evidence": [item["value"] for item in evidence_sources],
            "evidence_sources": evidence_sources,
            "source_url": source_url,
            "schedule_signals": signals,
            "needs_schedule_verification": True,
            "conflict": False,
            "reason": (
                "Exact shift hours are listed, but the posting does not establish "
                "that they are in America/Toronto time."
                + (
                    " The schedule is also rotating, so confirm an evening shift "
                    "is consistently available."
                    if signals["rotating_shift"]
                    else ""
                )
            ),
            "confidence": "low",
        }
    elif hours:
        is_evening = hours[0].hour >= 17
        result = {
            "status": "confirmed_evening" if is_evening else "incompatible",
            "schedule_type": schedule_type,
            "schedule_label": schedule_label,
            "start_time": hours[0].strftime("%H:%M"),
            "end_time": hours[1].strftime("%H:%M") if hours[1] else None,
            "timezone": timezone,
            "timezone_evidence": timezone_evidence or None,
            "evidence": hours[2],
            "evidence_sources": evidence_sources,
            "source_url": source_url,
            "schedule_signals": signals,
            "needs_schedule_verification": False,
            "conflict": False,
            "reason": (
                "rotating shifts include stated hours; confirm an evening shift is consistently available"
                if is_evening and signals["rotating_shift"]
                else "explicit shift start at or after 5 PM"
                if is_evening
                else "explicit shift start before 5 PM"
            ),
            "confidence": "high",
        }
        if signals["rotating_shift"] and is_evening:
            result.update(
                status="needs_verification",
                schedule_type="rotating_shift",
                needs_schedule_verification=True,
                conflict=False,
                confidence="medium",
            )
    else:
        label_evidence = [item["value"] for item in evidence_sources if item["classification"] != "unclassified"]
        if schedule_type == "day_shift":
            reason = "day-shift label is present, but exact shift hours are not stated"
        elif schedule_type == "rotating_shift":
            reason = (
                "rotating schedule mentions evening coverage but does not establish a shift start at or after 5 PM"
                if signals["evening_shift"] or signals["weekend_evening"]
                else "rotating schedule does not confirm a shift starting at or after 5 PM"
            )
        elif schedule_type == "needs_verification":
            reason = (
                "evening, closing, night, second-shift, or after-hours coverage is mentioned, "
                "but an exact shift start is not stated"
            )
        elif schedule_type == "flexible":
            reason = "flexible schedule does not confirm a shift starting at or after 5 PM"
        else:
            reason = "shift start time is not stated"
        result = {
            "status": "unknown",
            "schedule_type": schedule_type,
            "schedule_label": schedule_label,
            "start_time": None,
            "end_time": None,
            "timezone": None,
            "timezone_evidence": timezone_evidence or None,
            "evidence": label_evidence,
            "evidence_sources": evidence_sources,
            "source_url": source_url,
            "schedule_signals": signals,
            "needs_schedule_verification": True,
            "conflict": False,
            "reason": reason,
            "confidence": "low",
        }

    if schedule_resolution:
        resolution = schedule_resolution
        if isinstance(resolution, str):
            try:
                import json
                resolution = json.loads(resolution)
            except (TypeError, ValueError):
                resolution = {}
        if (
            isinstance(resolution, dict)
            and resolution.get("value") in {"confirmed_evening", "incompatible"}
            and resolution.get("source")
            and resolution.get("evidence")
            and resolution.get("timestamp")
        ):
            result = {
                **result,
                "status": resolution["value"],
                "conflict": False,
                "manual_resolution": resolution,
                "reason": "Schedule conflict manually resolved using the recorded source.",
                "confidence": "user_verified",
            }
            # The automatic schedule_type/start_time describe the posting as
            # the source currently states it; the manual decision overrides
            # status but not the observed source evidence.
            if resolution["value"] == "confirmed_evening":
                result.setdefault("schedule_type", "confirmed_evening")
            else:
                result["schedule_type"] = "day_shift"
    result["confirmed_evening"] = result["status"] == "confirmed_evening"
    result["needs_schedule_verification"] = (
        result["status"] in {"unknown", "needs_verification"}
    )
    return result


def classify_opportunity(job, schedule_resolution=None):
    if schedule_resolution is None:
        # Honour a persisted manual schedule resolution (with source,
        # evidence, and timestamp) stored on the job record.
        stored = job.get("schedule_classification")
        if isinstance(stored, str):
            try:
                stored = json.loads(stored)
            except (TypeError, ValueError):
                stored = None
        if isinstance(stored, dict):
            resolution = stored.get("manual_resolution")
            if (
                isinstance(resolution, dict)
                and resolution.get("value") in {"confirmed_evening", "incompatible"}
                and resolution.get("source")
                and resolution.get("evidence")
                and resolution.get("timestamp")
            ):
                schedule_resolution = resolution
    evening = classify_evening_eligibility(job, schedule_resolution)
    canada = canadian_eligibility(job)
    blockers = []
    verification_needed = []

    deadline = _text(job.get("deadline")).strip()
    if deadline:
        try:
            normalized_deadline = normalize_source_timestamp(deadline)
            deadline_value = datetime.fromisoformat(
                normalized_deadline.replace("Z", "+00:00")
            )
            now = datetime.now(deadline_value.tzinfo) if deadline_value.tzinfo else datetime.now()
            if deadline_value < now:
                blockers.append("Posting deadline has passed")
        except ValueError:
            verification_needed.append("Posting deadline could not be verified")

    listing_status = _text(job.get("listing_status")).strip()
    if listing_status in {"closed", "expired", "not_listed_on_source"}:
        blockers.append(
            "Posting is no longer listed in the latest successful source snapshot"
            if listing_status == "not_listed_on_source"
            else f"Posting status is {listing_status}"
        )
    elif listing_status == "active_on_source_delayed":
        verification_needed.append(
            "Source feed may lag by 24 hours; verify that the employer posting is still open"
        )
    elif listing_status and listing_status != "active_on_source":
        verification_needed.append("Current posting status has not been verified")
    elif not listing_status and (job.get("source") or job.get("job_url")):
        verification_needed.append("Current posting status has not been verified")

    if canada["status"] == "incompatible":
        blockers.append(canada["reason"])
    elif canada["status"] != "confirmed_compatible":
        verification_needed.append(canada["reason"])

    if evening["status"] == "incompatible":
        blockers.append(evening["reason"])
    elif evening["status"] != "confirmed_evening":
        verification_needed.append(evening["reason"])

    if french_is_mandatory(job):
        blockers.append("French is a mandatory requirement")

    location = _text(job.get("location"))
    local_location = bool(
        re.search(r"\b(?:oakville|mississauga|toronto)\b", location, re.I)
    )
    if not _is_remote(job) and not local_location:
        blockers.append(
            "In-person or hybrid location is outside Oakville, Mississauga, and Toronto"
        )

    if blockers:
        status = "rejected"
        reasons = blockers + verification_needed
    elif verification_needed:
        status = "needs_verification"
        reasons = verification_needed
    else:
        status = "confirmed_evening"
        reasons = ["Canadian eligibility and a shift starting at or after 5 PM are confirmed"]

    location_arrangement = {
        "remote": bool(_is_remote(job)),
        "local_area": local_location,
        "status": (
            "remote" if _is_remote(job) else "local_area" if local_location else "outside_area"
        ),
        "location": location or "not stated",
    }
    return {
        "status": status,
        "reasons": reasons,
        "evening": evening,
        "canadian_eligibility": canada,
        "location_arrangement": location_arrangement,
        "listing_status": listing_status or "unknown",
    }


def opportunity_status_label(opportunity):
    if opportunity.get("status") == "confirmed_evening":
        return "Confirmed Evening"
    if opportunity.get("status") == "rejected":
        return "Not Suitable"
    if opportunity.get("evening", {}).get("conflict"):
        return "Schedule Conflict"
    return "Potential Evening"


def opportunity_priority_key(job, opportunity=None, profile_score=None):
    """Rank non-rejected jobs by location eligibility, schedule, and fit."""
    opportunity = opportunity or classify_opportunity(job)
    eligibility_gate_rank = int(opportunity.get("status") != "rejected")
    canada_rank = {
        "confirmed_compatible": 3,
        "potentially_compatible": 2,
        "unknown": 1,
        "incompatible": 0,
    }.get(opportunity.get("canadian_eligibility", {}).get("status"), 0)

    evening = opportunity.get("evening", {})
    signals = evening.get("schedule_signals", {})
    if evening.get("status") == "confirmed_evening":
        schedule_rank = 3
    elif evening.get("status") == "needs_verification" or any(
        signals.get(key)
        for key in (
            "evening_shift",
            "weekend_evening",
            "rotating_shift",
            "after_hours_support",
            "multiple_shift_options",
        )
    ) or evening.get("conflict"):
        schedule_rank = 2
    elif evening.get("status") == "incompatible":
        schedule_rank = 0
    else:
        schedule_rank = 1

    if profile_score is None:
        try:
            profile_score = float(job.get("match_score") or 0)
        except (TypeError, ValueError):
            profile_score = 0
    try:
        score = float(profile_score)
    except (TypeError, ValueError):
        score = 0

    location = _text(job.get("location"))
    remote = _is_remote(job) or "remote" in location
    local = bool(re.search(r"\b(?:oakville|mississauga|toronto)\b", location))
    arrangement_rank = 2 if remote else 1 if local else 0
    schedule_text = (
        f"{_text(job.get('employment_type'))} {_text(job.get('description'))}"
    )
    if re.search(r"\bpart[- ]time\b|\b20\s*(?:-|to)\s*25\s+hours?\b", schedule_text):
        part_time_rank = 2
    elif re.search(r"\bfull[- ]time\b", schedule_text):
        part_time_rank = 0
    else:
        part_time_rank = 1

    freshness_rank = 0
    posting_date = _text(job.get("posting_date")).strip()
    if posting_date:
        try:
            normalized_posting_date = normalize_source_timestamp(posting_date)
            parsed = datetime.fromisoformat(
                normalized_posting_date.replace("Z", "+00:00")
            )
            current = datetime.now(parsed.tzinfo) if parsed.tzinfo else datetime.now()
            freshness_rank = max(0, 365 - max(0, (current - parsed).days))
        except ValueError:
            freshness_rank = 0

    return (
        eligibility_gate_rank,
        canada_rank,
        schedule_rank,
        score,
        arrangement_rank,
        part_time_rank,
        freshness_rank,
    )
