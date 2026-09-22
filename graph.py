from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from nodes import (extract, post_process, process_case, resolve_intent,
                   respond, verify)
from state import AgentState

GREETING = (
    "Thanks for calling claims support. Before I can pull anything up I'll need "
    "to confirm who I'm speaking with. How can I help you today?"
)


def route(state: AgentState) -> str:
    """Pick the handler for this turn. Phase decides -- never the model.

    The scope guard runs before any phase handler, so an off-topic message
    cannot be mistaken for an identity answer or a claim question.
    """
    # A request for a person ends the automated call, from any phase.
    if state.get("wants_human"):
        return "respond"
    if state.get("offtopic"):
        return "respond"

    if state["phase"] == "VERIFY_ID":
        return "verify"
    if state["phase"] == "RESOLVE_INTENT":
        return "resolve_intent"
    # A caller working one claim can ask for another. Send them back through
    # selection rather than leaving the old claim pinned.
    if state["phase"] == "PROCESS_CASE" and state.get("switch_requested"):
        return "resolve_intent"
    if state["phase"] == "PROCESS_CASE":
        # A caller who says they are done moves to the closing offer.
        return "post_process" if state.get("wrap_up") else "process_case"
    if state["phase"] == "POST_PROCESS":
        return "post_process"
    return "respond"


def build_graph():
    g = StateGraph(AgentState)

    g.add_node("extract", extract)
    g.add_node("verify", verify)
    g.add_node("resolve_intent", resolve_intent)
    g.add_node("process_case", process_case)
    g.add_node("post_process", post_process)
    g.add_node("respond", respond)

    g.add_edge(START, "extract")
    g.add_conditional_edges("extract", route,
                            ["verify", "resolve_intent", "process_case",
                             "post_process", "respond"])

    # Verification that clears this turn falls straight through to intent
    # resolution, so the caller is not made to repeat what they already said.
    g.add_conditional_edges(
        "verify",
        lambda s: "resolve_intent" if s["phase"] == "RESOLVE_INTENT" else "respond",
        ["resolve_intent", "respond"],
    )

    # A claim pinned this turn falls straight through to answering, so the
    # caller is not told to hold for a lookup that has already happened.
    g.add_conditional_edges(
        "resolve_intent",
        lambda s: "process_case" if s.get("case_id") else "respond",
        ["process_case", "respond"],
    )
    g.add_edge("process_case", "respond")
    g.add_edge("post_process", "respond")
    g.add_edge("respond", END)

    return g.compile(checkpointer=MemorySaver())


def initial_state():
    return {
        "phase": "VERIFY_ID",
        "party_id": None,
        "claimed": {},
        "verified": False,
        "gate": {},
        "caller_role": None,
        "rep_name": None,
        "relationship": None,
        "authorized": None,
        "consent_status": None,
        "consent_polls": 0,
        "unauthorized_turns": 0,
        "hints": {},
        "intent": None,
        "case_id": None,
        "switch_requested": False,
        "discussed": [],
        "offtopic": False,
        "offtopic_strikes": 0,
        "wrap_up": False,
        "wants_human": False,
        "email_offered": False,
        "email_choice": None,
        "email_sent": False,
        "closed": False,
        "grounding": {},
    }