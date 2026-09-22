"""The SOP wired up as a graph, plus the state a fresh call starts from."""

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
    """Pick the handler for this turn from the phase in state.

    A request for a person and an off-topic message both short-circuit the
    phase handlers, from anywhere in the call.
    """
    if state.get("wants_human") or state.get("offtopic"):
        return "respond"

    if state["phase"] == "VERIFY_ID":
        return "verify"
    if state["phase"] == "RESOLVE_INTENT":
        return "resolve_intent"
    if state["phase"] == "PROCESS_CASE":
        if state.get("switch_requested"):
            return "resolve_intent"
        return "post_process" if state.get("wrap_up") else "process_case"
    if state["phase"] == "POST_PROCESS":
        return "post_process"
    return "respond"


def build_graph():
    """Assemble the SOP graph.

    Every turn starts at extract and ends at respond; route() decides what
    happens in between.
    """
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

    # A step completing this turn falls through, so nothing is repeated.
    g.add_conditional_edges(
        "verify",
        lambda s: "resolve_intent" if s["phase"] == "RESOLVE_INTENT" else "respond",
        ["resolve_intent", "respond"],
    )
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
    """A blank call, with every key set so no node has to guess a default."""
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
        "bad_attempts": 0,
        "hints": {},
        "intent": None,
        "case_id": None,
        "switch_requested": False,
        "discussed": [],
        "offtopic": False,
        "offtopic_strikes": 0,
        "emotion": None,
        "refusing": False,
        "friction": 0,
        "wrap_up": False,
        "wants_human": False,
        "email_offered": False,
        "email_choice": None,
        "email_sent": False,
        "closed": False,
        "grounding": {},
    }
