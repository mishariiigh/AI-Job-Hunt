"""Stage 12.2 regression tests: schedule classification persisted at ingest.

Uses isolated temporary databases and mocked discovery sources; the
production database is never touched.
"""
import json
import sqlite3
import threading

import pytest

import database.db as db_module
from agents.discovery_agent import DiscoveryAgent
from tracking.application_tracker import ApplicationTracker


@pytest.fixture
def isolated_tracker(tmp_path, monkeypatch):
    db_file = tmp_path / "test_jobs.db"
    monkeypatch.setattr(db_module, "DB_PATH", str(db_file))
    db_module.init_db()
    yield ApplicationTracker()


def _rows(tracker, url):
    conn = sqlite3.connect(db_module.DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM jobs WHERE job_url = ?", (url,)
    ).fetchone()
    conn.close()
    return row


def _insert_evening_job(tracker, url="https://jobs.example.com/evening"):
    return tracker.add_job({
        "employer": "Example Corp",
        "job_title": "Evening Support Analyst",
        "job_url": url,
        "source": "greenhouse",
        "description": "Shift: 5 PM - 1 AM Eastern Time.",
        "location": "Remote - Canada",
        "remote": 1,
        "listing_status": "active_on_source",
    })


def test_new_job_insertion_stores_populated_classification(isolated_tracker):
    job_id = _insert_evening_job(isolated_tracker)
    assert job_id
    row = _rows(isolated_tracker, "https://jobs.example.com/evening")
    classification = json.loads(row["schedule_classification"])
    assert classification["status"] == "confirmed_evening"
    assert classification["start_time"] == "17:00"
    assert classification["timezone"] == "America/Toronto"
    assert classification["evidence"]


def test_refresh_updates_classification_when_schedule_evidence_changes(
    isolated_tracker,
):
    _insert_evening_job(isolated_tracker)
    isolated_tracker.refresh_job_listing({
        "employer": "Example Corp",
        "job_title": "Evening Support Analyst",
        "job_url": "https://jobs.example.com/evening",
        "source": "greenhouse",
        # Employer now publishes daytime hours
        "description": "Shift changed: 9 AM - 5 PM Eastern Time.",
        "location": "Remote - Canada",
        "remote": 1,
        "listing_status": "active_on_source",
    })
    row = _rows(isolated_tracker, "https://jobs.example.com/evening")
    classification = json.loads(row["schedule_classification"])
    assert classification["status"] == "incompatible"
    assert classification["start_time"] == "09:00"


def test_unchanged_refresh_preserves_correct_classification(isolated_tracker):
    _insert_evening_job(isolated_tracker)
    before = _rows(isolated_tracker, "https://jobs.example.com/evening")
    isolated_tracker.refresh_job_listing({
        "employer": "Example Corp",
        "job_title": "Evening Support Analyst",
        "job_url": "https://jobs.example.com/evening",
        "source": "greenhouse",
        "description": "Shift: 5 PM - 1 AM Eastern Time.",
        "location": "Remote - Canada",
        "remote": 1,
        "listing_status": "active_on_source",
    })
    after = _rows(isolated_tracker, "https://jobs.example.com/evening")
    assert json.loads(after["schedule_classification"]) == json.loads(
        before["schedule_classification"]
    )


def test_unknown_schedule_persists_as_needs_verification(isolated_tracker):
    isolated_tracker.add_job({
        "employer": "Example Corp",
        "job_title": "Support Analyst",
        "job_url": "https://jobs.example.com/unknown",
        "source": "greenhouse",
        "description": "Great team and interesting work.",
        "location": "Remote - Canada",
        "remote": 1,
        "listing_status": "active_on_source",
    })
    row = _rows(isolated_tracker, "https://jobs.example.com/unknown")
    classification = json.loads(row["schedule_classification"])
    assert classification["status"] == "unknown"
    assert classification["needs_schedule_verification"] is True
    assert classification["confirmed_evening"] is False


