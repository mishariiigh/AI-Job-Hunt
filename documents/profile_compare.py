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


def compare_structured(profile, parsed):
    profile_skills = profile.get("technical_interests", []) or []
    imported_skills = parsed.get("skills", []) or []
    profile_by_key = {str(skill).strip().casefold(): skill for skill in profile_skills}
    imported_by_key = {str(skill).strip().casefold(): skill for skill in imported_skills}
    common = profile_by_key.keys() & imported_by_key.keys()
    profile_education = str(profile.get("education") or "").strip()
    imported_education = parsed.get("education", []) or []
    imported_education_text = [
        item.get("description") or item.get("institution") or ""
        for item in imported_education
    ]
    return {
        "skills": {
            "in_both": [profile_by_key[key] for key in sorted(common)],
            "only_in_profile": [
                profile_by_key[key] for key in sorted(profile_by_key.keys() - common)
            ],
            "only_in_import": [
                imported_by_key[key] for key in sorted(imported_by_key.keys() - common)
            ],
        },
        "experience": {
            "profile_years": profile.get("experience_years"),
            "profile_history": profile.get("experience", []),
            "imported": parsed.get("experience", []) or [],
        },
        "education": {
            "profile": profile_education,
            "imported": imported_education_text,
            "appears_in_import": bool(
                profile_education
                and any(
                    profile_education.casefold() in item.casefold()
                    or item.casefold() in profile_education.casefold()
                    for item in imported_education_text
                    if item
                )
            ),
        },
        "certifications": {
            "profile": profile.get("certifications", []) or [],
            "imported": parsed.get("certifications", []) or [],
        },
    }
