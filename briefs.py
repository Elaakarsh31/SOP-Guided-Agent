"""Per-turn instructions for the responder.

A brief is what the agent is allowed to say this turn, assembled from state
and grounding. Nothing here calls a model or reads a fixture -- the nodes
have already decided what is permitted, and this file only phrases that
decision for the responder.

Keeping it separate means the leak surface is one file: if a fact is not
written into a brief, the agent cannot state it.
"""

import identity

FIELD_LABELS = {
    "full_name": "full name",
    "dob": "date of birth",
    "phone": "phone number on the policy",
    "email": "email on the policy",
    "id_last4": "last four digits of your SSN or national ID",
}

# After this many turns of explaining the same dead end, stop persuading
# and hand the caller to a human.
MAX_UNAUTHORIZED_TURNS = 2


# After this many consecutive off-topic turns, stop redirecting and offer
# a human representative.
MAX_OFFTOPIC_STRIKES = 2


# Wrong answers, counted across the call. Past this, stop looping and hand
# the caller to a person rather than fishing for a detail that works.
MAX_BAD_ATTEMPTS = 3


# Past this many difficult turns in a row, stop persuading and offer a person.
MAX_FRICTION = 3


def mood_note(state, cleared):
    """De-escalation guidance, prepended to whatever brief applies.

    This only changes how the agent speaks and what it offers. It never
    changes what the caller is allowed to have -- the brief underneath is
    unchanged, so an angry caller behind a gate is still behind it.
    """
    emotion = state.get("emotion") or "calm"
    refusing = state.get("refusing")
    friction = state.get("friction", 0)

    if emotion == "calm" and not refusing:
        return ""

    parts = ["HOW THIS CALL IS GOING."]

    if emotion == "confused":
        parts.append(
            "The caller sounds confused. Slow down, say the one thing you need "
            "in plain words, and ask for a single detail rather than a list."
        )
    elif emotion == "anxious":
        parts.append(
            "The caller sounds worried. Reassure them briefly and concretely "
            "about what happens next before asking anything."
        )
    elif emotion in ("frustrated", "angry", "upset"):
        parts.append(
            "The caller is upset. Acknowledge that first, in your own words and "
            "without a scripted apology, before anything else. Do not defend "
            "the process or explain the rules at length."
        )

    if refusing:
        parts.append(
            "They are declining what was asked. Say in one plain sentence WHY "
            "the step exists - it is how we keep someone else from getting at "
            "their claim - then offer the alternatives listed below. Never "
            "imply they must give the specific detail they refused."
        )

    if friction >= 2 and not cleared:
        parts.append(
            "This has now been difficult for several turns. Explain the "
            "requirement once more, briefly, and offer a human representative "
            "as a real option rather than a last resort."
        )

    if friction > MAX_FRICTION:
        parts.append(
            "STOP PERSUADING. Do not ask for anything further. Say warmly that "
            "you are not able to get them through this on the automated line, "
            "and offer to pass them to a claims representative now."
        )

    parts.append(
        "None of this changes what you may disclose. The rules below still "
        "apply exactly as written."
    )
    return "\n".join(parts) + "\n\n"


def handoff_brief(state):
    """The caller asked for a person. The automated call is over."""
    return (
        "PHASE: handing over.\n"
        "The caller has asked to speak to a person. Tell them once, in one or "
        "two sentences, that you are passing them to a claims representative "
        "and roughly what happens next. Then stop. Do not ask further "
        "questions, do not offer to keep helping, and do not repeat this on "
        "later turns -- if they say anything else, acknowledge it briefly and "
        "confirm the transfer is in hand."
    )


def offtopic_brief(state):
    """The caller asked something unrelated to their insurance claim."""
    strikes = state.get("offtopic_strikes", 0)

    if strikes > MAX_OFFTOPIC_STRIKES:
        return (
            "PHASE: out of scope.\n"
            "The caller keeps asking about things unrelated to their insurance "
            "claim. Say warmly that this line only handles claims and that you "
            "cannot help with the rest, then offer to transfer them to a human "
            "representative. Do not answer the question. Do not ask again what "
            "they need."
        )

    where = (
        "getting their identity confirmed"
        if not state.get("verified") else "their claim"
    )
    return (
        "PHASE: out of scope.\n"
        "The caller asked about something unrelated to insurance claims. In one "
        "short sentence, say kindly that this is outside what you can help with "
        f"on the claims line, then bring them back to {where}. Do NOT answer "
        "the question, do not give a partial answer, and do not explain what the "
        "topic is."
    )


