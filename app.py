import streamlit as st
import pandas as pd
import json
from database.db import get_conn
from tracking.application_tracker import ApplicationTracker
from agents.discovery_agent import DiscoveryAgent
from agents.matching_agent import MatchingAgent
from config.source_config import load_sources, save_sources
from sources.validator import SourceValidator
from agents.job_classifier import (
    classify_opportunity,
    opportunity_priority_key,
    opportunity_status_label,
)
from datetime import datetime
from collections import Counter

st.set_page_config(page_title="AI Job Hunter", layout="wide")

st.markdown("""
<style>
section[data-testid="stSidebar"] {background:#ffffff;border-right:1px solid #e5e7eb;}
section[data-testid="stSidebar"] .stRadio label {padding:.5rem .75rem;border-radius:8px;}
section[data-testid="stSidebar"] .stRadio label:hover {background:#f1f5f9;}
</style>
""", unsafe_allow_html=True)

tracker = ApplicationTracker()
discovery = DiscoveryAgent()
validator = SourceValidator()
matcher = MatchingAgent()

st.sidebar.markdown("### AI Job Hunter")
st.sidebar.caption("Find. Prepare. Apply.")
navigation_target = st.session_state.pop("navigation_target", None)
if navigation_target:
    st.session_state["main_navigation"] = navigation_target
page = st.sidebar.radio(
    "Navigation",
    ["Dashboard", "Recommended Jobs", "My Applications", "Profile", "Settings", "Help"],
    key="main_navigation",
)

# Sub-navigation preserving existing features
if page == "Recommended Jobs":
    sub = st.sidebar.radio("Section", ["Recommended Jobs", "Discover Jobs"], key="rec_sub_v2")
    page = sub
elif page == "My Applications":
    sub = st.sidebar.radio("Section", ["My Applications", "Application Review"], key="apps_sub")
    page = sub
elif page == "Profile":
    profile_sub_target = st.session_state.pop("profile_sub_target", None)
    if profile_sub_target:
        st.session_state["prof_sub"] = profile_sub_target
    sub = st.sidebar.radio("Section", ["Candidate Profile", "Resume Manager"], key="prof_sub")
    page = sub
elif page == "Settings":
    sub = st.sidebar.radio("Section", ["Settings", "Source Configuration", "Job Bank Import", "Manual Job Intake"], key="set_sub")
    page = "Discover Jobs" if sub == "Source Configuration" else sub


def get_jobs_df():
    jobs = tracker.get_jobs()
    if not jobs:
        return pd.DataFrame()
    return pd.DataFrame(jobs)


def application_progress(applications):
    counts = {
        "awaiting_review": 0,
        "approved": 0,
        "submitted": 0,
        "interviews": 0,
        "rejected": 0,
        "follow_up": 0,
    }
    for application in applications:
        status = str(application.get("status") or "").strip().lower()
        submission_state = str(application.get("submission_state") or "").strip().lower()
        interview_status = str(application.get("interview_status") or "").strip().lower()
        notes = str(application.get("notes") or "").strip().lower()

        if status in {
            "prepared", "preparing", "awaiting review", "pending_approval",
            "draft", "needs information", "ready for review",
        }:
            counts["awaiting_review"] += 1
        if status in {"approved", "approved for submission", "ready"} or submission_state in {"ready", "approved"}:
            counts["approved"] += 1
        if status in {
            "submitted", "manually submitted", "applied", "confirmed"
        } or submission_state in {"submitted", "confirmed", "manually_submitted"}:
            counts["submitted"] += 1
        if "interview" in status or "interview" in interview_status:
            counts["interviews"] += 1
        if status == "rejected":
            counts["rejected"] += 1
        if "follow-up" in status or "follow up" in status or "follow-up" in notes or "follow up" in notes:
            counts["follow_up"] += 1
    return counts


if page == "Dashboard":
    st.title("Dashboard")
    jobs = tracker.get_jobs()
    classified_jobs = [(job, classify_opportunity(job)) for job in jobs]
    job_counts = Counter(result["status"] for _, result in classified_jobs)
    applications = tracker.get_applications()
    progress = application_progress(applications)

    st.subheader("Suitable jobs")
    cols = st.columns(3)
    cols[0].metric("Confirmed evening matches", job_counts["confirmed_evening"])
    cols[1].metric("Needs verification", job_counts["needs_verification"])
    cols[2].metric("Rejected", job_counts["rejected"])

    st.subheader("Application progress")
    cols = st.columns(6)
    cols[0].metric("Awaiting review", progress["awaiting_review"])
    cols[1].metric("Approved, ready to submit", progress["approved"])
    cols[2].metric("Submitted", progress["submitted"])
    cols[3].metric("Interviews", progress["interviews"])
    cols[4].metric("Rejected", progress["rejected"])
    cols[5].metric("Follow-up", progress["follow_up"])

    st.subheader("Your next actions")
    if job_counts["confirmed_evening"]:
        st.write("Review confirmed evening matches in Recommended Jobs before preparing an application.")
    else:
        st.info("There are no confirmed evening matches yet. Verify missing shift times and Canadian applicant eligibility in Recommended Jobs.")
    if progress["awaiting_review"]:
        st.write(f"Review {progress['awaiting_review']} application(s) in My Applications.")
    if progress["follow_up"]:
        st.write(f"Follow up on {progress['follow_up']} application(s) that need attention.")

    st.subheader("Recently discovered suitable jobs")
    confirmed_jobs = [
        (job, result) for job, result in classified_jobs
        if result["status"] == "confirmed_evening"
    ]
    if confirmed_jobs:
        for job, result in confirmed_jobs[:5]:
            st.markdown(f"**{job.get('job_title') or 'Untitled role'}** — {job.get('employer') or 'Employer not listed'}")
            st.caption(
                f"{job.get('location') or 'Location not listed'} · "
                f"{job.get('employment_type') or 'Employment type not listed'} · "
                f"Match score {job.get('match_score') or 0:.0f}/100"
            )
    else:
        st.caption("No roles currently meet the confirmed Canada and shift-time checks.")

    st.subheader("Recent activity")
    if jobs:
        for job in jobs[:5]:
            discovered = str(job.get("discovered_at") or "")
            date_label = discovered[:10] if discovered else "Date not recorded"
            st.write(f"Discovered: {job.get('job_title') or 'Untitled role'} at {job.get('employer') or 'unknown employer'} · {date_label}")
    else:
        st.info("No live job discoveries have been recorded.")
    if applications:
        for application in applications[:5]:
            st.write(
                f"Application {application.get('id')}: "
                f"{application.get('status') or 'status not set'} · "
                f"{application.get('applied_at') or 'date not recorded'}"
            )
    else:
        st.caption("No applications have been prepared or submitted.")

    with st.expander("Discovery diagnostics"):
        st.write(f"Total stored live-job records: {len(jobs)}")
        st.write("Records by source:", dict(Counter(job.get("source") or "Unknown" for job in jobs)))
        reason_counts = Counter(
            reason
            for _, result in classified_jobs
            if result["status"] == "needs_verification"
            for reason in result["reasons"]
        )
        if reason_counts:
            st.write("Most common verification gaps:", dict(reason_counts.most_common(5)))