@pytest.mark.parametrize(
    "description",
    [
        "Flexible hours; evening availability preferred.",
        "Rotating shift schedule between day and evening coverage.",
        "Provide on-call support with evening escalations.",
        "Support a 24/7 operations environment.",
        "After-hours support rotation for global teams.",
    ],
)
def test_vague_schedule_language_never_becomes_confirmed_evening(
    isolated_tracker, description,
):
    isolated_tracker.add_job({
        "employer": "Example Corp",
        "job_title": "Support Analyst",
        "job_url": f"https://jobs.example.com/{abs(hash(description))}",
        "source": "greenhouse",
        "description": description,
        "location": "Remote - Canada",
        "remote": 1,
        "listing_status": "active_on_source",
    })
    # Recompute URL deterministically for lookup
    url = f"https://jobs.example.com/{abs(hash(description))}"
    row = _rows(isolated_tracker, url)
    classification = json.loads(row["schedule_classification"])
    assert classification["status"] != "confirmed_evening"
    assert classification["confirmed_evening"] is False


def test_verified_5pm_start_classified_correctly(isolated_tracker):
    _insert_evening_job(isolated_tracker)
    row = _rows(isolated_tracker, "https://jobs.example.com/evening")
    classification = json.loads(row["schedule_classification"])
    assert classification["status"] == "confirmed_evening"


def test_manual_schedule_resolution_is_not_overwritten(isolated_tracker):
    manual = {
        "status": "confirmed_evening",
        "schedule_type": "confirmed_evening",
        "start_time": "17:00",
        "end_time": "01:00",
        "timezone": "America/Toronto",
        "manual_resolution": {
            "value": "confirmed_evening",
            "source": "https://employer.example.com/careers/job-1",
            "evidence": "Employer confirmed shift 5 PM - 1 AM by email",
            "timestamp": "2026-01-01T12:00:00-05:00",
        },
    }
    isolated_tracker.add_job({
        "employer": "Example Corp",
        "job_title": "Support Analyst",
        "job_url": "https://jobs.example.com/manual",
        "source": "greenhouse",
        "description": "Hours not stated in posting.",
        "location": "Remote - Canada",
        "remote": 1,
        "listing_status": "active_on_source",
        "schedule_classification": manual,
    })
    # Refresh with a description that does NOT state qualifying hours:
    # the manual resolution must survive.
    isolated_tracker.refresh_job_listing({
        "employer": "Example Corp",
        "job_title": "Support Analyst",
        "job_url": "https://jobs.example.com/manual",
        "source": "greenhouse",
        "description": "Hours not stated in posting.",
        "location": "Remote - Canada",
        "remote": 1,
        "listing_status": "active_on_source",
        "schedule_classification": manual,
    })
    row = _rows(isolated_tracker, "https://jobs.example.com/manual")
    classification = json.loads(row["schedule_classification"])
    assert classification["status"] == "confirmed_evening"
    assert classification["manual_resolution"]["value"] == "confirmed_evening"


def test_discovery_persists_classification_through_add_and_refresh(
    isolated_tracker, monkeypatch,
):
    """End-to-end with mocked sources: ingest + refresh path persists
    classification, and recommendation behavior is unchanged."""
    agent = DiscoveryAgent()
    job = {
        "employer": "Mock Corp",
        "job_title": "NOC Technician",
        "job_url": "https://jobs.example.com/noc",
        "source": "greenhouse",
        "source_feed": "mock",
        "description": "Evening shift 6 PM - 10 PM Eastern Time monitoring.",
        "location": "Remote - Canada",
        "remote": 1,
        "listing_status": "active_on_source",
    }
    passed, _ = agent.filter_job(dict(job))
    assert passed
    # filter_job itself attaches the classification
    prepared = dict(job)
    agent.filter_job(prepared)
    assert prepared["schedule_classification"]["status"] == "confirmed_evening"
    job_id = isolated_tracker.add_job(prepared)
    row = _rows(isolated_tracker, "https://jobs.example.com/noc")
    classification = json.loads(row["schedule_classification"])
    assert classification["status"] == "confirmed_evening"
    assert classification["start_time"] == "18:00"
    # Recommendation classification from the stored row agrees
    stored = dict(row)
    from agents.job_classifier import classify_opportunity
    opportunity = classify_opportunity(stored)
    assert opportunity["status"] in {"confirmed_evening", "needs_verification"}


# --- Stage 12.2 follow-up: manual resolution survives the REAL discovery path ---

