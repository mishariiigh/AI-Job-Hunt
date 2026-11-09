"""Unified manual job import for Indeed and LinkedIn postings.

No scraping, no browser automation, no credentials: the user supplies the
posting URL and the posting details themselves. Everything the user
provides is recorded as user-supplied, clearly distinguished from any
independently verified information.

Jobs enter the same normalization and persistence pipeline as
discovered postings, so all existing gates (schedule, Canadian
eligibility, location, French, technical matching) apply unchanged.
"""
import re
from urllib.parse import urlparse

# Allowed platforms and their job-URL host patterns.
PLATFORM_URL_PATTERNS = {
    "indeed": re.compile(
        r"(?:^|\.)indeed\.com$", re.I
    ),
    "linkedin": re.compile(
        r"(?:^|\.)linkedin\.com$", re.I
    ),
}

# Platforms whose content is user-supplied and therefore never treated as
# independently verified.
USER_SUPPLIED_SOURCES = {"indeed", "linkedin", "manual"}

IMPORTED_SOURCE_VERSION = 1


class ManualImportError(ValueError):
    """Raised when a manual import payload is invalid."""


def detect_platform(url):
    """Return 'indeed' or 'linkedin' for a recognized job URL, else None."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    host = (parsed.hostname or "").lower()
    if not host:
        return None
    for platform, pattern in PLATFORM_URL_PATTERNS.items():
        if pattern.search(host):
            return platform
    return None


def validate_import(
    url,
    title,
    employer,
    description,
    platform=None,
    employer_application_url=None,
):
    """Validate a manual import payload; raises ManualImportError on failure.

    Returns (platform, normalized fields dict).
    """
    if not isinstance(url, str) or len(url.strip()) < 8:
        raise ManualImportError("A job posting URL is required.")
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ManualImportError("The job URL must be a valid http(s) URL.")
    detected = detect_platform(url)
    if platform is None:
        platform = detected
    if platform not in {"indeed", "linkedin"}:
        raise ManualImportError(
            "Platform must be 'indeed' or 'linkedin'."
        )
    if detected and detected != platform:
        raise ManualImportError(
            f"The URL host does not match the selected platform '{platform}'."
        )
    if detected is None:
        # An explicitly declared platform requires a matching platform URL:
        # a non-platform host (e.g. a Greenhouse board) can never be a
        # genuine Indeed/LinkedIn posting.
        raise ManualImportError(
            "The URL is not an Indeed or LinkedIn job URL."
        )

    if not isinstance(title, str) or len(title.strip()) < 3:
        raise ManualImportError("A job title of at least 3 characters is required.")
    if not isinstance(employer, str) or len(employer.strip()) < 2:
        raise ManualImportError("An employer name is required.")
    if not isinstance(description, str) or len(description.strip()) < 20:
        raise ManualImportError(
            "A job description of at least 20 characters is required."
        )

    fields = {
        "platform": platform,
        "url": url,
        "title": title.strip(),
        "employer": employer.strip(),
        "description": description.strip(),
    }
    if employer_application_url:
        parsed_apply = urlparse(str(employer_application_url).strip())
        if parsed_apply.scheme not in ("http", "https") or not parsed_apply.netloc:
            raise ManualImportError(
                "The employer application URL must be a valid http(s) URL when provided."
            )
        fields["employer_application_url"] = str(employer_application_url).strip()
    return fields


def build_import_job(
    url,
    title,
    employer,
    description,
    location="",
    employment_type="",
    shift_hours="",
    education_required="",
    experience_required="",
    employer_application_url=None,
    platform=None,
    remote=None,
):
    """Build a job record for the existing persistence pipeline.

    Provenance rules:
    - source is the platform ('indeed' or 'linkedin'); it remains
      identifiable after normalization.
    - everything in this record is user-supplied except fields explicitly
      marked otherwise; source_verification_status records this.
    - external_job_id is captured from the platform URL when the pattern is
      recognizable; it is never invented.
    """
    fields = validate_import(
        url, title, employer, description, platform, employer_application_url
    )
    platform = fields["platform"]

    external_id = ""
    if platform == "linkedin":
        match = re.search(r"/jobs/view/[^/]+-(\d+)", fields["url"]) or re.search(
            r"currentJobId=(\d+)", fields["url"]
        )
        if match:
            external_id = match.group(1)
    elif platform == "indeed":
        match = re.search(r"(?:jk|vjk)=([a-f0-9]{6,})", fields["url"], re.I)
        if match:
            external_id = match.group(1)

    # Remote flag: only set when the user states it; never inferred from the
    # platform alone.
    if remote is None:
        remote = bool(location and "remote" in location.lower())
    else:
        remote = bool(remote)

    job = {
        "employer": fields["employer"],
        "job_title": fields["title"],
        "job_url": fields["url"],
        "employer_application_url": fields.get("employer_application_url", ""),
        "source": platform,
        "source_platform": platform,
        "original_source_url": fields["url"],
        "external_job_id": external_id,
        "source_verification_status": "user_supplied",
        "imported_at": None,  # stamped by the tracker at insert time
        "description": fields["description"],
        "location": (location or "").strip(),
        "remote": remote,
        "employment_type": (employment_type or "").strip(),
        "shift": (shift_hours or "").strip(),
        "education_required": (education_required or "").strip(),
        "experience_required": (experience_required or "").strip(),
        "listing_status": "user_imported",
    }
    return job
