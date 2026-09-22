import json
from pathlib import Path
import os 

FIXTURES = Path(__file__).parent / "insurance_claims" / "fixtures"
MAX_POLLS = 4

def load_representatives():
    with open(FIXTURES / "representatives.json") as f:
        return json.load(f)

def load_scenarios():
    with open(FIXTURES / "consent_scenarios.json") as f:
        return json.load(f)

def _norm(name):
    return " ".join(str(name or "").lower().split())

def authorized(rep_name, party_id):
    if not rep_name or not party_id:
        return None

    for row in load_representatives():
        if (_norm(row['rep_name']) == _norm(rep_name) and row['buyer_party_id'] == party_id):
            return row

    return None

def poll(poll_count, scenario=None):
    """Ask the consent system for the current status.
 
    Returns 'approved', 'pending', 'timeout', or 'denied'.
    """
    scenario = scenario or os.getenv("SOP_CONSENT_SCENARIO", "default")
    scenarios = load_scenarios()
    sequence = scenarios.get(scenario, scenarios["default"])["status_sequence"]
 
    if poll_count >= MAX_POLLS:
        return "timeout"
 
    if poll_count < len(sequence):
        return sequence[poll_count]
 
    return "pending"