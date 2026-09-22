import contextvars
import os
from functools import lru_cache
from pathlib import Path

import yaml
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import AIMessage, SystemMessage
from dotenv import load_dotenv
import identity
import claims
import consent
import guidance
import briefs
import summary
from state import AgentState, Extraction

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

MODEL = os.getenv("SOP_MODEL", "gemini-3.5-flash-lite")

# A reviewer can supply their own key per session instead of using the one
# the server was started with. The server sets this before each turn.
CURRENT_KEY = contextvars.ContextVar("current_api_key", default=None)


class MissingKey(RuntimeError):
    pass


@lru_cache(maxsize=8)
def _clients(api_key):
    """Built once per distinct key, not once per call."""
    llm = ChatGoogleGenerativeAI(
        model=MODEL, api_key=api_key, thinking_budget=128,
    )
    return llm, llm.with_structured_output(Extraction)


def _active_key():
    key = CURRENT_KEY.get() or GEMINI_API_KEY
    if not key:
        raise MissingKey(
            "No API key. Set GEMINI_API_KEY on the server, or paste a key in "
            "the key box above the chat."
        )
    return key


def llm():
    return _clients(_active_key())[0]


def extractor():
    return _clients(_active_key())[1]

PROMPTS = yaml.safe_load(
    (Path(__file__).parent / "prompts.yaml").read_text()
)

EXTRACT_PROMPT = PROMPTS["extract"]
RESPOND_PROMPT = PROMPTS["respond"]

def extract(state: AgentState) -> dict:
    """Pull identity, caller role and case hints out of the latest message.

    Runs in every phase. Callers state why they are calling long before they
    are verified, and that has to be captured when it is said.
    """
    # A bare "my name is David Chen" is ambiguous on its own. Once we know a
    # representative is on the line, tell the extractor whose name is whose.
    # A bare "6688" or "+16502088799" means nothing without knowing what was
    # just asked. Name the pending fields so the extractor can place it.
    ask_note = ""
    if state["phase"] == "VERIFY_ID":
        pending = (state.get("gate") or {}).get("still_needed") or []
        if pending:
            ask_note = (
                "\n\nContext: verification is in progress and these details are "
                f"still outstanding: {', '.join(pending)}. If this message is a "
                "bare value with no label - a number, a date, a name - place it "
                "in whichever of those fields it fits. A caller correcting an "
                "earlier answer is giving that same field again."
            )

    role_note = ""
    if state.get("caller_role") == "representative":
        role_note = (
            "\n\nContext: this caller is acting for the policyholder. Their OWN "
            "name goes in caller.rep_name. Only the POLICYHOLDER's name goes in "
            "identity.full_name."
        )

    recent = state["messages"][-3:]
    try:
        result = extractor().invoke(
            [SystemMessage(content=EXTRACT_PROMPT + ask_note + role_note), *recent]
        ).model_dump()
    except MissingKey:
        raise
    except Exception:
        # A malformed or rate-limited extraction leaves state untouched
        # rather than taking the turn down.
        return {}

    # A field that already matched the pinned party is settled. Nothing later
    # in the conversation may overwrite it and flip verification back off.
    locked = set((state.get("gate") or {}).get("matched", []))

    claimed = dict(state.get("claimed") or {})
    for field, value in result["identity"].items():
        if value not in (None, "") and field not in locked:
            claimed[field] = value

    # Two signals, either is enough. The model's flag catches "actually a
    # different one"; the contradiction check catches "tell me about my auto
    # claim", where nothing in the wording says switch but the named type
    # does not match the pinned claim.
    req = result["request"]
    switching = (
        bool(req.get("switch_case"))
        or claims.contradicts(req, state.get("case_id"))
    )

    # A switch means the old narrowing hints are stale. Clear them BEFORE
    # merging this turn's, or "actually the auto one" still carries last
    # claim's status and period and selects the same claim again.
    hints = dict(state.get("hints") or {})
    if switching:
        for k in ("case_id", "case_type", "status", "period"):
            hints.pop(k, None)

    for f, v in req.items():
        if f == "switch_case":
            continue
        if v not in (None, "", "none"):
            hints[f] = v

    # grounding is left alone: resolve_intent rewrites it whenever it runs, and
    # PROCESS_CASE turns skip that node and still need the picked claim.
    # Written every turn, never accumulated: it describes this message only.
    out = {"claimed": claimed, "hints": hints, "switch_requested": switching}
    if switching:
        out["case_id"] = None

    # Scope guard. Strikes count consecutive off-topic turns and reset the
    # moment the caller returns to their claim, so an idle aside does not
    # accumulate toward a transfer across a long call.
    offtopic = req.get("intent") == "out_of_scope"
    out["offtopic"] = offtopic
    out["offtopic_strikes"] = (
        state.get("offtopic_strikes", 0) + 1 if offtopic else 0
    )
    if offtopic:
        # An out-of-scope message tells us nothing about the claim. Keep the
        # hints we already had rather than letting it overwrite intent.
        out["hints"] = dict(state.get("hints") or {})

    # Closing signals describe this message only, so they are written every
    # turn rather than accumulated.
    closing = result["closing"]
    out["wrap_up"] = bool(closing.get("wrap_up"))
    # Sticky: once a person has been asked for, the call stays handed off.
    out["wants_human"] = bool(closing.get("wants_human")) or bool(
        state.get("wants_human"))
    if closing.get("email_choice") and state.get("email_offered"):
        out["email_choice"] = closing["email_choice"]

    # Only write when present, so a later "yes I'll hold" cannot blank the role.
    caller = result["caller"]
    for f in ("caller_role", "rep_name"):
        if caller.get(f) not in (None, ""):
            out[f] = caller[f]

    return out


