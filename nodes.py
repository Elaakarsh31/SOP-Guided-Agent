import contextvars
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

import briefs
import claims
import consent
import guidance
import identity
import summary
from state import AgentState, Extraction

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = os.getenv("SOP_MODEL", "gemini-3.5-flash-lite")

# Set per request by the server when a user supplies their own key in the UI.
CURRENT_KEY = contextvars.ContextVar("current_api_key", default=None)

_clients = {}


def llm(structured=False):
    key = CURRENT_KEY.get() or GEMINI_API_KEY
    if not key:
        raise ValueError("No API key. Set GEMINI_API_KEY or paste one in the UI.")
    if key not in _clients:
        chat = ChatGoogleGenerativeAI(model=MODEL, api_key=key, thinking_budget=128)
        _clients[key] = (chat, chat.with_structured_output(Extraction))
    return _clients[key][1 if structured else 0]


PROMPTS = yaml.safe_load((Path(__file__).parent / "prompts.yaml").read_text())
EXTRACT_PROMPT = PROMPTS["extract"]
RESPOND_PROMPT = PROMPTS["respond"]

DIFFICULT = ("frustrated", "angry", "upset")
# Cleared when the caller moves to a different claim. intent is in here
# because what they wanted about the last claim says nothing about this one.
NARROWING_HINTS = ("case_id", "case_type", "status", "period", "intent")


def _extract_context(state):
    """Extra prompt context so bare values land in the right field."""
    notes = ""

    if state["phase"] == "VERIFY_ID":
        pending = (state.get("gate") or {}).get("still_needed") or []
        if pending:
            notes += (
                "\n\nVerification is in progress and these details are still "
                f"outstanding: {', '.join(pending)}. If this message is a bare "
                "value with no label, place it in whichever of those fields it "
                "fits. A caller correcting an earlier answer is giving that "
                "same field again."
            )

    if state.get("caller_role") == "representative":
        notes += (
            "\n\nThis caller is acting for the policyholder. Their OWN name "
            "goes in caller.rep_name. Only the POLICYHOLDER's name goes in "
            "identity.full_name."
        )

    return notes


def extract(state: AgentState) -> dict:
    """Read the latest message into state. Runs in every phase.

    Callers say why they are calling long before they are verified, so this
    has to capture intent and case hints during VERIFY_ID too.
    """
    prompt = EXTRACT_PROMPT + _extract_context(state)
    try:
        result = llm(structured=True).invoke(
            [SystemMessage(content=prompt), *state["messages"][-3:]]
        ).model_dump()
    except ValueError:
        raise
    except Exception:
        # Rate limits and malformed responses leave state untouched rather
        # than taking the turn down.
        return {}

    identity_fields = result["identity"]
    req = result["request"]
    caller = result["caller"]
    mood = result["mood"]
    closing = result["closing"]

    # A field that already matched the pinned party is settled. Nothing later
    # may overwrite it and flip verification back off.
    locked = set((state.get("gate") or {}).get("matched", []))
    claimed = dict(state.get("claimed") or {})
    for field, value in identity_fields.items():
        if value not in (None, "") and field not in locked:
            claimed[field] = value

    # The model's flag catches "actually a different one". The contradiction
    # check catches "tell me about my auto claim", where nothing in the
    # wording says switch but the named type is not the pinned claim's.
    switching = bool(req.get("switch_case")) or claims.contradicts(
        req, state.get("case_id"))

    hints = dict(state.get("hints") or {})
    if switching:
        # Clear the old filters before merging this turn's, or "the auto one"
        # still carries the last claim's status and selects it again.
        for key in NARROWING_HINTS:
            hints.pop(key, None)

    offtopic = req.get("intent") == "out_of_scope"
    if not offtopic:
        for field, value in req.items():
            if field != "switch_case" and value not in (None, "", "none"):
                hints[field] = value

    emotion = mood.get("emotion") or "calm"
    refusing = bool(mood.get("refusing"))
    difficult = refusing or emotion in DIFFICULT

    out = {
        "claimed": claimed,
        "hints": hints,
        "switch_requested": switching,
        "emotion": emotion,
        "refusing": refusing,
        "offtopic": offtopic,
        "wrap_up": bool(closing.get("wrap_up")),
        # Counters track consecutive turns and reset on a good one, so an
        # isolated aside or sharp remark does not build toward a transfer.
        "friction": state.get("friction", 0) + 1 if difficult else 0,
        "offtopic_strikes": state.get("offtopic_strikes", 0) + 1 if offtopic else 0,
        # Deliberately not sticky. A wrong read here would otherwise end the
        # call for good, and the handoff brief already avoids repeating itself.
        "wants_human": bool(closing.get("wants_human")),
    }

    if switching:
        out["case_id"] = None

    if closing.get("email_choice") and state.get("email_offered"):
        out["email_choice"] = closing["email_choice"]

    # Only write when present, so a later "yes I'll hold" cannot blank the role.
    for field in ("caller_role", "rep_name"):
        if caller.get(field) not in (None, ""):
            out[field] = caller[field]

    return out


