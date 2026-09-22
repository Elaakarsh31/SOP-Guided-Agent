"""The graph nodes, one function per step of the SOP.

Only extract() and respond() call a model. Identity scoring, consent,
claim selection and grounding are all plain Python.
"""

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

DEFAULT_MODEL = "gemini-3.5-flash-lite"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = os.getenv("SOP_MODEL", DEFAULT_MODEL)

# Set per request by the server when a tester supplies their own key.
CURRENT_KEY = contextvars.ContextVar("current_api_key", default=None)

_clients = {}


def llm(structured=False):
    """The Gemini client for the key in play, built once per key.

    structured=True returns a client that parses its reply into Extraction.
    """
    api_key = CURRENT_KEY.get() or GEMINI_API_KEY
    if not api_key:
        raise ValueError("No API key. Set GEMINI_API_KEY or paste one in the UI.")

    if api_key not in _clients:
        chat = ChatGoogleGenerativeAI(
            model=MODEL, api_key=api_key, thinking_budget=128)
        _clients[api_key] = {
            False: chat,
            True: chat.with_structured_output(Extraction),
        }
    return _clients[api_key][structured]


PROMPTS = yaml.safe_load((Path(__file__).parent / "prompts.yaml").read_text())
EXTRACT_PROMPT = PROMPTS["extract"]
RESPOND_PROMPT = PROMPTS["respond"]

DIFFICULT = ("frustrated", "angry", "upset")

# Hints dropped when the caller moves to a different claim.
NARROWING_HINTS = ("case_id", "case_type", "status", "period", "intent")

FALLBACK_REPLY = "Sorry, I lost that for a second. Could you say that again?"


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
    """Read the latest message into state.

    Runs in every phase, including verification, because callers explain
    what they want long before they are through the gate.
    """
    prompt = EXTRACT_PROMPT + _extract_context(state)
    try:
        result = llm(structured=True).invoke(
            [SystemMessage(content=prompt), *state["messages"][-3:]]
        ).model_dump()
    except ValueError:
        # A missing API key is a configuration fault; let the server report it.
        raise
    except Exception:
        # Rate limits and malformed replies leave state untouched.
        return {}

    identity_fields = result["identity"]
    req = result["request"]
    caller = result["caller"]
    mood = result["mood"]
    closing = result["closing"]

    # A field that already matched is settled and cannot be overwritten.
    locked = set((state.get("gate") or {}).get("matched", []))
    claimed = dict(state.get("claimed") or {})
    for field, value in identity_fields.items():
        if value not in (None, "") and field not in locked:
            claimed[field] = value

    # The flag catches an explicit switch, contradicts() an implicit one.
    switching = bool(req.get("switch_case")) or claims.contradicts(
        req, state.get("case_id"))

    hints = dict(state.get("hints") or {})
    if switching:
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
        # Consecutive counts, reset by a good turn.
        "friction": state.get("friction", 0) + 1 if difficult else 0,
        "offtopic_strikes": state.get("offtopic_strikes", 0) + 1 if offtopic else 0,
        "wants_human": bool(closing.get("wants_human")),
    }

    if switching:
        out["case_id"] = None

    if closing.get("email_choice") and state.get("email_offered"):
        out["email_choice"] = closing["email_choice"]

    # Written only when present, so a later turn cannot blank out the role.
    for field in ("caller_role", "rep_name"):
        if caller.get(field) not in (None, ""):
            out[field] = caller[field]

    return out


def verify(state: AgentState) -> dict:
    """Score identity, then authorisation. A representative needs both."""
    if state["phase"] != "VERIFY_ID":
        return {}

    gate = identity.check(state.get("claimed") or {}, state.get("party_id"))
    out = {"gate": gate, "party_id": gate["party_id"], "verified": gate["verified"]}

    # Count newly wrong answers, so correcting a typo is not charged twice.
    previously_wrong = set((state.get("gate") or {}).get("mismatched", []))
    out["bad_attempts"] = state.get("bad_attempts", 0) + len(
        set(gate["mismatched"]) - previously_wrong)

    if not gate["verified"]:
        return {**out, "phase": "VERIFY_ID"}

    if state.get("caller_role") != "representative":
        return {**out, "phase": "RESOLVE_INTENT"}

    record = consent.authorized(state.get("rep_name"), gate["party_id"])
    if not record:
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

    return {**out, "phase": "RESOLVE_INTENT" if status == "approved" else "VERIFY_ID"}


def resolve_intent(state: AgentState) -> dict:
    """Pin the claim the caller means, or hand back a shortlist to choose from."""
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
    """Collect the facts and approved wording for the question just asked."""
    claim = claims.get(state.get("case_id"))
    if not claim:
        return {"phase": "RESOLVE_INTENT", "case_id": None, "grounding": {}}

    text = state["messages"][-1].content if state["messages"] else ""
    hints = state.get("hints") or {}

    # The latest question sets the intent, not the one the claim was pinned on.
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


def post_process(state: AgentState) -> dict:
    """Offer an emailed summary, then act on whichever answer comes back."""
    payload = summary.build(state)
    if not payload:
        return {"phase": "POST_PROCESS", "closed": True,
                "grounding": {"closing": True}}

    choice = state.get("email_choice")

    if choice == "skip":
        return {"phase": "POST_PROCESS", "closed": True,
                "grounding": {"closing": True, "email": "skipped"}}

    if choice == "send" and not state.get("email_sent"):
        receipt = summary.send(payload, summary.email_body(payload))
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
    """Choose this turn's brief. Order matters: the exits come first."""
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


def _complete(messages):
    """One model call, trimmed. Empty string if it returns nothing."""
    return (llm().invoke(messages).text or "").strip()


def respond(state: AgentState) -> dict:
    """The one node that produces text the caller sees.

    It works from the brief it is handed and never reads a fixture, so a
    fact no brief mentions cannot be leaked here.
    """
    ground = state.get("grounding") or {}

    # A representative needs approved consent on top of identity.
    cleared = state["verified"] and (
        state.get("caller_role") != "representative"
        or state.get("consent_status") == "approved"
    )

    brief = _brief_for(state, ground, cleared)
    if cleared and state.get("caller_role") == "representative":
        brief += briefs.representative_note(state)

    brief = briefs.mood_note(state, cleared) + brief

    messages = [
        SystemMessage(content=RESPOND_PROMPT),
        *state["messages"][-8:],
        SystemMessage(content=f"[internal, not visible to caller]\n{brief}"),
    ]

    # An empty completion usually clears on a second attempt.
    text = _complete(messages) or _complete(messages) or FALLBACK_REPLY
    return {"messages": [AIMessage(content=text)]}