def _insert_manually_resolved_job(tracker, url, description):
    manual = {
        "status": "confirmed_evening",
        "schedule_type": "confirmed_evening",
        "start_time": "17:00",
        "end_time": "01:00",
        "timezone": "America/Toronto",
        "manual_resolution": {
            "value": "confirmed_evening",
            "source": "https://employer.example.com/careers/job-1",
            "evidence": "Employer confirmed shift 5 PM - 1 AM by email",
            "timestamp": "2026-01-01T12:00:00-05:00",
        },
    }
    tracker.add_job({
        "employer": "Example Corp",
        "job_title": "Support Analyst",
        "job_url": url,
        "source": "greenhouse",
        "description": description,
        "location": "Remote - Canada",
        "remote": 1,
        "listing_status": "active_on_source",
        "schedule_classification": manual,
    })


def _feed_payload(url, description):
    """A source payload as discovery produces it: classification is
    recomputed automatically and manual_resolution is NEVER present."""
    payload = {
        "employer": "Example Corp",
        "job_title": "Support Analyst",
        "job_url": url,
        "source": "greenhouse",
        "description": description,
        "location": "Remote - Canada",
        "remote": 1,
        "listing_status": "active_on_source",
    }
    from agents.job_classifier import classify_evening_eligibility
    payload["schedule_classification"] = classify_evening_eligibility(payload)
    assert "manual_resolution" not in payload["schedule_classification"]
    return payload


def test_real_discovery_refresh_preserves_manual_resolution(isolated_tracker):
    """End-to-end: job with manual resolution, next discovery run fetches
    the same job without manual_resolution, refresh_job_listing is called
    with an automatically computed classification."""
    url = "https://jobs.example.com/real-refresh"
    description = "Hours not stated in the posting."
    _insert_manually_resolved_job(isolated_tracker, url, description)

    # Next discovery run: feed payload lacks manual_resolution
    payload = _feed_payload(url, description)
    assert isolated_tracker.job_exists(url)
    isolated_tracker.refresh_job_listing(payload)

    row = _rows(isolated_tracker, url)
    classification = json.loads(row["schedule_classification"])
    assert classification["status"] == "confirmed_evening"
    assert classification["manual_resolution"]["value"] == "confirmed_evening"
    assert classification["manual_resolution"]["evidence"] == (
        "Employer confirmed shift 5 PM - 1 AM by email"
    )
    assert classification["manual_evidence_needs_reverification"] is False
    # Recommendation category still honours the manual decision
    from agents.job_classifier import classify_opportunity
    opportunity = classify_opportunity(dict(row))
    assert opportunity["status"] == "confirmed_evening"


def test_real_discovery_refresh_with_changed_description_flags_reverification(
    isolated_tracker,
):
    url = "https://jobs.example.com/real-refresh-changed"
    _insert_manually_resolved_job(
        isolated_tracker, url, "Original posting text without hours."
    )
    # Source now publishes different text (daytime hours)
    payload = _feed_payload(url, "Updated posting: day shift 9 AM - 5 PM.")
    isolated_tracker.refresh_job_listing(payload)

    row = _rows(isolated_tracker, url)
    classification = json.loads(row["schedule_classification"])
    # Manual decision retained, never overwritten by automatic classification
    assert classification["status"] == "confirmed_evening"
    assert classification["manual_resolution"]["value"] == "confirmed_evening"
    # But flagged because the supporting posting text changed
    assert classification["manual_evidence_needs_reverification"] is True
    assert "re-verify" in classification["reason"].lower()
    # Automatic classification evidence is preserved in the merged record
    # (start_time reflects the posting's stated hours), while the manual
    # decision sets the effective schedule_type.
    assert classification["schedule_type"] == "confirmed_evening"
    assert classification["start_time"] == "09:00"
    # A subsequent identical refresh must KEEP the flag set: only an
    # explicit user re-verification may clear it.
    isolated_tracker.refresh_job_listing(payload)
    row2 = _rows(isolated_tracker, url)
    classification2 = json.loads(row2["schedule_classification"])
    assert classification2["manual_evidence_needs_reverification"] is True


