"""Representative authorisation and policyholder consent.

There is no consent service in this demo, so poll() replays a scripted
sequence of replies from a fixture.
"""

import os

from fixtures import load

MAX_POLLS = 4


def load_representatives():
    return load("representatives.json")


def load_scenarios():
    return load("consent_scenarios.json")


def _norm(name):
    """Fold case and whitespace so spoken names compare cleanly."""
    return " ".join(str(name or "").lower().split())


def authorized(rep_name, party_id):
    """Return the representative's record, or None if they are not on the policy."""
    if not rep_name or not party_id:
        return None

    for row in load_representatives():
        if (_norm(row["rep_name"]) == _norm(rep_name)
                and row["buyer_party_id"] == party_id):
            return row
    return None


def poll(poll_count, scenario=None):
    """Return the consent status: pending, approved, denied or timeout.

    poll_count is how many times we have already asked. SOP_CONSENT_SCENARIO
    selects which script to replay.
    """
    scenario = scenario or os.getenv("SOP_CONSENT_SCENARIO", "default")
    scenarios = load_scenarios()
    sequence = scenarios.get(scenario, scenarios["default"])["status_sequence"]

    if poll_count >= MAX_POLLS:
        return "timeout"
    if poll_count < len(sequence):
        return sequence[poll_count]
    return "pending"