def verify(state: AgentState) -> dict:
    """Identity and authorization are separate gates. Both must pass."""
    if state["phase"] != "VERIFY_ID":
        return {}

    gate = identity.check(state.get("claimed") or {}, state.get("party_id"))
    out = {"gate": gate, "party_id": gate["party_id"], "verified": gate["verified"]}

    # Count new wrong answers, not fields currently wrong. A caller who
    # corrects a typo should not be charged twice for the same field.
    previously_wrong = set((state.get("gate") or {}).get("mismatched", []))
    out["bad_attempts"] = state.get("bad_attempts", 0) + len(
        set(gate["mismatched"]) - previously_wrong)

    if not gate["verified"]:
        return {**out, "phase": "VERIFY_ID"}

    if state.get("caller_role") != "representative":
        return {**out, "phase": "RESOLVE_INTENT"}

    # Knowing the policyholder's details is not authorization.
    record = consent.authorized(state.get("rep_name"), gate["party_id"])
    if not record:
        # Consent is never asked for here, so consent_status stays untouched.
        return {
            **out,
            "phase": "VERIFY_ID",
            "authorized": False,
            "unauthorized_turns": state.get("unauthorized_turns", 0) + 1,
        }

    polls = state.get("consent_polls", 0)
    status = consent.poll(polls)
    out.update(
        authorized=True,
        relationship=record.get("relationship"),
        consent_polls=polls + 1,
        consent_status=status,
    )

    # Only the exact string 'approved' opens the gate.
    return {**out, "phase": "RESOLVE_INTENT" if status == "approved" else "VERIFY_ID"}


def resolve_intent(state: AgentState) -> dict:
    """Decide which claim the caller means from whatever they have said."""
    hints = state.get("hints") or {}
    matches, used = claims.find(state["party_id"], hints)

    if len(matches) != 1:
        return {
            "phase": "RESOLVE_INTENT",
            "switch_requested": False,
            "grounding": {
                "options": [claims.summary_view(c) for c in matches],
                "narrowed_by": used,
            },
        }

    picked = matches[0]
    intent = hints.get("intent") or "general_claim_question"
    discussed = list(state.get("discussed") or [])
    if intent not in discussed:
        discussed.append(intent)

    return {
        "case_id": picked["case_id"],
        "intent": intent,
        "discussed": discussed,
        "phase": "PROCESS_CASE",
        "switch_requested": False,
        "grounding": {
            "picked": claims.summary_view(picked),
            "recognised_from": used,
        },
    }