def test_real_discovery_refresh_without_manual_resolution_unaffected(
    isolated_tracker,
):
    """Jobs that never had a manual resolution classify normally."""
    url = "https://jobs.example.com/no-manual"
    payload = _feed_payload(url, "Shift: 5 PM - 1 AM Eastern Time.")
    isolated_tracker.add_job(payload)
    isolated_tracker.refresh_job_listing(payload)
    row = _rows(isolated_tracker, url)
    classification = json.loads(row["schedule_classification"])
    assert classification["status"] == "confirmed_evening"
    assert "manual_resolution" not in classification
    assert classification.get("manual_evidence_needs_reverification") is None


# --- Re-verification lifecycle: flag must survive repeated refreshes ---

def test_repeated_identical_refreshes_after_change_never_clear_flag(
    isolated_tracker,
):
    """The re-verification flag must not clear just because the changed
    description fingerprint now matches the last-stored fingerprint. The
    anchor is the description at the ORIGINAL manual verification, and
    automatic refreshes never move it."""
    url = "https://jobs.example.com/reverify-lifecycle"
    _insert_manually_resolved_job(isolated_tracker, url, "Original posting text.")
    changed = "Updated posting: day shift 9 AM - 5 PM."

    payload = _feed_payload(url, changed)
    isolated_tracker.refresh_job_listing(payload)
    row = _rows(isolated_tracker, url)
    classification = json.loads(row["schedule_classification"])
    assert classification["manual_evidence_needs_reverification"] is True

    # Repeated identical refreshes must keep the flag set
    for _ in range(3):
        isolated_tracker.refresh_job_listing(payload)
        row = _rows(isolated_tracker, url)
        classification = json.loads(row["schedule_classification"])
        assert classification["manual_evidence_needs_reverification"] is True
        assert classification["status"] == "confirmed_evening"
        assert classification["manual_resolution"]["evidence"] == (
            "Employer confirmed shift 5 PM - 1 AM by email"
        )

    # Original manual resolution and evidence remain available for review
    assert classification["manual_resolution"]["source"] == (
        "https://employer.example.com/careers/job-1"
    )
    assert classification["manual_resolution"]["timestamp"]
    # Automatic schedule observations preserved separately
    assert classification["start_time"] == "09:00"


def test_reverting_description_does_not_clear_flag_either(isolated_tracker):
    """Even if the posting text goes back to what the user verified, only an
    explicit re-verification may clear the flag."""
    url = "https://jobs.example.com/reverify-revert"
    original = "Original posting text."
    _insert_manually_resolved_job(isolated_tracker, url, original)
    isolated_tracker.refresh_job_listing(_feed_payload(url, "Changed 9 AM - 5 PM."))
    row = _rows(isolated_tracker, url)
    assert json.loads(row["schedule_classification"])[
        "manual_evidence_needs_reverification"
    ] is True
    # Back to the original description: flag persists
    isolated_tracker.refresh_job_listing(_feed_payload(url, original))
    row = _rows(isolated_tracker, url)
    assert json.loads(row["schedule_classification"])[
        "manual_evidence_needs_reverification"
    ] is True


def test_explicit_reverification_clears_flag_and_reanchors(isolated_tracker):
    """The dedicated explicit operation (record_manual_schedule_resolution)
    is the only way to replace a resolution, re-anchor the fingerprint, and
    clear the flag."""
    url = "https://jobs.example.com/reverify-explicit"
    _insert_manually_resolved_job(isolated_tracker, url, "Original posting text.")
    changed = "Updated posting: day shift 9 AM - 5 PM."
    isolated_tracker.refresh_job_listing(_feed_payload(url, changed))
    row = _rows(isolated_tracker, url)
    assert json.loads(row["schedule_classification"])[
        "manual_evidence_needs_reverification"
    ] is True

    from tracking.application_tracker import ManualResolutionError
    job_id = row["id"]
    tracker = isolated_tracker
    new_resolution = {
        "value": "incompatible",
        "source": "https://employer.example.com/careers/job-1",
        "evidence": "Current posting states day shift 9 AM - 5 PM",
        "timestamp": "2026-11-05T10:00:00-05:00",
    }
    merged = tracker.record_manual_schedule_resolution(job_id, new_resolution)
    assert merged["manual_evidence_needs_reverification"] is False
    assert merged["status"] == "incompatible"

    row = _rows(isolated_tracker, url)
    classification = json.loads(row["schedule_classification"])
    assert classification["manual_evidence_needs_reverification"] is False
    assert classification["status"] == "incompatible"
    assert classification["manual_resolution"]["evidence"] == (
        "Current posting states day shift 9 AM - 5 PM"
    )
    # Fingerprint re-anchored to the CURRENT description
    assert classification["description_fingerprint_at_resolution"] == (
        tracker._description_fingerprint(changed)
    )

    # Automatic refreshes after re-verification keep the flag cleared
    isolated_tracker.refresh_job_listing(_feed_payload(url, changed))
    row = _rows(isolated_tracker, url)
    classification = json.loads(row["schedule_classification"])
    assert classification["manual_evidence_needs_reverification"] is False
    assert classification["status"] == "incompatible"


