"""Builds and sends the end-of-call summary.

build() assembles the payload from state and the claim record; the model is
given that payload and nothing else.
"""

import json
from datetime import datetime
from pathlib import Path

import claims
import identity

OUTBOX = Path(__file__).parent / "outbox"

TOPIC_LABELS = {
    "denial_question": "why the claim was denied",
    "status_inquiry": "the current claim status",
    "document_submission": "how to submit the missing documents",
    "next_steps": "what happens next",
    "general_claim_question": "general questions about the claim",
}


def recipient(state):
    """The address on the policy, whoever made the call.

    A representative gets the call summarised to the policyholder, so the
    summary cannot redirect claim details to an address the caller supplied.
    """
    who = identity.person(state.get("party_id"))
    if not who:
        return None
    return {"name": who["name"], "email": who["email"]}


def build(state):
    """Gather the facts the summary may contain, or None if no claim was pinned."""
    claim = claims.get(state.get("case_id"))
    if not claim:
        return None

    discussed = [TOPIC_LABELS.get(t, t) for t in state.get("discussed", [])]

    payload = {
        "to": recipient(state),
        "case_id": claim["case_id"],
        "case_type": claim["case_type"],
        "status": claim["status"],
        "filed": claim["created_at"],
        "discussed": discussed or ["the claim"],
        "next_steps": [],
    }

    if claim.get("denial_reason"):
        payload["outcome"] = f"denied because {claim['denial_reason']}"
    else:
        payload["outcome"] = claim.get("summary", f"status: {claim['status']}")

    docs = claim.get("documents_needed") or []
    if docs:
        payload["documents_needed"] = docs
        payload["next_steps"].append(
            "send in " + " and ".join(docs) + " so the claim can be reviewed again"
        )

    if claim.get("appeal_deadline"):
        payload["appeal_deadline"] = claim["appeal_deadline"]
        payload["next_steps"].append(
            f"the appeal deadline on file is {claim['appeal_deadline']}"
        )

    if state.get("caller_role") == "representative":
        payload["spoke_with"] = state.get("rep_name")

    return payload


def email_body(payload):
    """Render the payload as the plain-text email.

    Written here rather than by the model so what lands in the caller's
    inbox is predictable.
    """
    lines = [
        f"Summary of your call about claim {payload['case_id']}",
        "",
        f"Claim: {payload['case_id']} ({payload['case_type']}, "
        f"filed {payload['filed']})",
        f"Status: {payload['status']}",
        f"Outcome: {payload['outcome']}",
        "",
        "What we discussed: " + ", ".join(payload["discussed"]),
    ]
    if payload.get("next_steps"):
        lines += ["", "Next steps:"] + [f"  - {s}" for s in payload["next_steps"]]
    if payload.get("spoke_with"):
        lines += ["", f"Call handled with {payload['spoke_with']} on your behalf."]
    return "\n".join(lines)


def send(payload, body):
    """Simulated send. Writes the message to outbox/ and returns a receipt."""
    OUTBOX.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    path = OUTBOX / f"{payload['case_id']}-{now:%Y%m%d-%H%M%S}.json"
    record = {
        "sent_at": now.isoformat(timespec="seconds"),
        "to": payload["to"],
        "subject": f"Summary of your call about claim {payload['case_id']}",
        "body": body,
        "payload": payload,
    }
    path.write_text(json.dumps(record, indent=2))
    return {"ok": True, "to": payload["to"]["email"], "file": str(path)}
