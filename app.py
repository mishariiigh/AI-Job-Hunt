import streamlit as st
import pandas as pd
import json
from database.db import get_conn
from tracking.application_tracker import ApplicationTracker
from agents.discovery_agent import DiscoveryAgent
from agents.matching_agent import MatchingAgent
from config.source_config import load_sources, save_sources
from sources.validator import SourceValidator
from datetime import datetime

st.set_page_config(page_title="AI Job Hunter", layout="wide")

tracker = ApplicationTracker()
discovery = DiscoveryAgent()
validator = SourceValidator()
matcher = MatchingAgent()

st.sidebar.title("AI Job Hunter")
page = st.sidebar.radio(
    "Navigation",
    ["Dashboard", "Discover Jobs", "Recommended Jobs", "Application Review", "My Applications", "Resume Manager", "Candidate Profile", "Settings"]
)

def get_jobs_df():
    jobs = tracker.get_jobs()
    if not jobs:
        return pd.DataFrame()
    return pd.DataFrame(jobs)


if page == "Dashboard":
    st.title("Dashboard")
    df = get_jobs_df()
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Total Jobs", len(df))
    col2.metric("Remote", len(df[df['remote'] == 1]) if not df.empty else 0)
    col3.metric("Evening/Flex", len(df) if not df.empty else 0)
    col4.metric("Matched", len(df[df['match_score'] >= 55]) if not df.empty and 'match_score' in df else 0)
    col5.metric("Awaiting Approval", len(df[df['status'] == 'pending_approval']) if not df.empty and 'status' in df else 0)
    col6.metric("Submitted", len(df[df['status'] == 'applied']) if not df.empty and 'status' in df else 0)
    st.subheader("Recent Jobs")
    if df.empty:
        st.info("No jobs discovered yet.")
    else:
        display_cols = ['job_title', 'employer', 'location', 'remote', 'salary', 'source', 'match_score']
        st.dataframe(df[display_cols].head(10), width="stretch")

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
elif page == "Recommended Jobs":
    st.title("Recommended Jobs")
    df = get_jobs_df()
    if df.empty:
        st.info("No jobs yet.")
    else:
        col1, col2 = st.columns(2)
        if col1.button("Recalculate All Matches"):
            with st.spinner("Calculating..."):
                for _, job in df.iterrows():
                    match_res = matcher.score_job(dict(job))
                    matcher.save_match(job['id'], match_res)
                st.success("Matches recalculated")
                st.rerun()
        if col2.button("Recalculate for Changed Profile"):
            st.info("Profile loaded from config/candidate_profile.json")
        with st.expander("Filters"):
            c1, c2, c3 = st.columns(3)
            min_score = c1.slider("Min match score", 0, 100, 0)
            cat_filter = c2.selectbox("Category", ["All", "Excellent match", "Strong match", "Possible match", "Weak match"])
            src_filter = c3.selectbox("Source", ["All"] + list(df['source'].unique()) if 'source' in df else ["All"])
        df_sorted = df.copy()
        if 'match_score' in df_sorted:
            df_sorted = df_sorted.sort_values('match_score', ascending=False)
        df_sorted = df_sorted[df_sorted['match_score'] >= min_score]
        for _, job in df_sorted.iterrows():
            match = matcher.get_match(job['id'])
            category = match['match_category'] if match else job.get('match_category', 'Unknown')
            if cat_filter != "All" and category != cat_filter:
                continue
            if src_filter != "All" and job.get('source') != src_filter:
                continue
            with st.expander(f"{job['job_title']} at {job['employer']} | Score: {job.get('match_score', 0):.0f}% | {category}"):
                col1, col2 = st.columns(2)
                col1.write(f"**Location:** {job['location']}")
                col1.write(f"**Remote:** {'Yes' if job['remote'] else 'No'}")
                col1.write(f"**Salary:** {job.get('salary') or 'Unknown'}")
                col1.write(f"**Employment:** {job.get('employment_type') or 'Unknown'}")
                col2.write(f"**Source:** {job['source']}")
                col2.write(f"**Shift:** {job.get('shift')}")
                sched = job.get('schedule_classification') or {}
                col2.write(f"**Schedule:** {sched.get('schedule_type', 'unknown')}")
                col2.write(f"**[Original URL]({job['job_url']})**")
                if match:
                    st.write(f"**Explanation:** {match['explanation']}")
                    rm = json.loads(match['required_matched']) if match['required_matched'] else []
                    miss = json.loads(match['missing_qualifications']) if match['missing_qualifications'] else []
                    hd = json.loads(match['hard_disqualifiers']) if match['hard_disqualifiers'] else []
                    if rm: st.write(f"**Matched:** {', '.join(rm)}")
                    if miss: st.write(f"**Missing:** {', '.join(miss)}")
                    if hd: st.error(f"**Hard disqualifiers:** {', '.join(hd)}")
                st.write("**Description:**")
                st.write((job.get('description','')[:400]) + "...")