def verify(state: AgentState) -> dict:
    """The gate. Identity and authorization are separate questions."""
    if state["phase"] != "VERIFY_ID":
        return {}

    gate = identity.check(state.get("claimed") or {}, state.get("party_id"))
    out = {"gate": gate, "party_id": gate["party_id"], "verified": gate["verified"]}

    if not gate["verified"]:
        return {**out, "phase": "VERIFY_ID"}

    # Policyholder calling for themselves: one gate was enough.
    if state.get("caller_role") != "representative":
        return {**out, "phase": "RESOLVE_INTENT"}

    # Representative: knowing the policyholder's details is not authorization.
    record = consent.authorized(state.get("rep_name"), gate["party_id"])
    if not record:
        # Not on the list. Consent is never asked for, so consent_status
        # stays untouched -- there is nothing for it to report.
        return {
            **out,
            "phase": "VERIFY_ID",
            "authorized": False,
            "unauthorized_turns": state.get("unauthorized_turns", 0) + 1,
        }

    out["authorized"] = True
    out["relationship"] = record.get("relationship")

    polls = state.get("consent_polls", 0)
    status = consent.poll(polls)
    out["consent_polls"] = polls + 1
    out["consent_status"] = status

    # Only the exact string 'approved' opens the gate.
    return {**out, "phase": "RESOLVE_INTENT" if status == "approved" else "VERIFY_ID"}


def resolve_intent(state: AgentState) -> dict:
    """Work out which claim the caller means, using whatever they have said."""
    hints = state.get("hints") or {}
    matches, used = claims.find(state["party_id"], hints)

    if len(matches) == 1:
        picked = matches[0]
        return {
            "case_id": picked["case_id"],
            "intent": hints.get("intent") or "general_claim_question",
            "phase": "PROCESS_CASE",
            "switch_requested": False,
            "grounding": {
                "picked": claims.summary_view(picked),
                "recognised_from": used,
            },
        }

    return {
        "phase": "RESOLVE_INTENT",
        "switch_requested": False,
        "grounding": {
            "options": [claims.summary_view(c) for c in matches],
            "narrowed_by": used,
        },
    }


def process_case(state: AgentState) -> dict:
    """Assemble the facts and guidance the agent may use for this question.

    Nothing here is generated. The claim row is filtered by intent, and the
    guidance text comes straight out of the fixture with the claim id and
    document names filled in.
    """
    claim = claims.get(state.get("case_id"))
    if not claim:
        return {"phase": "RESOLVE_INTENT", "case_id": None, "grounding": {}}

    text = state["messages"][-1].content if state["messages"] else ""
    hints = state.get("hints") or {}
    intent = hints.get("intent") or state.get("intent") or "general_claim_question"

    ground = {
        "facts": guidance.claim_facts(claim, intent, text),
        "intent": intent,
    }

    rows = guidance.followup_guidance(claim, intent, text)
    if rows:
        ground["guidance"] = [r["text"] for r in rows]
        ground["guidance_topics"] = [r["topic"] for r in rows]

    if claim.get("documents_needed"):
        ground["documents"] = guidance.document_requirements(claim)
        if intent == "document_submission":
            ground["submission_basics"] = guidance.submission_basics(claim)

    if not rows and intent in ("next_steps", "status_inquiry",
                               "general_claim_question"):
        ground["fallback"] = guidance.fallback()

    # Keep a running list of what the call has covered, for the summary.
    discussed = list(state.get("discussed") or [])
    if intent not in discussed and intent != "out_of_scope":
        discussed.append(intent)

    return {
        "phase": "PROCESS_CASE",
        "intent": intent,
        "discussed": discussed,
        "grounding": ground,
    }