def test_discovery_payload_with_manual_resolution_cannot_reverify(
    isolated_tracker,
):
    """Provenance: a feed payload carrying a new, valid-looking
    manual_resolution must NOT clear the re-verification flag or replace
    the stored resolution. Only record_manual_schedule_resolution may."""
    url = "https://jobs.example.com/provenance"
    _insert_manually_resolved_job(isolated_tracker, url, "Original posting text.")
    changed = "Updated posting: day shift 9 AM - 5 PM."
    isolated_tracker.refresh_job_listing(_feed_payload(url, changed))
    row = _rows(isolated_tracker, url)
    assert json.loads(row["schedule_classification"])[
        "manual_evidence_needs_reverification"
    ] is True

    # Attacker-controlled / feed-produced resolution in the payload
    forged = {
        "status": "confirmed_evening",
        "schedule_type": "confirmed_evening",
        "manual_resolution": {
            "value": "confirmed_evening",
            "source": "https://evil.example.com/fake-source",
            "evidence": "Trust me, this is evening",
            "timestamp": "2026-11-05T10:00:00-05:00",
        },
    }
    payload = _feed_payload(url, changed)
    payload["schedule_classification"] = forged
    isolated_tracker.refresh_job_listing(payload)

    row = _rows(isolated_tracker, url)
    classification = json.loads(row["schedule_classification"])
    # Flag NOT cleared; stored resolution NOT replaced
    assert classification["manual_evidence_needs_reverification"] is True
    assert classification["manual_resolution"]["evidence"] == (
        "Employer confirmed shift 5 PM - 1 AM by email"
    )
    assert classification["manual_resolution"]["source"] == (
        "https://employer.example.com/careers/job-1"
    )
    assert classification["status"] == "confirmed_evening"


def test_normal_refresh_cannot_reanchor_fingerprint(isolated_tracker):
    """The description fingerprint anchor only moves on explicit
    re-verification; ordinary refreshes preserve it."""
    url = "https://jobs.example.com/anchor"
    original = "Original posting text."
    _insert_manually_resolved_job(isolated_tracker, url, original)
    row = _rows(isolated_tracker, url)
    original_anchor = json.loads(row["schedule_classification"])[
        "description_fingerprint_at_resolution"
    ]
    assert original_anchor == isolated_tracker._description_fingerprint(original)

    changed = "Updated posting: day shift 9 AM - 5 PM."
    isolated_tracker.refresh_job_listing(_feed_payload(url, changed))
    row = _rows(isolated_tracker, url)
    classification = json.loads(row["schedule_classification"])
    assert classification["description_fingerprint_at_resolution"] == original_anchor

    isolated_tracker.refresh_job_listing(_feed_payload(url, "Another change."))
    row = _rows(isolated_tracker, url)
    classification = json.loads(row["schedule_classification"])
    assert classification["description_fingerprint_at_resolution"] == original_anchor