elif page == "Application Review":
    st.title("Application Review")
    from tracking.application_tracker import ApplicationTracker
    tracker = ApplicationTracker()
    apps = tracker.get_applications()
    if not apps:
        st.info("No applications yet.")
    for app in apps:
        with st.expander(f"Application {app['id']}"):
            st.write(f"Job ID: {app.get('job_id')}")
            status = st.selectbox("Status", ["Discovered","Interested","Preparing","Awaiting review","Approved for submission","Submitted","Interview","Rejected","Withdrawn"], index=0, key=f"status_{app['id']}")
            if st.button("Update status", key=f"upd_{app['id']}"):
                conn = __import__("database.db", fromlist=["get_conn"]).get_conn()
                cur = conn.cursor()
                cur.execute("UPDATE applications SET status = ? WHERE id = ?", (status, app['id']))
                conn.commit()
                conn.close()
                st.success("Updated")
            cl = st.text_area("Cover letter", value=app.get("cover_letter") or "", key=f"cl_{app['id']}")
            if st.button("Save cover letter", key=f"savecl_{app['id']}"):
                ApplicationTracker().set_cover_letter(app['id'], cl)
                st.success("Saved")
            st.info("Open the original employer application page manually to submit.")
    st.info("Approval required per job. No auto-submit.")
elif page == "My Applications":
    st.title("My Applications")
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM applications ORDER BY id DESC", conn)
    conn.close()
    st.dataframe(df if not df.empty else pd.DataFrame())

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
    all_uploads = []
    if uploaded:
        all_uploads.extend(uploaded)
    if linkedin_upload:
        all_uploads.extend(linkedin_upload)
    if all_uploads:
        for u in all_uploads:
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
    path = "config/candidate_profile.json"
    profile = json.load(open(path)) if os.path.exists(path) else {}
    profile.setdefault("technical_interests", [])
    # Profile Comparison UI with approval persistence
    st.subheader("Profile Editor")
    summary = st.text_area("Professional summary", value=profile.get("career_direction",""))
    skills = st.text_area("Technical skills (comma-separated)", value=", ".join(profile.get("technical_interests",[])))
    if st.button("Save Profile", key="save_profile_main"):
        profile["career_direction"] = summary
        profile["technical_interests"] = [x.strip() for x in skills.split(",") if x.strip()]
        with open(path,"w") as f: json.dump(profile,f,indent=2)
        st.success("Saved")
    st.subheader("Resume Comparison")
    from documents.resume_manager import list_resumes
    from documents.profile_suggestions import create_suggestions, list_suggestions, set_status, apply_approved
    from documents import profile_compare
    resumes = list_resumes()
    if resumes:
        names = [r["name"] for r in resumes]
        sel = st.selectbox("Resume to compare", names)
        r = next(x for x in resumes if x["name"] == sel)
        colc1, colc2 = st.columns(2)
        if colc1.button("Compare"):
            create_suggestions(profile, r.get("text",""), r["name"])
        if colc2.button("Compare with Structured Parser"):
            parsed = r.get('parsed_json')
            if parsed:
                if isinstance(parsed, str):
                    try:
                        parsed = json.loads(parsed)
                    except Exception:
                        pass
            res = profile_compare.compare(profile, r.get("text",""))
            st.json(res)
        for sug in list_suggestions():
            with st.expander(f"{sug['category']}: {sug.get('proposed','')} | Status: {sug['status']}"):
                st.write("Existing:", sug.get("existing",""))
                st.write("Proposed:", sug["proposed"])
                st.write("Evidence:", sug.get("evidence",""))
                st.write("Resume:", sug.get("resume",""))
                st.write("Status:", sug["status"])
                c1,c2,c3 = st.columns(3)
                if c1.button("Approve", key=f"ap_{sug['id']}"):
                    set_status(sug["id"], "approved")
                    st.success("Approved")
                    st.rerun()
                if c2.button("Reject", key=f"rj_{sug['id']}"):
                    set_status(sug["id"], "rejected")
                    st.success("Rejected")
                    st.rerun()
                if c3.button("Leave pending", key=f"pd_{sug['id']}"):
                    set_status(sug["id"], "pending")
                    st.rerun()
        if st.button("Apply approved changes (persist)", key="apply_approved"):
            changed = apply_approved(path)
            if changed:
                st.success("Applied approved changes and persisted to profile")
            else:
                st.info("No approved changes to apply")
            st.rerun()
    else:
        st.info("No resumes available for comparison")

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
