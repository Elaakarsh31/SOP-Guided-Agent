"""End-of-call summary: what to put in it, and the send step.

The payload is assembled from state and the claim record. The model writes
the wording from that payload and nothing else, so the summary cannot
contain a fact the call did not establish.
"""

import json
from datetime import datetime
from pathlib import Path

import claims
import identity

# Where simulated sends are recorded. There is no mail server in this demo;
# writing the payload to disk keeps the step honest and inspectable.
OUTBOX = Path(__file__).parent / "outbox"

TOPIC_LABELS = {
    "denial_question": "why the claim was denied",
    "status_inquiry": "the current claim status",
    "document_submission": "how to submit the missing documents",
    "next_steps": "what happens next",
    "general_claim_question": "general questions about the claim",
}


def recipient(state):
    """Always the policyholder on file, never an address the caller gave.

    A representative gets the call summarised to the person whose claim it
    is, not to themselves.
    """
    who = identity.person(state.get("party_id"))
    if not who:
        return None
    return {"name": who["name"], "email": who["email"]}


def build(state):
    """The facts the summary may contain. Returns None if there is no claim."""
    claim = claims.get(state.get("case_id"))
    if not claim:
        return None

    to = recipient(state)
    discussed = [TOPIC_LABELS.get(t, t) for t in state.get("discussed", [])]

    payload = {
        "to": to,
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


def send(payload, body):
    """Simulated send. Writes the message to outbox/ and returns a receipt."""
    OUTBOX.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = OUTBOX / f"{payload['case_id']}-{stamp}.json"
    record = {
        "sent_at": datetime.now().isoformat(timespec="seconds"),
        "to": payload["to"],
        "subject": f"Summary of your call about claim {payload['case_id']}",
        "body": body,
        "payload": payload,
    }
    path.write_text(json.dumps(record, indent=2))
    return {"ok": True, "to": payload["to"]["email"], "file": str(path)}