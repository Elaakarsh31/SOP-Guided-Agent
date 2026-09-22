"""HTTP wrapper around the SOP agent.

Sessions are LangGraph threads. The checkpointer already persists state per
thread_id, so there is no session store here -- the browser supplies an id
and the graph loads whatever that call had.
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
from nodes import CURRENT_KEY, MissingKey

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Insurance Claims SOP Agent")
agent = build_graph()


def thread(session_id):
    return {"configurable": {"thread_id": session_id}}


class StartResponse(BaseModel):
    session_id: str
    greeting: str


class ChatRequest(BaseModel):
    session_id: str
    message: str
    # Optional. Blank means use the key the server was started with.
    api_key: str | None = None


def public_state(values):
    """What the debug panel is allowed to see.

    This is a test harness, so it shows the machinery. A production build
    would not expose gate internals to the browser.
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
    if not req.message.strip():
        raise HTTPException(400, "Message is empty.")

    cfg = thread(req.session_id)
    if not agent.get_state(cfg).values:
        raise HTTPException(404, "Unknown session. Start a new call.")

    token = CURRENT_KEY.set((req.api_key or "").strip() or None)
    try:
        out = agent.invoke({"messages": [HumanMessage(req.message)]}, cfg)
    except MissingKey as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        # Rate limits and malformed model responses should not take the
        # page down mid-demo.
        raise HTTPException(503, f"The model call failed: {exc}") from exc
    finally:
        CURRENT_KEY.reset(token)

    return {
        "reply": out["messages"][-1].content,
        "key_source": "yours" if (req.api_key or "").strip() else "server",
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
    return {
        "ok": True,
        "model": os.getenv("SOP_MODEL", "gemini-3.5-flash-lite"),
        "server_key_set": bool(os.getenv("GEMINI_API_KEY")),
        "consent_scenario": os.getenv("SOP_CONSENT_SCENARIO", "default"),
    }


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")