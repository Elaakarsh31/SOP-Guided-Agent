"""Terminal client for the agent, running the same graph as the web server.

Commands: /state prints what the agent has worked out, /ground dumps the
grounding it was handed last turn, /quit exits.
"""

import json

from langchain_core.messages import AIMessage, HumanMessage

from graph import GREETING, build_graph, initial_state

THREAD = {"configurable": {"thread_id": "demo-session"}}


def print_state(s):
    """Print the interesting parts of state between turns."""
    g = s.get("gate") or {}
    print(f"\n  phase      {s['phase']}")
    print(f"  party_id   {s['party_id']}   verified {s['verified']}")
    print(f"  claimed    {s['claimed']}")
    print(f"  gate       matched {g.get('matched')} / "
          f"mismatched {g.get('mismatched')} / "
          f"needs {g.get('still_needed')}")
    print(f"  caller     {s.get('caller_role')} {s.get('rep_name') or ''} "
          f"authorized={s.get('authorized')} "
          f"consent={s.get('consent_status')} polls={s.get('consent_polls')}")
    print(f"  mood       {s.get('emotion')} refusing={s.get('refusing')} "
          f"friction={s.get('friction')} "
          f"offtopic={s.get('offtopic_strikes')} "
          f"wants_human={s.get('wants_human')}")
    print(f"  hints      {s.get('hints')}")
    print(f"  intent     {s.get('intent')}   case_id {s.get('case_id')}   "
          f"switch={s.get('switch_requested')}")
    print(f"  discussed  {s.get('discussed')}")
    print(f"  closing    wrap_up={s.get('wrap_up')} "
          f"offered={s.get('email_offered')} choice={s.get('email_choice')} "
          f"sent={s.get('email_sent')} closed={s.get('closed')}")
    print(f"  grounding  {list(s.get('grounding') or {})}\n")


def main():
    """Read a line, run a turn, print the reply, repeat."""
    app = build_graph()
    app.update_state(THREAD, {**initial_state(), "messages": [AIMessage(GREETING)]})
    print(f"\nagent: {GREETING}\n")

    while True:
        try:
            user = input("you: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user:
            continue
        if user == "/quit":
            break
        if user == "/state":
            print_state(app.get_state(THREAD).values)
            continue
        if user == "/ground":
            ground = app.get_state(THREAD).values.get("grounding") or {}
            print("\n" + json.dumps(ground, indent=2) + "\n")
            continue

        out = app.invoke({"messages": [HumanMessage(user)]}, THREAD)
        print(f"\nagent: {out['messages'][-1].content}\n")


if __name__ == "__main__":
    main()