def process_case(state: AgentState) -> dict:
    """Collect the facts and guidance the agent may use for this question.

    Nothing here is generated. The claim row is filtered by intent and the
    guidance text comes out of the fixture with the placeholders filled in.
    """
    claim = claims.get(state.get("case_id"))
    if not claim:
        return {"phase": "RESOLVE_INTENT", "case_id": None, "grounding": {}}

    text = state["messages"][-1].content if state["messages"] else ""
    hints = state.get("hints") or {}

    # The latest question decides the intent, not whatever the caller wanted
    # when the claim was first pinned.
    intent = hints.get("intent") or state.get("intent") or "general_claim_question"

    ground = {"facts": guidance.claim_facts(claim, intent, text), "intent": intent}

    rows = guidance.followup_guidance(claim, intent, text)
    if rows:
        ground["guidance"] = [r["text"] for r in rows]
        ground["guidance_topics"] = [r["topic"] for r in rows]
    elif intent in ("next_steps", "status_inquiry", "general_claim_question"):
        ground["fallback"] = guidance.fallback()

    if claim.get("documents_needed"):
        ground["documents"] = guidance.document_requirements(claim)
        if intent == "document_submission":
            ground["submission_basics"] = guidance.submission_basics(claim)

    discussed = list(state.get("discussed") or [])
    if intent not in discussed:
        discussed.append(intent)

    return {
        "phase": "PROCESS_CASE",
        "intent": intent,
        "discussed": discussed,
        "grounding": ground,
    }


def summary_text(payload):
    """The emailed body. Built from the payload, not written by the model."""
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


def post_process(state: AgentState) -> dict:
    """Offer an emailed summary, then do whatever the caller chose."""
    payload = summary.build(state)
    if not payload:
        return {"phase": "POST_PROCESS", "closed": True,
                "grounding": {"closing": True}}

    choice = state.get("email_choice")

    if choice == "skip":
        return {"phase": "POST_PROCESS", "closed": True,
                "grounding": {"closing": True, "email": "skipped"}}

    if choice == "send" and not state.get("email_sent"):
        receipt = summary.send(payload, summary_text(payload))
        return {
            "phase": "POST_PROCESS",
            "email_sent": True,
            "closed": True,
            "grounding": {"closing": True, "email": "sent",
                          "receipt": receipt, "summary": payload},
        }

    return {
        "phase": "POST_PROCESS",
        "email_offered": True,
        "grounding": {"summary": payload, "email": "offered"},
    }


def _brief_for(state, ground, cleared):
    if state.get("wants_human"):
        return briefs.handoff_brief(state)
    if state.get("offtopic"):
        return briefs.offtopic_brief(state)
    if not cleared:
        return briefs.identity_brief(state)
    if state["phase"] == "RESOLVE_INTENT":
        return briefs.choose_claim_brief(ground)
    if ground.get("email") or ground.get("closing"):
        return briefs.closing_brief(state, ground)
    if ground.get("facts"):
        return briefs.process_brief(ground)
    return briefs.claim_picked_brief(ground)


def respond(state: AgentState) -> dict:
    """The only node that produces text the caller sees.

    It works from the brief it is handed and never reads the fixtures, so
    anything it cannot be told, it cannot leak.
    """
    ground = state.get("grounding") or {}

    # Identity alone is not clearance. A representative also needs consent.
    cleared = state["verified"] and (
        state.get("caller_role") != "representative"
        or state.get("consent_status") == "approved"
    )

    brief = _brief_for(state, ground, cleared)
    if cleared and state.get("caller_role") == "representative":
        brief += briefs.representative_note(state)

    # Tone guidance goes in front of the rules, never in place of them.
    brief = briefs.mood_note(state, cleared) + brief

    messages = [
        SystemMessage(content=RESPOND_PROMPT),
        *state["messages"][-8:],
        SystemMessage(content=f"[internal, not visible to caller]\n{brief}"),
    ]

    text = (llm().invoke(messages).text or "").strip()
    if not text:
        text = (llm().invoke(messages).text or "").strip()
    if not text:
        text = "Sorry, I lost that for a second. Could you say that again?"

    return {"messages": [AIMessage(content=text)]}