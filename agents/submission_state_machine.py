VALID = {
 "DISCOVERED": {"QUALIFIED","CANCELLED"},
 "QUALIFIED": {"PREPARING","CANCELLED"},
 "PREPARING": {"READY","REQUIRES_HUMAN_ACTION","FAILED","CANCELLED"},
 "READY": {"SUBMITTING","CANCELLED"},
 "SUBMITTING": {"SUBMITTED","FAILED","REQUIRES_HUMAN_ACTION"},
 "SUBMITTED": {"CONFIRMATION_PENDING","CONFIRMED","FAILED"},
 "CONFIRMATION_PENDING": {"CONFIRMED","FAILED","REQUIRES_HUMAN_ACTION"},
 "CONFIRMED": set(),
 "FAILED": {"PREPARING","CANCELLED"},
 "REQUIRES_HUMAN_ACTION": {"PREPARING","CANCELLED"},
 "CANCELLED": set(),
}

def can_transition(src, dst):
    return dst in VALID.get(src, set())

def transition(src, dst):
    if not can_transition(src, dst):
        raise ValueError(f"invalid transition {src}->{dst}")
    return dst

def eligibility_gate(job, profile, answers, docs_ready, job_open, already_submitted):
    if already_submitted: return False, "already submitted"
    if not job_open: return False, "job closed"
    if not docs_ready: return False, "docs missing"
    # Canadian remote
    if not (job.get("remote") and job.get("canada_eligible")): return False, "not canada remote"
    # evening shift
    if not job.get("evening_confirmed"): return False, "evening unknown"
    if job.get("shift_start_hour", 0) < 17: return False, "shift before 5pm"
    if job.get("french_required"): return False, "french required"
    # mandatory qualifications
    if not job.get("qualifications_met"): return False, "qualifications not met"
    # required answers verified
    for a in answers:
        if a.get("required") and a.get("verification") not in ("VERIFIED","USER_CONFIRMED"):
            return False, "unresolved required answer"
    return True, "ok"

import threading
_locks = {}
def acquire_lock(key):
    _locks.setdefault(key, threading.Lock())
    return _locks[key].acquire(blocking=False)
def release_lock(key):
    if key in _locks:
        try: _locks[key].release()
        except RuntimeError: pass