elif page == "Discover Jobs":
    st.title("Discover Jobs")
    from config.source_config import load_sources, save_sources, enabled_tokens
    sources_cfg = load_sources()
    st.subheader("Greenhouse Boards")
    for i, b in enumerate(sources_cfg.get("greenhouse_boards", [])):
        c1, c2, c3, c4 = st.columns([3,1,1,1])
        c1.write(f"{b['token']} | status: {b.get('status','unknown')} | retrieved: {b.get('last_retrieved',0)}")
        if c2.button("Validate", key=f"val_gh_{i}"):
            from sources.validator import SourceValidator
            v = SourceValidator().validate_greenhouse(b["token"])
            b["status"] = v.get("status")
            b["last_retrieved"] = v.get("job_count", 0)
            b["last_checked"] = v.get("last_checked","")
            save_sources(sources_cfg)
            st.rerun()
        if c3.button("Toggle", key=f"tgl_gh_{i}"):
            b["enabled"] = not b["enabled"]
            save_sources(sources_cfg)
            st.rerun()
        if c4.button("Remove", key=f"rm_gh_{i}"):
            sources_cfg["greenhouse_boards"].pop(i)
            save_sources(sources_cfg)
            st.rerun()
    new_gh = st.text_input("Add Greenhouse board", key="add_gh")
    if st.button("Add Greenhouse", key="add_gh_btn") and new_gh.strip():
        sources_cfg["greenhouse_boards"].append({"token": new_gh.strip(), "enabled": True, "status": "unknown", "last_retrieved": 0, "last_checked": ""})
        save_sources(sources_cfg)
        st.rerun()

    st.subheader("Lever Boards")
    for i, b in enumerate(sources_cfg.get("lever_boards", [])):
        c1, c2, c3, c4 = st.columns([3,1,1,1])
        c1.write(f"{b['token']} | status: {b.get('status','unknown')} | retrieved: {b.get('last_retrieved',0)}")
        if c2.button("Validate", key=f"val_lv_{i}"):
            from sources.validator import SourceValidator
            v = SourceValidator().validate_lever(b["token"])
            b["status"] = v.get("status")
            b["last_retrieved"] = v.get("job_count", 0)
            b["last_checked"] = v.get("last_checked","")
            save_sources(sources_cfg)
            st.rerun()
        if c3.button("Toggle", key=f"tgl_lv_{i}"):
            b["enabled"] = not b["enabled"]
            save_sources(sources_cfg)
            st.rerun()
        if c4.button("Remove", key=f"rm_lv_{i}"):
            sources_cfg["lever_boards"].pop(i)
            save_sources(sources_cfg)
            st.rerun()
    new_lv = st.text_input("Add Lever board", key="add_lv")
    if st.button("Add Lever", key="add_lv_btn") and new_lv.strip():
        sources_cfg["lever_boards"].append({"token": new_lv.strip(), "enabled": True, "status": "unknown", "last_retrieved": 0, "last_checked": ""})
        save_sources(sources_cfg)
        st.rerun()

    if st.button("Run Live Discovery", key="run_live_discovery"):
        gh_tokens = enabled_tokens(sources_cfg, "greenhouse_boards")
        lv_tokens = enabled_tokens(sources_cfg, "lever_boards")
        if not gh_tokens and not lv_tokens:
            st.warning("No enabled boards. Add/enable boards above.")
        else:
            with st.spinner("Discovering..."):
                discovered, stats = discovery.discover(greenhouse_boards=gh_tokens, lever_boards=lv_tokens)
                st.success(f"New: {stats['new_saved']}, Retrieved: {stats['retrieved']}")
                st.json(stats)

    st.subheader("Scheduled Discovery")
    import json, os
    runs_path = os.path.join("storage", "discovery_runs.json")
    if os.path.exists(runs_path):
        try:
            runs = json.load(open(runs_path))
        except Exception:
            runs = []
    else:
        runs = []
    if runs:
        r = runs[0]
        st.write(
            f"Last run: {r.get('start')} | status: {r.get('status')} | "
            f"retrieved: {r.get('retrieved')} | new: {r.get('new_saved')} | "
            f"previously known: {r.get('previously_known', r.get('duplicates'))} | "
            f"possible repost groups: {r.get('possible_repost_groups', 0)}"
        )
        if r.get("error"):
            st.error(r["error"])
        st.write("Recent runs:")
        for r in runs[:5]:
            st.write(f"{r['run_id']} {r['status']} retrieved={r['retrieved']} new={r['new_saved']} dup={r['duplicates']}")
    else:
        st.info("No scheduled discovery runs yet.")
    st.write("Run manually: `python3 discovery_worker.py once`")
    st.write("Start worker: `python3 discovery_worker.py`")

