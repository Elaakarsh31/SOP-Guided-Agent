"""Checks the details a caller gives against the policyholder records."""

import re

from fixtures import load

# policy_number is excluded: it is printed on every letter we send.
FIELDS = ["full_name", "dob", "phone", "email", "id_last4"]
REQUIRED = 3

RECORD_COLUMN = {"full_name": "name"}


def load_people():
    return load("policyholders.json")


def clean(field, value):
    """Reduce a value to a comparable form, or None if it is unusable.

    Both the record and the spoken answer go through here so they meet in
    the middle.
    """
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
    """Every value this person could correctly give for one field.

    Names, emails and phone numbers may carry aliases on the record.
    """
    column = RECORD_COLUMN.get(field, field)
    values = [person[column], *person.get(f"{column}_aliases", [])]
    return {clean(field, v) for v in values}


def matching_fields(person, claimed):
    """Which of the caller's answers are right for this person."""
    hits = []
    for field in FIELDS:
        value = clean(field, claimed.get(field))
        if value is not None and value in accepted(person, field):
            hits.append(field)
    return hits


def check(claimed, party_id=None):
    """Score the details given so far and report where verification stands.

    Once party_id is set we score against that record alone, so answers
    borrowed from several policyholders cannot add up to a verified caller.
    """
    people = load_people()
    if party_id:
        people = [p for p in people if p["party_id"] == party_id]

    best, matched = None, []
    for person in people:
        fields = matching_fields(person, claimed)
        if len(fields) > len(matched):
            best, matched = person, fields

    mismatched = [f for f in FIELDS if claimed.get(f) and f not in matched]

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
