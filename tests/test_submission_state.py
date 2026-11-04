from agents.submission_state_machine import can_transition, transition, eligibility_gate, acquire_lock, release_lock

def test_valid_transitions():
    assert can_transition("DISCOVERED","QUALIFIED")
    assert can_transition("READY","SUBMITTING")

def test_invalid_transition():
    try:
        transition("CONFIRMED","SUBMITTING")
        assert False
    except ValueError:
        pass

def test_eligibility_gate_blocks_unknown():
    job={"remote":True,"canada_eligible":True,"evening_confirmed":False,"shift_start_hour":18,"french_required":False,"qualifications_met":True}
    ok, reason = eligibility_gate(job, {}, [], True, True, False)
    assert not ok

def test_eligibility_passes():
    job={"remote":True,"canada_eligible":True,"evening_confirmed":True,"shift_start_hour":18,"french_required":False,"qualifications_met":True}
    ok, reason = eligibility_gate(job, {}, [{"required":True,"verification":"VERIFIED"}], True, True, False)
    assert ok

def test_duplicate_lock():
    assert acquire_lock("k1") is True
    assert acquire_lock("k1") is False
    release_lock("k1")