elif page == "Recommended Jobs":
    st.title("Recommended Jobs")
    st.caption(
        "Hard gates first: a job is a confirmed evening recommendation only when a shift "
        "starting at or after 5:00 PM (America/Toronto), Canadian eligibility, acceptable "
        "location, and no disqualifying requirements are all verified. The technical match "
        "score never overrides a failed or unknown gate."
    )
    jobs = tracker.get_jobs()
    if not jobs:
        st.info("No live job postings have been discovered yet. Use discovery or Manual Job Intake to add a current vacancy.")
    else:
        classified_jobs = [(job, classify_opportunity(job)) for job in jobs]

        def recommendation_category(job, result):
            """Map opportunity status to one of the three display categories."""
            if result["status"] == "confirmed_evening":
                return "Confirmed Evening"
            if result["status"] == "rejected":
                return "Not Suitable"
            return "Needs Verification"

        category_order = ["Confirmed Evening", "Needs Verification", "Not Suitable"]
        counts = Counter(recommendation_category(job, result) for job, result in classified_jobs)
        cols = st.columns(3)
        for column, label in zip(cols, category_order):
            column.metric(label, counts[label])

        with st.expander("Filters", expanded=True):
            c1, c2, c3 = st.columns(3)
            category_filter = c1.selectbox("Recommendation category", ["All", *category_order])
            min_score = c2.slider("Minimum technical match score", 0, 100, 0)
            sources = sorted({str(job.get("source") or "Unknown") for job in jobs})
            source_filter = c3.selectbox("Source", ["All"] + sources)
            c4, c5 = st.columns(2)
            query = c4.text_input("Search employer or job title")
            display_limit = st.selectbox("Maximum postings per section", [10, 25, 50, "All"], index=1)

        filtered_jobs = []
        for job, result in classified_jobs:
            score = float(job.get("match_score") or 0)
            category = recommendation_category(job, result)
            if category_filter != "All" and category != category_filter:
                continue
            if score < min_score:
                continue
            if source_filter != "All" and (job.get("source") or "Unknown") != source_filter:
                continue
            if query and query.lower() not in f"{job.get('employer', '')} {job.get('job_title', '')}".lower():
                continue
            filtered_jobs.append((job, result, score, category))

        filtered_jobs.sort(
            key=lambda item: opportunity_priority_key(
                item[0], item[1], profile_score=item[2]
            ),
            reverse=True,
        )

        st.caption(f"{len(filtered_jobs)} posting(s) match these filters.")

        with st.expander("Match diagnostics"):
            if st.button("Recalculate all match scores"):
                with st.spinner("Recalculating match scores..."):
                    for job in jobs:
                        match_result = matcher.score_job(dict(job))
                        matcher.save_match(job["id"], match_result)
                st.success("Match scores recalculated.")
                st.rerun()
            st.info(
                "Match scores are technical profile signals only. They never change which "
                "category a job appears in or override a failed or unverified eligibility gate."
            )

        applications_by_job = {}
        for existing_application in tracker.get_applications():
            applications_by_job.setdefault(existing_application.get("job_id"), existing_application)

        for category in category_order:
            category_jobs = [item for item in filtered_jobs if item[3] == category]
            st.subheader(f"{category} ({len(category_jobs)})")
            if category == "Confirmed Evening":
                st.caption("All hard gates verified: qualifying evening shift, Canadian eligibility, acceptable location, no disqualifiers.")
            elif category == "Needs Verification":
                st.caption("Potentially suitable, but the schedule, eligibility, or another key detail is unverified. These are NOT confirmed evening opportunities.")
            else:
                st.caption("Verified incompatible with your requirements. Shown here and in filters for audit purposes.")
            if not category_jobs:
                st.info("No jobs currently in this category.")
                continue
            shown = category_jobs if display_limit == "All" else category_jobs[:display_limit]
            for job, result, score, category in shown:
                with st.container(border=True):
                    col1, col2 = st.columns([4, 1])
                    with col1:
                        st.subheader(job.get("job_title") or "Untitled role")
                        st.write(f"{job.get('employer') or 'Employer not listed'} · {job.get('location') or 'Location not listed'}")
                    if (job.get("source") or "").lower() == "remotive":
                        st.caption(
                            "Source: Remotive API · listings may be delayed by up to 24 hours."
                        )
                    else:
                        st.caption(f"Source: {job.get('source') or 'Unknown'}")
                    if job.get("last_verified_at"):
                        st.caption(
                            f"Last checked in source feed: {job['last_verified_at']} "
                            f"· status: {job.get('listing_status') or 'unknown'}"
                        )
                    if job.get("possible_repost_count", 1) > 1:
                        st.caption(
                            "Possible same-role repost or parallel requisition; postings are kept separate."
                        )
                    with col2:
                        st.metric("Technical match", f"{score:.0f}/100", category)

                    shift = result["evening"]
                    if shift["status"] == "confirmed_evening":
                        shift_end = f"–{shift['end_time']}" if shift.get("end_time") else ""
                        shift_kind = (
                            "Confirmed overnight"
                            if shift.get("schedule_type") == "confirmed_overnight"
                            else "Confirmed evening"
                        )
                        st.write(
                            f"**Shift:** {shift_kind}, {shift['start_time']}{shift_end} "
                            f"({shift['timezone']})"
                        )
                    else:
                        schedule_labels = {
                            "day_shift": "Day shift",
                            "rotating_shift": "Rotating shift",
                            "multiple_shift_options": "Multiple shift options",
                            "timezone_unverified": "Timezone needs verification",
                            "flexible": "Flexible schedule",
                            "unknown": "Schedule unknown",
                        }
                        if shift.get("conflict"):
                            label = "Schedule conflict"
                        elif shift.get("schedule_type") == "needs_verification":
                            label = "Evening mentioned, hours not stated"
                        else:
                            label = schedule_labels.get(shift.get("schedule_type"), "Schedule")
                        shift_hours = (
                            f" ({shift['start_time']}–{shift['end_time']})"
                            if shift.get("start_time")
                            else " (hours not stated)"
                        )
                        st.write(f"**Shift:** {label}{shift_hours} — {shift['reason']}")
                    arrangement = result.get("location_arrangement", {})
                    st.write(
                        f"**Canadian eligibility:** {result['canadian_eligibility']['reason']}"
                    )
                    st.write(
                        f"**Work arrangement:** {'Remote' if arrangement.get('remote') else 'In person / hybrid'}"
                        f" · location: {arrangement.get('location') or job.get('location') or 'not stated'}"
                        + (
                            " (within Oakville/Mississauga/Toronto area)"
                            if arrangement.get("local_area")
                            else "" if arrangement.get("remote") else " (outside preferred area)"
                        )
                    )
                    st.write(
                        f"**Hours / salary:** {job.get('employment_type') or 'Not listed'} · "
                        f"{job.get('salary') or 'Not listed'}"
                    )
                    match_skills = [
                        token.replace("Matched skills: ", "").strip()
                        for token in (job.get("match_explanation") or "").split("; ")
                        if token.startswith("Matched skills:")
                    ]
                    if match_skills:
                        st.write(f"**Main matching skills:** {match_skills[0]}")
                    status_label = opportunity_status_label(result)
                    if status_label == "Confirmed Evening":
                        st.success(
                            "CONFIRMED EVENING — all hard gates verified (schedule, Canadian eligibility, location)."
                        )
                    else:
                        st.warning(
                            f"{category} — NOT a confirmed evening opportunity. Reasons: "
                            + "; ".join(result["reasons"])
                        )
                    if job.get("match_explanation"):
                        with st.expander("Why this job is in this category"):
                            st.write("**Technical score explanation:**")
                            st.write(job["match_explanation"])
                            st.write("**Gate status (separate from technical score):**")
                            st.write(f"- Schedule: {shift['status']} — {shift['reason']}")
                            st.write(f"- Canadian eligibility: {result['canadian_eligibility']['status']} — {result['canadian_eligibility']['reason']}")
                            st.write(f"- Listing status: {result.get('listing_status') or 'unknown'}")
                            st.caption(
                                "The technical match score never overrides a failed or unknown gate. "
                                "This automated score is not a qualification decision."
                            )
                    application_for_job = applications_by_job.get(job["id"])
                    prepare_col, action_col, analysis_col = st.columns([1.5, 1, 1])
                    if job.get("job_url"):
                        posting_link_label = (
                            "View Remotive listing"
                            if (job.get("source") or "").lower() == "remotive"
                            else "View employer posting"
                        )
                        action_col.link_button(posting_link_label, job["job_url"])
                    if application_for_job:
                        if prepare_col.button(
                            "Open existing draft",
                            key=f"open_application_{job['id']}",
                        ):
                            st.session_state["application_id"] = application_for_job["id"]
                            st.session_state["review_application_selector"] = application_for_job["id"]
                            st.session_state["apps_sub"] = "Application Review"
                            st.session_state["navigation_target"] = "My Applications"
                            st.rerun()
                        if result["status"] != "rejected" and prepare_col.button(
                            "Create another version",
                            key=f"new_application_version_{job['id']}",
                        ):
                            from tracking.application_workflow import (
                                ApplicationWorkflowError,
                                prepare_application_draft,
                            )
                            try:
                                prepared = prepare_application_draft(
                                    job["id"], allow_new_version=True, tracker=tracker
                                )
                                st.session_state["application_id"] = prepared["application"]["id"]
                                st.session_state["review_application_selector"] = prepared["application"]["id"]
                                st.session_state["apps_sub"] = "Application Review"
                                st.session_state["navigation_target"] = "My Applications"
                                st.rerun()
                            except ApplicationWorkflowError as error:
                                st.error(str(error))
                    elif result["status"] != "rejected":
                        label = (
                            "Prepare Application"
                            if result["status"] == "confirmed_evening"
                            else "Prepare blocked draft"
                        )
                        if prepare_col.button(label, key=f"prepare_application_{job['id']}"):
                            from tracking.application_workflow import (
                                ApplicationWorkflowError,
                                prepare_application_draft,
                            )
                            try:
                                prepared = prepare_application_draft(job["id"], tracker=tracker)
                                st.session_state["application_id"] = prepared["application"]["id"]
                                st.session_state["review_application_selector"] = prepared["application"]["id"]
                                st.session_state["apps_sub"] = "Application Review"
                                st.session_state["navigation_target"] = "My Applications"
                                st.rerun()
                            except ApplicationWorkflowError as error:
                                st.error(str(error))
                    else:
                        prepare_col.caption("Rejected jobs cannot be prepared.")
                    if analysis_col.button("Analyze eligibility", key=f"analyze_{job['id']}"):
                        if result["status"] == "confirmed_evening":
                            analysis = matcher.unified_suitability(dict(job))
                        else:
                            analysis = {
                                "eligible": False,
                                "reason": "; ".join(result["reasons"]),
                            }
                        st.session_state[f"eligibility_analysis_{job['id']}"] = analysis
                    analysis = st.session_state.get(f"eligibility_analysis_{job['id']}")
                    if analysis:
                        if analysis.get("eligible"):
                            st.info(
                                f"Requirement signal score: {analysis.get('overall_score', 0):.0f}/100 "
                                f"({analysis.get('category')}). Review the full posting before applying."
                            )
                            if analysis.get("mandatory_gaps"):
                                st.warning("Potential gaps to verify: " + "; ".join(analysis["mandatory_gaps"]))
                            if analysis.get("requirements_requiring_review"):
                                st.caption(
                                    "Transferable / unverified requirements: "
                                    + "; ".join(analysis["requirements_requiring_review"])
                                )
                        else:
                            st.warning(f"Eligibility analysis: {analysis.get('reason')}. This is not an approval to apply.")
