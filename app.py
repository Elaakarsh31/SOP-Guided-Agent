from langchain_core.messages import AIMessage, HumanMessage

from graph import GREETING, build_graph, initial_state

THREAD = {"configurable": {"thread_id": "demo-session"}}


def main():
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
        if user in ("/state", "\\state", "state"):
            s = app.get_state(THREAD).values
            print(f"\n  phase      {s['phase']}")
            print(f"  party_id   {s['party_id']}   verified {s['verified']}")
            print(f"  claimed    {s['claimed']}")
            print(f"  gate       {(s.get('gate') or {}).get('matched')} "
                  f"/ needs {(s.get('gate') or {}).get('still_needed')}")
            print(f"  caller     {s.get('caller_role')} {s.get('rep_name') or ''} "
                  f"authorized={s.get('authorized')} "
                  f"consent={s.get('consent_status')} polls={s.get('consent_polls')}")
            print(f"  hints      {s.get('hints')}")
            print(f"  intent     {s.get('intent')}   case_id {s.get('case_id')}   "
                  f"switch={s.get('switch_requested')}")
            print(f"  discussed  {s.get('discussed')}")
            print(f"  closing    wrap_up={s.get('wrap_up')} "
                  f"offered={s.get('email_offered')} choice={s.get('email_choice')} "
                  f"sent={s.get('email_sent')} closed={s.get('closed')}")
            g = s.get('grounding') or {}
            print(f"  grounding  keys={list(g)}\n")
            continue
        out = app.invoke({"messages": [HumanMessage(user)]}, THREAD)
        print(f"\nagent: {out['messages'][-1].content}\n")


if __name__ == "__main__":
    main()