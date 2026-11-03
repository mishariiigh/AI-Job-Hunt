import os, json, uuid

PATH = os.path.join("storage", "profile_suggestions.json")

def _load():
    if os.path.exists(PATH):
        try:
            return json.load(open(PATH))
        except Exception:
            return []
    return []

def _save(items):
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    with open(PATH, "w") as f:
        json.dump(items, f, indent=2)

def create_suggestions(profile, resume_text, resume_name):
    items = []
    text = resume_text or ""
    tlow = text.lower()
    # skill suggestions: profile skills not found? propose skills found in resume not in profile
    existing_skills = [s.lower() for s in profile.get("technical_interests", [])]
    for skill in ["Python","SQL","Java","JavaScript","Azure","React"]:
        if skill.lower() in tlow and skill.lower() not in existing_skills:
            items.append({"id": str(uuid.uuid4()), "category": "skill", "existing": "", "proposed": skill,
                          "evidence": skill, "resume": resume_name, "status": "pending", "applied": False})
    # conflict example: job title
    # store
    _save(items)
    return items

def list_suggestions():
    return _load()

def set_status(sid, status):
    items = _load()
    for it in items:
        if it["id"] == sid:
            it["status"] = status
    _save(items)

def apply_approved(profile_path):
    items = _load()
    profile = json.load(open(profile_path)) if os.path.exists(profile_path) else {}
    changed = False
    for it in items:
        if it["status"] == "approved" and not it.get("applied"):
            if it["category"] == "skill":
                profile.setdefault("technical_interests", [])
                if it["proposed"] not in profile["technical_interests"]:
                    profile["technical_interests"].append(it["proposed"])
                    changed = True
            it["applied"] = True
    if changed:
        with open(profile_path, "w") as f:
            json.dump(profile, f, indent=2)
    _save(items)
    return changed


def detect_conflicts(profile, resume_text):
    conflicts = []
    text = (resume_text or "").lower()
    # skill alias normalization simple
    for s in profile.get("technical_interests", []):
        if s.lower() not in text:
            conflicts.append({"category": "skill_missing_in_resume", "existing": s, "proposed": "", "status": "needs_review"})
    # employer/title not parsed; mark manual review
    conflicts.append({"category": "manual_review", "existing": "profile", "proposed": "resume", "status": "needs_review"})
    return conflicts