elif page == "Application Review":
    st.title("Application Review")
    from tracking.application_workflow import (
        ApplicationWorkflowError,
        application_readiness,
        approve_application,
        mark_manually_submitted,
        mark_submission_failed,
        regenerate_documents,
        retry_failed_submission,
        save_application_review,
        submission_capability,
    )
    from documents.resume_export import export_docx, export_pdf
    from documents.resume_manager import list_resumes

    capability = submission_capability()
    st.info(
        "Automated submission is unavailable. Employer submission credentials and an "
        "authorized submission adapter are not configured. Review, approve, then submit "
        "on the employer's website."
    )
    st.caption(capability["reason"])
    apps = tracker.get_applications()
    if not apps:
        st.info("No application drafts yet. Use Prepare Application on a job card.")
    else:
        selected_ids = [application["id"] for application in apps]
        selected_id = st.session_state.get("application_id")
        if selected_id not in selected_ids:
            selected_id = selected_ids[0]
        selected_index = selected_ids.index(selected_id)
        selected_id = st.selectbox(
            "Application draft",
            selected_ids,
            index=selected_index,
            format_func=lambda application_id: next(
                (
                    f"#{application_id} · {item.get('employer') or 'Employer'} — "
                    f"{item.get('job_title') or 'Job'} · {item.get('status') or 'Draft'}"
                    for item in apps
                    if item["id"] == application_id
                ),
                f"Application {application_id}",
            ),
            key="review_application_selector",
        )
        application = tracker.get_application(selected_id)
        job = tracker.get_job(application["job_id"]) if application else None
        if not application or not job:
            st.error("The selected application or its linked job is unavailable.")
        else:
            ready, missing, eligibility, assessment = application_readiness(application, tracker)
            st.subheader(f"{job.get('job_title') or 'Job title missing'} — {job.get('employer') or 'Employer missing'}")
            st.caption(
                f"Application #{application['id']} · Version {application.get('version_number', 1)} · "
                f"Status: {application.get('status') or 'Draft'}"
            )
            st.write(
                f"**Location:** {job.get('location') or 'Not listed'} · "
                f"**Employment:** {job.get('employment_type') or 'Not listed'} · "
                f"**Salary:** {job.get('salary') or 'Not listed'}"
            )
            employer_url = job.get("job_url") or ""
            if employer_url.startswith(("https://", "http://")):
                st.link_button("Open original employer application page", employer_url)
            else:
                st.warning("No valid employer application URL is available.")
            with st.expander("Full employer job description", expanded=False):
                st.text(job.get("description") or "No job description was supplied.")

            if eligibility["status"] == "confirmed_evening":
                st.success("Eligibility confirmed by the current posting and candidate-provided verification.")
            elif eligibility["status"] == "rejected":
                st.error("Eligibility rejected. This draft cannot be approved: " + "; ".join(eligibility["reasons"]))
            else:
                st.warning(
                    "Needs information. Application approval is blocked until the missing eligibility "
                    "details are resolved."
                )
                st.caption("Qualification analysis and document preparation do not override eligibility.")
            if eligibility.get("evening", {}).get("conflict"):
                st.error(eligibility["evening"]["reason"])
            elif eligibility.get("evening", {}).get("manual_resolution"):
                st.info(eligibility["evening"]["reason"])
            if eligibility.get("evening", {}).get("evidence_sources"):
                for evidence_item in eligibility["evening"].get("evidence_sources", []):
                    st.write(
                        f"**{evidence_item.get('source')}:** "
                        f"{evidence_item.get('value')} "
                        f"({evidence_item.get('classification')})"
                    )
                    evidence_url = evidence_item.get("source_url")
                    if evidence_url:
                        st.caption(f"Evidence source: {evidence_url}")
            resolution = application.get("schedule_resolution") or ""
            if isinstance(resolution, str):
                try:
                    resolution = json.loads(resolution)
                except json.JSONDecodeError:
                    resolution = {}
            if resolution:
                st.caption(
                    "Schedule resolution recorded from "
                    f"{resolution.get('source', 'unknown source')} at "
                    f"{resolution.get('timestamp', 'unknown time')}."
                )
            st.subheader("Qualification assessment")
            st.write(
                "**Skills match:** "
                f"{assessment.get('overall_score', 0):.0f}/100 · "
                f"{assessment.get('category', 'Not assessed')}"
            )
            if assessment.get("mandatory_gaps"):
                st.error("Mandatory qualification gaps: " + "; ".join(assessment["mandatory_gaps"]))
            requirement_rows = [
                {
                    "Requirement": item.get("requirement"),
                    "Type": item.get("requirement_type"),
                    "Candidate evidence": item.get("evidence_status"),
                    "Supporting information": item.get("supporting_evidence") or "No supporting information found",
                    "Source": item.get("evidence_source") or "None",
                }
                for item in assessment.get("requirement_assessments", [])
            ]
            if requirement_rows:
                st.dataframe(requirement_rows, hide_index=True, use_container_width=True)
            if assessment.get("requirements_requiring_review"):
                st.warning(
                    "Review evidence for: "
                    + ", ".join(assessment["requirements_requiring_review"])
                    + ". These are not treated as qualifications you lack."
                )
            elif assessment.get("reason"):
                st.caption(assessment["reason"])
            st.subheader("Application readiness")
            if ready:
                st.success("Ready for review. Your approval is still required before submission.")
            else:
                for missing_item in missing:
                    st.warning(missing_item)
                    if missing_item.startswith("Resume header needs verified information"):
                        if st.button(
                            "Update Candidate Profile",
                            key=f"profile_from_header_{selected_id}",
                        ):
                            st.session_state["navigation_target"] = "Profile"
                            st.session_state["profile_sub_target"] = "Candidate Profile"
                            st.rerun()

            resumes = list_resumes()
            resume_ids = [resume["id"] for resume in resumes]
            preferred_resume_id = application.get("resume_id")
            if preferred_resume_id not in resume_ids:
                preferred_resume_id = resume_ids[0] if resume_ids else None
            if resumes:
                selected_resume_id = st.selectbox(
                    "Original resume used for this application",
                    resume_ids,
                    index=resume_ids.index(preferred_resume_id),
                    format_func=lambda resume_id: next(
                        f"{resume.get('name', resume.get('filename'))} · {resume.get('filename')}"
                        for resume in resumes
                        if resume["id"] == resume_id
                    ),
                    key=f"regenerate_source_{selected_id}",
                )
                if st.button("Regenerate documents from selected original resume", key=f"regenerate_{selected_id}"):
                    try:
                        documents = regenerate_documents(
                            selected_id, selected_resume_id, tracker
                        )
                        answers_value = application.get("answers") or "[]"
                        save_application_review(
                            selected_id,
                            tailored_resume=documents["tailored_resume"],
                            cover_letter=documents["cover_letter"],
                            answers=answers_value,
                            eligibility_verification=application.get("eligibility_verification") or "",
                            supplied_questions=application.get("additional_questions") or "",
                            resume_id=documents["resume_id"],
                            tracker=tracker,
                        )
                        st.session_state[f"resume_text_{selected_id}"] = documents["tailored_resume"]
                        st.session_state[f"cover_letter_text_{selected_id}"] = documents["cover_letter"]
                        st.success("Resume and cover letter regenerated from the selected original resume.")
                        st.rerun()
                    except ApplicationWorkflowError as error:
                        st.error(str(error))
            else:
                st.warning("Add an original resume in Profile → Resume Manager before approval.")

            saved_answers = json.loads(application.get("answers") or "[]")
            answer_inputs = []
            with st.form(f"application_review_form_{selected_id}"):
                resume_text = st.text_area(
                    "Tailored resume (editable)",
                    value=application.get("tailored_resume") or "",
                    height=320,
                    key=f"resume_text_{selected_id}",
                )
                cover_letter_text = st.text_area(
                    "Tailored cover letter (editable)",
                    value=application.get("cover_letter") or "",
                    height=220,
                    key=f"cover_letter_text_{selected_id}",
                )
                st.markdown("#### Employer application questions")
                st.caption(
                    "Questions are extracted from the job description and any application information "
                    "you provide below. Answers not supported by the verified profile remain blank."
                )
                for index, answer in enumerate(saved_answers):
                    st.write(f"**Question:** {answer.get('question', '')}")
                    st.caption(
                        f"Question source: {answer.get('question_source', 'unknown')} · "
                        f"{'Required' if answer.get('required', True) else 'Optional'} · "
                        f"Answer source: {answer.get('source', 'unknown')} · "
                        f"Supporting information: "
                        f"{answer.get('supporting_information') or 'None found'}"
                    )
                    if answer.get("requires_review"):
                        st.warning("This answer needs your review before it can be used.")
                    answer_value = st.text_area(
                        "Suggested answer",
                        value=str(answer.get("answer") or ""),
                        key=f"answer_{selected_id}_{index}",
                    )
                    confirm_answer = st.checkbox(
                        "I reviewed and confirm this answer",
                        value=answer.get("verification") == "USER_CONFIRMED",
                        key=f"confirm_answer_{selected_id}_{index}",
                    )
                    answer_inputs.append((answer, answer_value, confirm_answer))
                supplied_questions = st.text_area(
                    "Additional employer questions or supplied application-page text",
                    value=application.get("additional_questions") or "",
                    help="The employer page is not scraped. Paste accessible question text here to extract and prepare suggested answers.",
                    key=f"question_source_{selected_id}",
                )
                eligibility_verification = st.text_area(
                    "Employer-confirmed missing eligibility details",
                    value=application.get("eligibility_verification") or "",
                    help="Only enter details you verified from the employer posting or supplied information, such as the shift start time or Canadian applicant eligibility.",
                    key=f"eligibility_evidence_{selected_id}",
                )
                schedule_inquiry_text = application.get("schedule_inquiry") or ""
                if (
                    eligibility.get("evening", {}).get("needs_schedule_verification")
                    or schedule_inquiry_text
                ):
                    st.markdown("#### Employer inquiry draft")
                    st.caption(
                        "Editable draft only. Review and copy it if useful; no message is sent."
                    )
                    schedule_inquiry_text = st.text_area(
                        "Editable schedule inquiry",
                        value=schedule_inquiry_text,
                        height=160,
                        key=f"schedule_inquiry_{selected_id}",
                    )
                resolution_values = {
                    "Unresolved": "unresolved",
                    "Employer confirmed evening hours (5 PM or later)": "confirmed_evening",
                    "Employer confirmed not evening-compatible": "incompatible",
                }
                current_resolution_value = resolution.get("value")
                resolution_label = {
                    "confirmed_evening": "Employer confirmed evening hours (5 PM or later)",
                    "incompatible": "Employer confirmed not evening-compatible",
                }.get(current_resolution_value, "Unresolved")
                selected_resolution_label = st.selectbox(
                    "Schedule conflict resolution",
                    list(resolution_values),
                    index=list(resolution_values).index(resolution_label),
                    help="Only record an explicit employer-confirmed resolution. The source and evidence are saved with a timestamp.",
                    key=f"schedule_resolution_{selected_id}",
                )
                schedule_resolution_source = st.text_input(
                    "Schedule resolution source",
                    value=str(resolution.get("source") or ""),
                    help="For example: employer email, employer phone confirmation, or corrected posting URL.",
                    key=f"schedule_resolution_source_{selected_id}",
                )
                schedule_resolution_evidence = st.text_area(
                    "Schedule resolution evidence",
                    value=str(resolution.get("evidence") or ""),
                    help="Record the exact corrected shift hours or the employer's clarification.",
                    key=f"schedule_resolution_evidence_{selected_id}",
                )
                save_review = st.form_submit_button("Save draft and answers")
            if save_review:
                edited_answers = []
                for answer, answer_value, confirmed in answer_inputs:
                    updated_answer = dict(answer)
                    updated_answer["answer"] = answer_value.strip() or None
                    if confirmed and updated_answer["answer"] is not None:
                        updated_answer["verification"] = "USER_CONFIRMED"
                    elif answer_value.strip() != str(answer.get("answer") or ""):
                        updated_answer["verification"] = "NEEDS_REVIEW"
                    edited_answers.append(updated_answer)
                try:
                    save_application_review(
                        selected_id,
                        tailored_resume=resume_text,
                        cover_letter=cover_letter_text,
                        answers=edited_answers,
                        eligibility_verification=eligibility_verification,
                        schedule_inquiry=schedule_inquiry_text,
                        schedule_resolution_value=resolution_values[
                            selected_resolution_label
                        ],
                        schedule_resolution_source=schedule_resolution_source,
                        schedule_resolution_evidence=schedule_resolution_evidence,
                        supplied_questions=supplied_questions,
                        tracker=tracker,
                    )
                    st.success("Draft, documents, and question answers saved.")
                    st.rerun()
                except ApplicationWorkflowError as error:
                    st.error(str(error))

            st.subheader("Download prepared documents")
            for label, content, extension, exporter in (
                ("Tailored resume", application.get("tailored_resume") or "", "pdf", export_pdf),
                ("Tailored resume", application.get("tailored_resume") or "", "docx", export_docx),
                ("Cover letter", application.get("cover_letter") or "", "pdf", export_pdf),
                ("Cover letter", application.get("cover_letter") or "", "docx", export_docx),
            ):
                if not content.strip():
                    continue
                document_key = f"document_{selected_id}_{label.replace(' ', '_')}_{extension}"
                filename = (
                    f"application_{selected_id}_v{application.get('version_number', 1)}_"
                    f"{label.lower().replace(' ', '_')}.{extension}"
                )
                if st.button(f"Generate {label} {extension.upper()}", key=f"export_{document_key}"):
                    try:
                        if exporter is export_pdf and label == "Tailored resume":
                            output_path = exporter(content, filename, compact=True)
                        else:
                            output_path = exporter(content, filename)
                        with open(output_path, "rb") as output_file:
                            st.session_state[document_key] = output_file.read()
                    except (OSError, ValueError) as error:
                        st.error(f"Could not export {label}: {error}")
                if document_key in st.session_state:
                    st.download_button(
                        f"Download {label} {extension.upper()}",
                        data=st.session_state[document_key],
                        file_name=filename,
                        mime="application/pdf" if extension == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        key=f"download_{document_key}",
                    )

            if application.get("status") != "Approved" and application.get("status") not in {
                "Submitted", "Manually submitted", "Submission failed"
            }:
                if st.button(
                    "Approve application",
                    disabled=not ready,
                    key=f"approve_{selected_id}",
                ):
                    try:
                        approve_application(selected_id, tracker)
                        st.success("Application approved. It has not been submitted.")
                        st.rerun()
                    except ApplicationWorkflowError as error:
                        st.error(str(error))
            elif application.get("status") == "Approved":
                st.success("Approved by you; not submitted.")

            if application.get("status") == "Approved" and ready:
                st.subheader("Manual submission")
                st.caption(
                    "Open the employer page, submit the application yourself, then record the outcome. "
                    "This app cannot verify submission without an employer confirmation."
                )
                if employer_url.startswith(("https://", "http://")):
                    st.link_button("Open employer application page", employer_url)
                with st.form(f"manual_submission_form_{selected_id}"):
                    submitted_on = st.date_input("Date submitted", value=datetime.now().date())
                    confirmation_ref = st.text_input("Confirmation/reference number (optional)")
                    follow_up = st.date_input("Follow-up date (optional)", value=None)
                    confirm_manual = st.checkbox(
                        "I submitted this application on the employer's website"
                    )
                    record_submission = st.form_submit_button("Record manual submission")
                if record_submission:
                    if not confirm_manual:
                        st.error("Confirm that you submitted it on the employer site before recording.")
                    else:
                        try:
                            mark_manually_submitted(
                                selected_id,
                                submitted_on.isoformat(),
                                confirmation_ref,
                                follow_up.isoformat() if follow_up else None,
                                tracker,
                            )
                            st.success("Manual submission recorded from your confirmation.")
                            st.rerun()
                        except ApplicationWorkflowError as error:
                            st.error(str(error))
                with st.form(f"manual_failure_form_{selected_id}"):
                    failure_details = st.text_input("Employer-page failure details (optional)")
                    confirm_failure = st.checkbox("I confirm the employer page did not accept the application")
                    record_failure = st.form_submit_button("Record submission failed")
                if record_failure:
                    if not confirm_failure:
                        st.error("Confirm the reported failure before recording it.")
                    else:
                        try:
                            mark_submission_failed(
                                selected_id, failure_details, tracker
                            )
                            st.rerun()
                        except ApplicationWorkflowError as error:
                            st.error(str(error))
            elif application.get("status") == "Approved":
                st.error(
                    "This approval no longer passes current readiness checks. "
                    "Resolve the missing information and approve again before submission."
                )
            elif application.get("status") in {"Manually submitted", "Submitted"}:
                st.success(
                    f"Submission recorded: {application.get('status')} · "
                    f"{application.get('submitted_at') or application.get('applied_at') or 'date not recorded'}"
                )
                if application.get("confirmation_ref"):
                    st.caption(f"Reference: {application['confirmation_ref']}")
            elif application.get("status") == "Submission failed":
                st.error("Submission failure was reported by the candidate; no automated submission was attempted.")
                if st.button("Return to employer page for another manual attempt", key=f"retry_manual_{selected_id}"):
                    try:
                        retry_failed_submission(selected_id, tracker)
                        st.rerun()
                    except ApplicationWorkflowError as error:
                        st.error(str(error))

            with st.expander("Application audit history"):
                events = tracker.get_application_events(selected_id)
                if events:
                    st.dataframe(
                        [
                            {
                                "Event": event["event_type"],
                                "From": event["from_status"],
                                "To": event["to_status"],
                                "Date": event["created_at"],
                                "Details": event["details"],
                            }
                            for event in events
                        ],
                        width="stretch",
                        hide_index=True,
                    )
                else:
                    st.caption("No audit events recorded.")
