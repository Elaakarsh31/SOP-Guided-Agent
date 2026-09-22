"""Check what the caller told us against the policyholder records."""

import json
import re
from pathlib import Path

FIXTURES = Path(__file__).parent / "insurance_claims" /"fixtures"

# Fields that count toward the 3-field requirement.
# policy_number is not here on purpose: it is printed on every letter,
# so it proves nothing about who is calling.
FIELDS = ["full_name", "dob", "phone", "email", "id_last4"]
REQUIRED = 3


def load_people():
    with open(FIXTURES / "policyholders.json") as f:
        return json.load(f)


def clean(field, value):
    """Make a value comparable. Returns None if it is unusable."""
    if not value:
        return None
    v = str(value).strip()
    if field == "full_name":
        v = re.sub(r"[^a-z ]", "", v.lower())
        return re.sub(r"\s+", " ", v).strip() or None
    if field == "email":
        return v.lower()
    if field == "phone":
        digits = re.sub(r"\D", "", v)
        return digits[-10:] if len(digits) >= 10 else None
    if field == "dob":
        return v if re.match(r"^\d{4}-\d{2}-\d{2}$", v) else None
    if field == "id_last4":
        digits = re.sub(r"\D", "", v)
        return digits[-4:] if len(digits) >= 4 else None
    return None


def accepted(person, field):
    """Every value this person could correctly give for this field.
    Most fields have one. Names and emails can have aliases."""
    values = {
        "full_name": [person["name"]] + person.get("name_aliases", []),
        "email": [person["email"]] + person.get("email_aliases", []),
        "phone": [person["phone"]] + person.get("phone_aliases", []),
        "dob": [person["dob"]],
        "id_last4": [person["id_last4"]],
    }[field]
    return {clean(field, v) for v in values}


def matching_fields(person, claimed):
    """Which of the caller's answers are correct for this person."""
    return [f for f in FIELDS
            if clean(f, claimed.get(f)) is not None
            and clean(f, claimed.get(f)) in accepted(person, f)]


def check(claimed, party_id=None):
    """Decide where verification stands.

    party_id is set once we know who we are talking to. After that we only
    check that one person, so three answers borrowed from three different
    policyholders can never add up to a verified caller.
    """
    people = load_people()
    if party_id:
        people = [p for p in people if p["party_id"] == party_id]

    best, matched = None, []
    for person in people:
        fields = matching_fields(person, claimed)
        if len(fields) > len(matched):
            best, matched = person, fields

    # Fields the caller gave that did not match. A wrong value is a signal,
    # not just a non-event -- the caller needs to know something is off, and
    # repeated misses should end the call rather than loop forever.
    mismatched = [f for f in FIELDS
                  if claimed.get(f) and f not in matched]

    return {
        "party_id": best["party_id"] if best else party_id,
        "matched": matched,
        "mismatched": mismatched,
        "still_needed": [f for f in FIELDS if f not in matched],
        "verified": len(matched) >= REQUIRED,
    }


def person(party_id):
    """One policyholder record by id, or None."""
    for p in load_people():
        if p["party_id"] == party_id:
            return p
    return None