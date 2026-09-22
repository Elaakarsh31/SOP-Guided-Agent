"""Works out which claim the caller is asking about."""

from fixtures import load

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}


def load_claims():
    return load("claims.json")


def claims_for(party_id):
    """Every claim belonging to one person, newest first."""
    rows = [c for c in load_claims() if c["party_id"] == party_id]
    return sorted(rows, key=lambda c: c["created_at"], reverse=True)


def _period_matches(created_at, period):
    """Test a YYYY-MM-DD date against a period such as '2026-01' or 'january'.

    Anything unparseable counts as no constraint.
    """
    if not period:
        return True
    p = str(period).strip().lower()

    if len(p) == 7 and p[4] == "-":
        return created_at.startswith(p)
    if p.isdigit() and len(p) == 4:
        return created_at.startswith(p)
    if p in MONTHS:
        return int(created_at[5:7]) == MONTHS[p]
    return True


FILTERS = [
    ("case_type", lambda claim, want: claim["case_type"] == want),
    ("status", lambda claim, want: claim["status"] == want),
    ("period", lambda claim, want: _period_matches(claim["created_at"], want)),
]


def find(party_id, hints):
    """Narrow this person's claims by case_id, case_type, status and period.

    A hint that would leave nothing is skipped instead of applied, so a
    misremembered month still returns the caller's claims. Returns the
    surviving claims and the hints that actually narrowed them.
    """
    rows = claims_for(party_id)

    if hints.get("case_id"):
        wanted = str(hints["case_id"]).lower()
        exact = [c for c in rows if c["case_id"].lower() == wanted]
        if exact:
            return exact, ["case_id"]

    used = []
    for key, keep in FILTERS:
        want = hints.get(key)
        if not want:
            continue
        narrowed = [c for c in rows if keep(c, want)]
        if narrowed:
            rows = narrowed
            used.append(key)

    return rows, used


def get(case_id):
    """One claim by id, or None."""
    if not case_id:
        return None
    wanted = str(case_id).lower()
    for c in load_claims():
        if c["case_id"].lower() == wanted:
            return c
    return None


def summary_view(claim):
    """The fields safe to read out while the caller is still choosing a claim.

    Denial reasons, amounts and outstanding documents belong to PROCESS_CASE.
    """
    return {
        "case_id": claim["case_id"],
        "case_type": claim["case_type"],
        "status": claim["status"],
        "created_at": claim["created_at"],
    }


def contradicts(request, case_id):
    """True if this turn describes a claim other than the one pinned.

    Catches the implicit switch, where "my auto claim" names a type that
    does not belong to the claim under discussion.
    """
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