elif page == "My Applications":
    st.title("My Applications")
    applications = tracker.get_applications()
    if applications:
        rows = [
            {
                "Employer": item.get("employer") or "",
                "Job title": item.get("job_title") or "",
                "Application date": item.get("submitted_at") or item.get("applied_at") or "",
                "Status": item.get("status") or "Draft",
                "Resume version": item.get("resume_version") or "",
                "Cover letter version": item.get("version_number") or 1,
                "Submission method": item.get("submission_method") or "Not submitted",
                "Confirmation/reference": item.get("confirmation_ref") or "",
                "Follow-up date": item.get("follow_up_date") or "",
            }
            for item in applications
        ]
        st.dataframe(rows, width="stretch", hide_index=True)
        selected_application = st.selectbox(
            "Review an application",
            [item["id"] for item in applications],
            format_func=lambda application_id: next(
                f"#{application_id} · {item.get('employer') or 'Employer'} — "
                f"{item.get('job_title') or 'Job'} · {item.get('status') or 'Draft'}"
                for item in applications
                if item["id"] == application_id
            ),
            key="applications_review_selector",
        )
        if st.button("Open Application Review", key="open_review_from_tracker"):
            st.session_state["application_id"] = selected_application
            st.session_state["review_application_selector"] = selected_application
            st.session_state["apps_sub"] = "Application Review"
            st.rerun()
    else:
        st.info("No application drafts or submission records yet.")