def test_incomplete_reverification_rejected(isolated_tracker):
    """record_manual_schedule_resolution rejects incomplete resolutions and
    changes nothing."""
    from tracking.application_tracker import ManualResolutionError
    url = "https://jobs.example.com/reverify-invalid"
    _insert_manually_resolved_job(isolated_tracker, url, "Original posting text.")
    changed = "Updated posting: day shift 9 AM - 5 PM."
    isolated_tracker.refresh_job_listing(_feed_payload(url, changed))
    row = _rows(isolated_tracker, url)
    job_id = row["id"]
    before = row["schedule_classification"]

    for bad in (
        {"value": "confirmed_evening"},  # missing source/evidence/timestamp
        {"value": "maybe", "source": "s", "evidence": "e", "timestamp": "t"},
        {"value": "incompatible", "source": "", "evidence": "e", "timestamp": "t"},
        {"value": "incompatible", "source": "s", "evidence": "", "timestamp": "t"},
        {"value": "incompatible", "source": "s", "evidence": "e", "timestamp": ""},
        "not a dict",
    ):
        with pytest.raises(ManualResolutionError):
            isolated_tracker.record_manual_schedule_resolution(job_id, bad)

    # Nothing changed
    row = _rows(isolated_tracker, url)
    assert row["schedule_classification"] == before
    classification = json.loads(row["schedule_classification"])
    assert classification["manual_evidence_needs_reverification"] is True
    assert classification["manual_resolution"]["evidence"] == (
        "Employer confirmed shift 5 PM - 1 AM by email"
    )


def test_reverification_is_atomic_against_concurrent_description_change(
    isolated_tracker,
):
    """The SELECT and UPDATE inside record_manual_schedule_resolution run in
    one BEGIN IMMEDIATE transaction, so a concurrent discovery refresh
    cannot change the description between verification and persistence."""
    import sqlite3

    url = "https://jobs.example.com/atomic"
    original = "Original posting text."
    _insert_manually_resolved_job(isolated_tracker, url, original)
    row = _rows(isolated_tracker, url)
    job_id = row["id"]

    # Fire a concurrent writer that tries to change the description while
    # the re-verification transaction holds the write lock. With BEGIN
    # IMMEDIATE the writer either waits (serialized) or fails busy; either
    # way it cannot interleave between the SELECT and the UPDATE.
    writer_error = []

    def concurrent_refresh():
        try:
            conn = sqlite3.connect(db_module.DB_PATH, timeout=0.2)
            conn.execute(
                "UPDATE jobs SET description = ? WHERE id = ?",
                ("CHANGED DURING WINDOW", job_id),
            )
            conn.commit()
            conn.close()
        except sqlite3.OperationalError as exc:
            writer_error.append(exc)

    writer = threading.Thread(target=concurrent_refresh)
    # Start the writer just before the transaction opens, then join after.
    writer.start()
    merged = isolated_tracker.record_manual_schedule_resolution(
        job_id,
        {
            "value": "confirmed_evening",
            "source": "https://employer.example.com/careers/job-1",
            "evidence": "User re-verified against the current posting",
            "timestamp": "2026-11-05T10:00:00-05:00",
        },
    )
    writer.join()

    final_row = _rows(isolated_tracker, url)
    classification = json.loads(final_row["schedule_classification"])
    # No torn state: the persisted fingerprint equals the fingerprint of
    # either the description the user verified or the description the
    # serialized concurrent refresh wrote — never a mix, because the SELECT
    # and UPDATE share one BEGIN IMMEDIATE transaction.
    fingerprint = isolated_tracker._description_fingerprint
    assert classification["description_fingerprint_at_resolution"] in {
        fingerprint("Original posting text."),
        fingerprint("CHANGED DURING WINDOW"),
    }
    assert classification["status"] == "confirmed_evening"
    assert classification["manual_evidence_needs_reverification"] is False
    assert classification["manual_resolution"]["evidence"] == (
        "User re-verified against the current posting"
    )


def test_normal_jobs_have_no_reverification_flag(isolated_tracker):
    url = "https://jobs.example.com/no-manual-lifecycle"
    payload = _feed_payload(url, "Shift: 5 PM - 1 AM Eastern Time.")
    isolated_tracker.add_job(payload)
    isolated_tracker.refresh_job_listing(payload)
    row = _rows(isolated_tracker, url)
    classification = json.loads(row["schedule_classification"])
    assert classification["status"] == "confirmed_evening"
    assert "manual_resolution" not in classification
    assert classification.get("manual_evidence_needs_reverification") is None
