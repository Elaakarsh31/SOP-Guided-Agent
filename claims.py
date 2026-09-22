"""Find which claim the caller is asking about.

Pure Python. The LLM supplies hints from messy speech; this file decides
which claim they point to, or reports that it cannot tell yet.
"""

import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "insurance_claims" /"fixtures"

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}


def load_claims():
    with open(FIXTURES / "claims.json") as f:
        return json.load(f)


def claims_for(party_id):
    """Every claim belonging to one person, newest first."""
    rows = [c for c in load_claims() if c["party_id"] == party_id]
    return sorted(rows, key=lambda c: c["created_at"], reverse=True)


def _period_matches(created_at, period):
    """created_at is YYYY-MM-DD. period may be '2026-01', 'january', or None."""
    if not period:
        return True
    p = str(period).strip().lower()

    if len(p) == 7 and p[4] == "-":           # '2026-01'
        return created_at.startswith(p)

    month = MONTHS.get(p)
    if month:                                  # month name, year unknown
        return int(created_at[5:7]) == month

    if p.isdigit() and len(p) == 4:            # '2026'
        return created_at.startswith(p)

    return True                                # unparseable, ignore it


def find(party_id, hints):
    """Narrow this person's claims using whatever the caller told us.

    hints keys, all optional: case_id, case_type, status, period.

    Returns (matches, used) -- the surviving claims and which hints
    actually did the narrowing.
    """
    rows = claims_for(party_id)
    used = []

    if hints.get("case_id"):
        exact = [c for c in rows if c["case_id"].lower() == hints["case_id"].lower()]
        if exact:
            return exact, ["case_id"]

    if hints.get("case_type"):
        narrowed = [c for c in rows if c["case_type"] == hints["case_type"]]
        if narrowed:
            rows, _ = narrowed, used.append("case_type")

    if hints.get("status"):
        narrowed = [c for c in rows if c["status"] == hints["status"]]
        if narrowed:
            rows, _ = narrowed, used.append("status")

    if hints.get("period"):
        narrowed = [c for c in rows if _period_matches(c["created_at"], hints["period"])]
        if narrowed:
            rows, _ = narrowed, used.append("period")

    return rows, used


def get(case_id):
    """One claim by id, or None."""
    if not case_id:
        return None
    for c in load_claims():
        if c["case_id"].lower() == str(case_id).lower():
            return c
    return None


def summary_view(claim):
    """The safe subset for disambiguation.

    No denial_reason, no amounts, no documents_needed. Those belong to
    PROCESS_CASE, after the caller has picked a claim.
    """
    return {
        "case_id": claim["case_id"],
        "case_type": claim["case_type"],
        "status": claim["status"],
        "created_at": claim["created_at"],
    }


def contradicts(request, case_id):

    claim = get(case_id)
    if not claim:
        return False

    wanted_id = request.get("case_id")
    if wanted_id and str(wanted_id).upper() != claim["case_id"].upper():
        return True

    if request.get("case_type") and request["case_type"] != claim["case_type"]:
        return True

    if request.get("status") and request["status"] != claim["status"]:
        return True

    return False