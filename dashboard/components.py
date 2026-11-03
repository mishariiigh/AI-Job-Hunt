import streamlit as st


def show_stats(jobs_df):
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Jobs Discovered", len(jobs_df))
    col2.metric("Matches", len(jobs_df[jobs_df['match_score'] >= 60]) if 'match_score' in jobs_df else 0)
    col3.metric("Awaiting Approval", len(jobs_df[jobs_df['status'] == 'pending_approval']) if 'status' in jobs_df else 0)
    col4.metric("Applied", len(jobs_df[jobs_df['status'] == 'applied']) if 'status' in jobs_df else 0)