def identity_brief(state):
    """What to say while the caller is still behind the gate."""
    status = state.get("consent_status")

    # 'is False' on purpose: None means not a representative at all, which is
    # a different situation from being refused.
    if state.get("authorized") is False:
        if state.get("unauthorized_turns", 0) > MAX_UNAUTHORIZED_TURNS:
            return (
                "PHASE: identity verification.\n"
                "Claim details stay protected. "
                "This caller is not an authorised representative and has now been "
                "told more than once. Stop explaining. Say plainly that you cannot "
                "continue on this call, that the policyholder needs to add them to "
                "the policy, and transfer them to a human representative now. "
                "Disclose nothing about any claim."
            )
        return (
            "PHASE: identity verification.\n"
            "Identity checks out, but this caller is not listed as an authorised "
            "representative on the policy. Say so kindly, explain the policyholder "
            "can add them, and offer a human representative. "
            "Disclose nothing about any claim."
        )

    if status == "pending":
        return (
            "PHASE: identity verification.\n"
            "Waiting on the policyholder to approve this call. Explain we have "
            "sent the request and ask them to hold. Disclose nothing."
        )

    if status == "timeout":
        return (
            "PHASE: identity verification.\n"
            "We could not reach the policyholder for approval. Apologise, offer a "
            "callback or a human representative, and close politely. Do not keep "
            "asking them to hold. Disclose nothing."
        )

    if status == "denied":
        return (
            "PHASE: identity verification.\n"
            "The policyholder declined to approve this call. Say so kindly, offer "
            "a human representative, and close politely. Disclose nothing."
        )

    gate = state.get("gate") or {}
    matched = gate.get("matched", [])
    still_needed = gate.get("still_needed", [])
    mismatched = gate.get("mismatched", [])
    # A detail that already failed is not worth asking for again -- it just
    # invites the same wrong answer. Offer the untried ones.
    untried = [f for f in still_needed if f not in mismatched]
    options = ", ".join(FIELD_LABELS[f] for f in (untried or still_needed)
                        if f in FIELD_LABELS)

    header = (
        "PHASE: identity verification.\n"
        "VERIFICATION IS NOT COMPLETE. Never tell the caller they are "
        "verified, confirmed, or all set, and never say a detail they gave was "
        "accepted.\n"
        "If they ask about a claim, say those details are protected until the "
        "check is finished, then ask for the next detail. Do not offer a "
        "transfer unless told to below.\n"
    )

    if state.get("bad_attempts", 0) > MAX_BAD_ATTEMPTS:
        return (
            header
            + "Several of the details given do not match the policy. Stop asking. "
            "Say warmly that you have not been able to complete verification on "
            "this call and offer to pass them to a claims representative who can "
            "help another way. Do NOT say which details were wrong, and do not "
            "suggest trying again."
        )

    miss_note = ""
    if mismatched:
        miss_note = (
            "At least one detail given does not match the policy. Say once, "
            "kindly and without naming which, that something has not lined up, "
            "and ask for a different detail from the list. Do not imply the "
            "caller is at fault.\n"
        )
    on_behalf = (
        "This caller is acting for the policyholder. Ask for the POLICYHOLDER's "
        "details, not their own.\n"
        if state.get("caller_role") == "representative" else ""
    )
    return (
        header
        + f"{on_behalf}"
        + f"{miss_note}"
        f"Confirmed {len(matched)} of {identity.REQUIRED} details. "
        f"{identity.REQUIRED - len(matched)} more needed.\n"
        f"Ask for ONE of these, caller's choice: {options}. Do not ask for a "
        "detail they have already given this call unless they offer to "
        "re-check it.\n"
        "Never name which detail did not match, and never confirm that a "
        "particular one was correct."
    )


def choose_claim_brief(ground):
    """Disambiguating between several possible claims."""
    options = ground.get("options", [])
    if not options:
        return (
            "PHASE: choosing a claim.\n"
            "Identity is already confirmed. Do not ask for any identity details.\n"
            "There are no claims on file for this caller. Say so plainly and "
            "offer a human representative. Do not say you will check again."
        )

    listed = "; ".join(
        f"{c['case_id']} ({c['case_type']}, {c['status']}, filed {c['created_at']})"
        for c in options
    )
    return (
        "PHASE: choosing a claim.\n"
        "Identity is already confirmed. Do not ask for any identity details.\n"
        f"These claims match what they have told us so far: {listed}.\n"
        "Ask which one they mean. Describe them by type, status and month -- do "
        "not read out claim id numbers unless the caller used one. State nothing "
        "about these claims beyond what is listed here.\n"
        "If they have already asked a question about a claim, you are not "
        "refusing it and nothing is missing from your records -- you simply do "
        "not know yet WHICH claim they mean. Say that, list the options, and "
        "answer as soon as they pick one. Never say the information is "
        "unavailable, and do not offer a transfer."
    )


