def compare(profile, resume_text):
    text = (resume_text or "").lower()
    skills = profile.get("technical_interests", [])
    missing_in_profile = [s for s in skills if s.lower() not in text]  # not meaningful
    # skills in resume not in profile: simple token check
    profile_skills = set(s.lower() for s in skills)
    resume_tokens = set(text.split())
    missing_in_resume = [s for s in skills if s.lower() not in resume_tokens]
    return {
        "in_both": [s for s in skills if s.lower() in text],
        "missing_in_profile": [],
        "missing_in_resume": missing_in_resume,
        "conflicts": [],
    }