elif page == "Resume Manager":
    st.title("Resume Manager")
    import os, json
    from documents.resume_parser import extract_text
    from documents.resume_manager import add_resume, list_resumes, set_default, save_parsed_json, get_parsed_json
    from documents.structured_resume_parser import parse_resume
    upload_dir = os.path.join("storage", "resumes")
    os.makedirs(upload_dir, exist_ok=True)
    # LinkedIn PDF upload
    st.subheader("Upload Resumes")
    uploaded = st.file_uploader("Upload Resume (PDF, DOCX, TXT)", type=["pdf", "docx", "txt"], accept_multiple_files=True)
    linkedin_upload = st.file_uploader("Upload LinkedIn PDF Export", type=["pdf"], accept_multiple_files=True, key="linkedin")
    if uploaded:
        for u in uploaded:
            dest = os.path.join(upload_dir, u.name)
            if os.path.exists(dest):
                st.warning(f"Duplicate file skipped: {u.name}")
                continue
            with open(dest, "wb") as f:
                f.write(u.getbuffer())
            text = extract_text(dest)
            rid = add_resume(u.name, dest, text, name=u.name)
            if text.strip():
                st.success(f"Uploaded {u.name}")
                # Auto-parse with structured parser
                parsed = parse_resume(text)
                parsed_json = json.dumps(parsed)
                save_parsed_json(rid, parsed_json)
            else:
                st.warning(f"Uploaded {u.name}, but no text extracted")
    if linkedin_upload:
        from documents.linkedin_import import import_linkedin_pdf
        for u in linkedin_upload:
            try:
                imported = import_linkedin_pdf(u.getvalue(), u.name)
                existing_resumes = list_resumes()
                if any(
                    resume.get("import_sha256") == imported["sha256"]
                    for resume in existing_resumes
                ):
                    st.warning(f"Duplicate LinkedIn PDF content skipped: {u.name}")
                    continue
                add_resume(
                    u.name,
                    imported["path"],
                    imported["text"],
                    name=u.name,
                    parsed_json=imported["parsed"],
                    import_sha256=imported["sha256"],
                )
                if imported["duplicate"]:
                    st.warning(f"Duplicate LinkedIn PDF content recognized: {u.name}")
                else:
                    st.success(f"Uploaded LinkedIn PDF: {u.name}")
            except ValueError as error:
                st.error(f"Could not import {u.name}: {error}")
    st.subheader("Stored Resumes")
    resumes = list_resumes()
    if resumes:
        for r in resumes:
            with st.expander(f"{r['name']} ({r['filename']})"):
                st.write(f"Upload date: {r['uploaded_at']}")
                st.write(f"Type: {os.path.splitext(r['filename'])[1]}")
                st.write(f"Default: {r.get('default', False)}")
                if st.button(f"Set default {r['id']}", key=f"def_{r['id']}"):
                    set_default(r['id'])
                    st.rerun()
                new_name = st.text_input("Rename", value=r['name'], key=f"rn_{r['id']}")
                if st.button("Save name", key=f"save_{r['id']}"):
                    from documents.resume_manager import rename_resume
                    if new_name.strip() and rename_resume(r['id'], new_name):
                        st.success("Renamed")
                        st.rerun()
                    else:
                        st.error("Invalid name")
                with st.form(f"del_{r['id']}"):
                    confirm = st.checkbox("Confirm delete")
                    if st.form_submit_button("Delete") and confirm:
                        try:
                            os.remove(r['path'])
                        except Exception:
                            pass
                        # remove from index
                        idx_path = os.path.join(upload_dir, "index.json")
                        if os.path.exists(idx_path):
                            data = json.load(open(idx_path))
                            data = [x for x in data if x['id'] != r['id']]
                            with open(idx_path, "w") as f:
                                json.dump(data, f, indent=2)
                        st.rerun()
                st.text_area("Extracted text", r.get('text',''), key=f"txt_{r['id']}", height=150)
                # Structured Parser Integration
                st.subheader("Structured Parser")
                parsed = get_parsed_json(r['id'])
                if parsed is None and r.get('text'):
                    parsed = parse_resume(r.get('text'))
                    save_parsed_json(r['id'], parsed)
                if parsed:
                    parsed_str = json.dumps(parsed, indent=2)
                    edited = st.text_area("Parsed JSON (editable)", parsed_str, key=f"parsed_{r['id']}", height=250)
                    colp1, colp2 = st.columns(2)
                    if colp1.button("Save Parsed JSON", key=f"saveparsed_{r['id']}"):
                        try:
                            parsed_obj = json.loads(edited)
                            save_parsed_json(r['id'], parsed_obj)
                            st.success("Parsed JSON saved")
                        except Exception as e:
                            st.error(f"Invalid JSON: {e}")
                    if colp2.button("Re-parse", key=f"reparse_{r['id']}"):
                        parsed_new = parse_resume(r.get('text',''))
                        save_parsed_json(r['id'], parsed_new)
                        st.success("Re-parsed")
                        st.rerun()
                else:
                    if st.button("Parse with Structured Parser", key=f"parse_{r['id']}"):
                        parsed_new = parse_resume(r.get('text',''))
                        save_parsed_json(r['id'], parsed_new)
                        st.rerun()
    else:
        st.info("No resumes uploaded yet.")