def post_process(state: AgentState) -> dict:
    """Offer an emailed summary, then honour whatever the caller chooses.

    The payload is assembled from state and the claim record. The responder
    writes the wording from that payload, so the summary cannot contain a
    fact the call did not establish.
    """
    payload = summary.build(state)
    if not payload:
        # Nothing to summarise -- close without an offer.
        return {"phase": "POST_PROCESS", "closed": True,
                "grounding": {"closing": True}}

    choice = state.get("email_choice")

    if choice == "skip":
        return {
            "phase": "POST_PROCESS",
            "closed": True,
            "grounding": {"closing": True, "email": "skipped"},
        }

    if choice == "send" and not state.get("email_sent"):
        # The body the caller will receive is the same text the agent speaks,
        # so it is written once by respond and recorded here.
        receipt = summary.send(payload, _summary_text(payload))
        return {
            "phase": "POST_PROCESS",
            "email_sent": True,
            "closed": True,
            "grounding": {"closing": True, "email": "sent",
                          "receipt": receipt, "summary": payload},
        }

    # First time through: make the offer.
    return {
        "phase": "POST_PROCESS",
        "email_offered": True,
        "grounding": {"summary": payload, "email": "offered"},
    }


def _summary_text(payload):
    """Plain-text body for the recorded email. Deterministic on purpose."""
    lines = [
        f"Summary of your call about claim {payload['case_id']}",
        "",
        f"Claim: {payload['case_id']} ({payload['case_type']}, filed "
        f"{payload['filed']})",
        f"Status: {payload['status']}",
        f"Outcome: {payload['outcome']}",
        "",
        "What we discussed: " + ", ".join(payload["discussed"]),
    ]
    if payload.get("next_steps"):
        lines += ["", "Next steps:"]
        lines += [f"  - {s}" for s in payload["next_steps"]]
    if payload.get("spoke_with"):
        lines += ["", f"Call handled with {payload['spoke_with']} on your behalf."]
    return "\n".join(lines)


def respond(state: AgentState) -> dict:
    """The only node that produces text the caller sees.

    It works from the brief and grounding it is handed. It never reads the
    fixtures itself, so anything it cannot be told, it cannot leak.
    """
    ground = state.get("grounding") or {}

    # Identity alone is not clearance. A representative also needs consent.
    cleared = state["verified"] and (
        state.get("caller_role") != "representative"
        or state.get("consent_status") == "approved"
    )

    if state.get("wants_human"):
        brief = briefs.handoff_brief(state)
    elif state.get("offtopic"):
        brief = briefs.offtopic_brief(state)
    elif not cleared:
        brief = briefs.identity_brief(state)
    elif state["phase"] == "RESOLVE_INTENT":
        brief = briefs.choose_claim_brief(ground)
    elif ground.get("email"):
        brief = briefs.closing_brief(state, ground)
    elif ground.get("closing"):
        brief = briefs.closing_brief(state, ground)
    elif ground.get("facts"):
        brief = briefs.process_brief(ground)
    else:
        brief = briefs.claim_picked_brief(ground)

    if cleared and state.get("caller_role") == "representative":
        brief += briefs.representative_note(state)

    messages = [
        SystemMessage(content=RESPOND_PROMPT),
        *state["messages"][-8:],
        SystemMessage(content=f"[internal, not visible to caller]\n{brief}"),
    ]

    out = llm().invoke(messages)
    text = (out.text or "").strip()
    if not text:
        text = (llm().invoke(messages).text or "").strip()
    if not text:
        text = ("Sorry, I lost that for a second. Could you say that again?")
    return {"messages": [AIMessage(content=text)]}