"""HTTP wrapper around the SOP agent.

A session is a LangGraph thread. The checkpointer already persists state
per thread_id, so there is no session store in here: the browser sends an
id back and the graph reloads whatever that call had.
"""

import os
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from graph import GREETING, build_graph, initial_state
from nodes import CURRENT_KEY, DEFAULT_MODEL

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Insurance Claims SOP Agent")
agent = build_graph()


def thread(session_id):
    """The LangGraph config that selects one caller's conversation."""
    return {"configurable": {"thread_id": session_id}}


class StartResponse(BaseModel):
    session_id: str
    greeting: str


class ChatRequest(BaseModel):
    session_id: str
    message: str
    api_key: str | None = None   # blank falls back to the server's key


def public_state(values):
    """What the debug panel is allowed to see.

    This is a test harness and the panel exists to show the machinery
    working, grounding included. A production build would not put gate
    internals on the wire.
    """
    gate = values.get("gate") or {}
    ground = values.get("grounding") or {}
    return {
        "phase": values.get("phase"),
        "verified": values.get("verified"),
        "party_id": values.get("party_id"),
        "claimed": values.get("claimed") or {},
        "matched": gate.get("matched", []),
        "still_needed": gate.get("still_needed", []),
        "caller_role": values.get("caller_role"),
        "rep_name": values.get("rep_name"),
        "authorized": values.get("authorized"),
        "consent_status": values.get("consent_status"),
        "consent_polls": values.get("consent_polls", 0),
        "hints": values.get("hints") or {},
        "intent": values.get("intent"),
        "case_id": values.get("case_id"),
        "discussed": values.get("discussed") or [],
        "offtopic_strikes": values.get("offtopic_strikes", 0),
        "emotion": values.get("emotion"),
        "refusing": values.get("refusing"),
        "friction": values.get("friction", 0),
        "email_offered": values.get("email_offered"),
        "email_choice": values.get("email_choice"),
        "email_sent": values.get("email_sent"),
        "closed": values.get("closed"),
        "grounding_keys": list(ground),
        "grounding": ground,
    }


@app.post("/api/start", response_model=StartResponse)
def start():
    """Open a new call. Each session is an independent thread."""
    session_id = uuid.uuid4().hex
    agent.update_state(
        thread(session_id),
        {**initial_state(), "messages": [AIMessage(GREETING)]},
    )
    return {"session_id": session_id, "greeting": GREETING}


@app.post("/api/chat")
def chat(req: ChatRequest):
    """One turn of a call: the caller's message in, the agent's reply out."""
    if not req.message.strip():
        raise HTTPException(400, "Message is empty.")

    cfg = thread(req.session_id)
    if not agent.get_state(cfg).values:
        raise HTTPException(404, "Unknown session. Start a new call.")

    token = CURRENT_KEY.set((req.api_key or "").strip() or None)
    try:
        out = agent.invoke({"messages": [HumanMessage(req.message)]}, cfg)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        # Rate limits and bad model replies become a 503 the page can show.
        raise HTTPException(503, f"The model call failed: {exc}") from exc
    finally:
        CURRENT_KEY.reset(token)

    return {
        "reply": out["messages"][-1].content,
        "state": public_state(agent.get_state(cfg).values),
    }


@app.get("/api/state/{session_id}")
def state(session_id: str):
    values = agent.get_state(thread(session_id)).values
    if not values:
        raise HTTPException(404, "Unknown session.")
    return public_state(values)


@app.get("/healthz")
def healthz():
    """Enough for the page to tell the tester whether they need their own key."""
    return {
        "ok": True,
        "model": os.getenv("SOP_MODEL", DEFAULT_MODEL),
        "server_key_set": bool(os.getenv("GEMINI_API_KEY")),
        "consent_scenario": os.getenv("SOP_CONSENT_SCENARIO", "default"),
    }


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


# Mounted last so the routes above keep priority.


app.mount("/static", StaticFiles(directory=STATIC), name="static")