elif page == "Candidate Profile":
    st.title("Candidate Profile")
    import json, os
    from documents.application_documents import resume_header_details
    from documents.resume_manager import get_default
    path = "config/candidate_profile.json"
    profile = json.load(open(path)) if os.path.exists(path) else {}
    profile.setdefault("technical_interests", [])
    original_resume = get_default()
    resume_header, missing_header = resume_header_details(
        profile, original_resume.get("text", "") if original_resume else ""
    )
    if missing_header:
        st.warning(
            "Resume header information is incomplete: "
            + ", ".join(missing_header)
            + ". Add the missing verified details below."
        )
    name = st.text_input("Full name", value=resume_header["name"])
    email = st.text_input("Email", value=resume_header["email"])
    phone = st.text_input("Phone", value=resume_header["phone"])
    location = st.text_input("Location", value=resume_header["location"])
    summary = st.text_area("Professional summary", value=profile.get("career_direction",""))
    skills = st.text_area("Technical skills (comma-separated)", value=", ".join(profile.get("technical_interests",[])))
    if st.button("Save Profile", key="save_profile_main"):
        profile["name"] = name.strip()
        profile["email"] = email.strip()
        profile["phone"] = phone.strip()
        profile["location"] = location.strip()
        profile["career_direction"] = summary
        profile["technical_interests"] = [x.strip() for x in skills.split(",") if x.strip()]
        with open(path,"w") as f: json.dump(profile,f,indent=2)
        st.success("Saved")
    # LinkedIn import
    st.subheader("LinkedIn PDF Import")
    linkedin_file = st.file_uploader("Upload LinkedIn PDF Export", type=["pdf"], key="linkedin_import")
    if linkedin_file is not None:
        from documents.linkedin_import import import_linkedin_pdf
        try:
            imported = import_linkedin_pdf(linkedin_file.getvalue(), linkedin_file.name)
        except ValueError as error:
            st.error(f"LinkedIn PDF import failed: {error}")
        else:
            if imported["duplicate"]:
                st.warning("This PDF content was already imported. The existing import is shown; no duplicate is added.")
            else:
                st.success("PDF text extracted. Compare the structured import before approving any profile change.")
            st.text_area("Extracted PDF text", imported["text"], height=200)
            st.subheader("Structured imported information")
            st.json(imported["parsed"])
            from documents.profile_compare import compare_structured
            comparison = compare_structured(profile, imported["parsed"])
            st.subheader("Compare with current Candidate Profile")
            st.write("**Skills in both:**", comparison["skills"]["in_both"])
            st.write("**Skills only in current profile:**", comparison["skills"]["only_in_profile"])
            st.write("**Skills only in import:**", comparison["skills"]["only_in_import"])
            st.write("**Current education:**", comparison["education"]["profile"] or "Not listed")
            st.write("**Imported education:**", comparison["education"]["imported"] or "Not detected")
            st.write("**Current experience years:**", comparison["experience"]["profile_years"] or "Not listed")
            st.write("**Imported experience:**", comparison["experience"]["imported"] or "Not detected")
            st.write("**Current certifications:**", comparison["certifications"]["profile"] or "Not listed")
            st.write("**Imported certifications:**", comparison["certifications"]["imported"] or "Not detected")
            st.caption(
                "The import never overwrites your profile automatically. Review and approve each "
                "supported skill suggestion below; experience, education, and certification changes "
                "are not applied automatically."
            )
            from documents.profile_suggestions import create_suggestions, list_suggestions, set_status, apply_approved
            create_suggestions(
                profile, imported["text"], f"linkedin:{imported['sha256']}"
            )
            for sug in list_suggestions():
                with st.expander(f"{sug['category']}: {sug['proposed']}"):
                    st.write("Status:", sug["status"])
                    st.write("Evidence:", sug.get("evidence", ""))
                    c1,c2,c3 = st.columns(3)
                    if c1.button("Approve", key=f"li_ap_{sug['id']}"):
                        set_status(sug['id'], "approved"); st.rerun()
                    if c2.button("Reject", key=f"li_rj_{sug['id']}"):
                        set_status(sug['id'], "rejected"); st.rerun()
                    if c3.button("Pending", key=f"li_pd_{sug['id']}"):
                        set_status(sug['id'], "pending"); st.rerun()
            if st.button("Apply approved changes", key="li_apply"):
                apply_approved(path)
                st.success("Explicitly approved profile suggestions applied.")