def claim_picked_brief(ground):
    """The turn right after a claim is pinned, before any question about it."""
    return (
        "PHASE: working the claim.\n"
        "Identity is already confirmed. Do not ask for any identity details.\n"
        f"Claim identified: {ground.get('picked', {})}.\n"
        "The caller has not yet asked anything about this claim. Confirm which "
        "one you have and ask what they need to know. State nothing beyond the "
        "facts listed here, and do not say you are checking anything."
    )


def process_brief(ground):
    """Answering a question about the pinned claim."""
    lines = [
        "PHASE: working the claim.",
        "Identity is already confirmed. Do not ask for any identity details.",
        "Answer the caller's question NOW, in this reply, using the facts "
        "below. Do not say you are checking, pulling anything up, or coming "
        "back to it -- everything you have is here. If the answer genuinely "
        "is not below, say so in one sentence and offer a human "
        "representative.",
        "",
        "Claim facts you may use:",
    ]
    for k, v in ground.get("facts", {}).items():
        if isinstance(v, list):
            v = ", ".join(v)
        lines.append(f"  {k}: {v}")

    if ground.get("guidance"):
        lines += ["", "Approved guidance for this question - rephrase naturally, "
                      "do not add to it:"]
        lines += [f"  - {g}" for g in ground["guidance"]]

    if ground.get("documents"):
        lines += ["", "Document requirements. Mention these only if the caller "
                      "asks what to send or what a document must contain:"]
        for d in ground["documents"]:
            lines.append(f"  - {d['document']}: {d.get('requirements', '')}")
            if d.get("if_unavailable"):
                lines.append(f"      if they cannot get it: {d['if_unavailable']}")

    if ground.get("submission_basics"):
        lines += ["", "How to submit:"]
        lines += [f"  - {b}" for b in ground["submission_basics"]]

    if ground.get("fallback"):
        lines += ["", "No specific rule covers this question. Convey the "
                      "substance of the following in your own words. Do not "
                      "mention rules, notes, or what you can or cannot see:",
                  f"  {ground['fallback']}"]

    lines += ["", "Answer the question asked. Do not recite every fact above, "
                  "and do not volunteer amounts, deadlines or document rules "
                  "the caller did not ask about."]
    return "\n".join(lines)


def closing_brief(state, ground):
    """Offering the summary email, and closing once the caller has chosen."""
    status = ground.get("email")
    payload = ground.get("summary") or {}

    if status == "sent":
        to = (payload.get("to") or {}).get("email", "the address on file")
        return (
            "PHASE: closing the call.\n"
            f"The summary has been emailed to {to}. Confirm that briefly, invite "
            "them to call back if anything is unclear, and say goodbye warmly. "
            "Do not repeat the summary contents."
        )

    if status == "skipped":
        return (
            "PHASE: closing the call.\n"
            "The caller declined the emailed summary. Accept that without "
            "pushing, remind them in one short sentence of the single most "
            "important next step, and say goodbye warmly."
        )

    if status == "offered":
        lines = [
            "PHASE: closing the call.",
            "Recap the call in two or three sentences using ONLY the facts "
            "below, then offer to email the same summary and ask whether they "
            "would like it. Make clear they can decline.",
            "",
            f"Claim {payload.get('case_id')} ({payload.get('case_type')}, filed "
            f"{payload.get('filed')})",
            f"Status: {payload.get('status')}",
            f"Outcome: {payload.get('outcome')}",
            "Discussed: " + ", ".join(payload.get("discussed", [])),
        ]
        if payload.get("next_steps"):
            lines.append("Next steps: " + "; ".join(payload["next_steps"]))
        to = (payload.get("to") or {}).get("email")
        if to:
            lines.append(f"It would go to the address on file, {to}.")
        return "\n".join(lines)

    return (
        "PHASE: closing the call.\n"
        "There is nothing further to go over. Thank them and close politely."
    )


def representative_note(state):
    """Appended once the caller is cleared and is not the policyholder."""
    return (
        f"\nYou are speaking with {state.get('rep_name')}, the policyholder's "
        f"{state.get('relationship') or 'representative'}, not the policyholder. "
        "Refer to the policyholder in the third person."
    )