elif page == "Job Bank Import":
    st.title("Job Bank Import (Monthly Dataset)")
    import csv, io, os, hashlib, datetime
    from database.db import get_conn
    uploaded = st.file_uploader("Upload Job Bank CSV", type=["csv"])
    if uploaded is not None:
        content = uploaded.read().decode("utf-8", errors="ignore")
        reader = csv.DictReader(io.StringIO(content))
        rows = list(reader)
        st.write(f"Rows: {len(rows)}")
        if st.button("Import", key="import_jobbank"):
            conn = get_conn()
            cur = conn.cursor()
            inserted = 0
            skipped = 0
            invalid = 0
            for r in rows:
                title = (r.get("Job Title") or r.get("job_title") or "").strip()
                city = (r.get("City") or r.get("city") or "").strip()
                prov = (r.get("Province/Territory") or r.get("province") or "").strip()
                loc = f"{city}, {prov}".strip(", ")
                noc = (r.get("NOC") or r.get("noc") or "").strip()
                if not title:
                    invalid += 1
                    continue
                h = hashlib.sha256(f"{title}|{loc}|{noc}".encode()).hexdigest()
                try:
                    cur.execute("INSERT INTO jobbank_imports (title, location, noc, record_hash, imported_at, dataset_month, dataset_publication_date, original_filename) VALUES (?,?,?,?,?,?,?,?)",
                                (title, loc, noc, h, datetime.datetime.now().isoformat(), "unknown", None, uploaded.name))
                    inserted += 1
                except Exception:
                    skipped += 1
            conn.commit()
            conn.close()
            st.success(f"Imported {inserted}, duplicates {skipped}, invalid {invalid}")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM jobbank_imports")
    st.write(f"Stored Job Bank rows: {cur.fetchone()[0]}")
    cur.execute("SELECT dataset_publication_date, imported_at, original_filename, COUNT(*) FROM jobbank_imports GROUP BY dataset_publication_date, imported_at, original_filename")
    for r in cur.fetchall():
        st.write(f"Publication date: {r[0] or 'Not provided'} | Imported: {r[1]} | File: {r[2] or 'unknown'} | Rows: {r[3]}")
    conn.close()
    st.warning("Monthly dataset records are not live vacancies.")

elif page == "Help":
    st.title("Help")
    st.write("Recommended Jobs applies strict eligibility checks. Canadian applicant eligibility and a shift start at or after 5:00 PM Toronto time must be confirmed; unknown details remain blocked for review.")
    st.write("Profile and Resume Manager: upload original resumes, extract LinkedIn PDF text, compare structured fields, and explicitly approve supported profile suggestions.")
    st.write("Prepare Application creates a persistent, versioned draft. Application Review includes eligibility and qualification gates, editable tailored documents, question answers with supporting information, PDF/DOCX exports, and an audit history.")
    st.write("Automated employer submission is not configured. Approve an application, submit manually on the employer's website, and record the self-reported date and confirmation in My Applications.")
    _help = True
elif page == "Manual Job Intake":
    st.title("Manual Job Intake")
    title = st.text_input("Job title (required)")
    employer = st.text_input("Employer (required)")
    url = st.text_input("Official job posting URL (required)")
    desc = st.text_area("Full job description (required)")
    location = st.text_input("Location")
    emp_type = st.text_input("Employment type")
    shift_hours = st.text_input("Shift hours (optional)")
    education = st.text_input("Required education (optional)")
    if st.button("Add Job", key="add_manual_job"):
        if not title or not employer or not url or not desc or len(desc) < 20:
            st.error("Missing required fields or description too short")
        else:
            from tracking.application_tracker import ApplicationTracker
            from urllib.parse import urlparse
            parsed = urlparse(url)
            if parsed.scheme not in ("http","https") or not parsed.netloc:
                st.error("Invalid URL")
            else:
                tracker = ApplicationTracker()
                job = {
                    "employer": employer,
                    "job_title": title,
                    "job_url": url,
                    "source": "manual",
                    "description": desc,
                    "location": location,
                    "remote": "remote" in location.lower(),
                    "employment_type": emp_type,
                    "shift": shift_hours,
                    "education_required": education,
                    "schedule_classification": {"schedule_type": "unknown"},
                }
                inserted = tracker.add_job(job)
                if inserted:
                    st.success(f"Added job {inserted}: {title} at {employer}. Saved. Assessing...")
                    try:
                        job['id'] = inserted
                        match_res = matcher.score_job(job)
                        matcher.save_match(inserted, match_res)
                        from agents.job_classifier import classify_evening_eligibility, classify_job
                        ee = classify_evening_eligibility(job)
                        cj = classify_job(job, matcher.load_profile())
                        us = matcher.unified_suitability(job)
                        st.write(f"Evening: {ee['status']} ({ee.get('evidence')})")
                        st.write(f"Canadian: {cj['canadian_eligibility']['status']}")
                        st.write(f"Skills: {us.get('skills_score')} Education: {us.get('education_score')}")
                        st.write(f"Overall: {us.get('overall_score')} {us.get('category')}")
                        if us.get('mandatory_gaps'):
                            st.error("Mandatory gaps: " + "; ".join(us['mandatory_gaps']))
                        st.info("Go to Recommended Jobs to view full assessment.")
                    except Exception as e:
                        st.error(f"Assessment failed: {e}")
                else:
                    st.warning("Duplicate or invalid job")
    st.info("Manually imported jobs appear in Recommended Jobs with source 'manual'.")


elif page == "Settings":
    st.title("Settings")
    import json, os
    path = "config/candidate_profile.json"
    profile = json.load(open(path)) if os.path.exists(path) else {}
    profile.setdefault("technical_interests", [])
    profile.setdefault("availability", {})
    st.subheader("Job Preferences")
    locations = st.text_input("Preferred locations", value=profile.get("location",""))
    remote = st.checkbox("Canada-wide remote preferred", value=str(profile.get("preferred_arrangement","")).lower().startswith("remote"))
    evening = st.checkbox("Evening availability", value=profile.get("availability",{}).get("weekdays_after","18:00") >= "18:00")
    weekend = st.checkbox("Weekend availability", value=profile.get("availability",{}).get("weekends", True))
    hours = st.text_input("Desired weekly hours", value=",".join(str(x) for x in profile.get("desired_hours_per_week",[20,25])))
    langs = st.text_input("Languages", value=profile.get("language","English"))
    french = st.checkbox("French required acceptable", value=profile.get("french_required", False))
    if st.button("Save Settings", key="save_settings"):
        profile["location"] = locations
        profile["preferred_arrangement"] = "Fully remote" if remote else profile.get("preferred_arrangement","")
        profile["availability"]["weekends"] = weekend
        profile["language"] = langs
        profile["french_required"] = french
        try:
            profile["desired_hours_per_week"] = [int(x.strip()) for x in hours.split(",") if x.strip()]
        except Exception:
            pass
        with open(path, "w") as f:
            json.dump(profile, f, indent=2)
        st.success("Saved")
    st.subheader("AI Matching")
    st.write(f"AI enabled: {os.getenv('ALLOW_AI_MATCHING','false')}")
    st.write(f"API key configured: {bool(os.getenv('OPENAI_API_KEY',''))}")
    st.info("Set ALLOW_AI_MATCHING=true and OPENAI_API_KEY in .env")

# Additional imports for Stage 1 features
from documents.structured_resume_parser import parse_resume as parse_resume_structured, parse_to_json
from documents import profile_compare
from documents import resume_manager as rm
import json as _json
