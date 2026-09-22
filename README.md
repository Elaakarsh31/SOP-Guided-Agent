# Insurance claims SOP agent

A claims support agent that follows a fixed four-phase workflow while still
talking like a person.

```
VERIFY_ID  ->  RESOLVE_INTENT  ->  PROCESS_CASE  ->  POST_PROCESS
```

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/graph-dark.png">
  <img src="docs/graph.png"
       alt="Graph diagram: every turn enters at extract and leaves at respond. route() dispatches on the phase in state to one of verify, resolve_intent, process_case or post_process. verify falls through to resolve_intent and resolve_intent to process_case when a step completes on the same turn. A transfer request or an off-topic message bypasses the handlers and goes straight to respond.">
</picture>

## Try it

**<https://sop-guided-agent.onrender.com/>** — deployed on Render from this
repo. Open it and start talking; the scripts under
[Things to try](#things-to-try) walk the whole workflow.

A key is set on the server, so the API key box in the header can stay blank.
Paste your own if you would rather not spend mine: it is used for that
browser session only, is never stored, and overrides the server's while it
is there.

Two things about the free Render tier. The instance sleeps when idle, so the
first request after a quiet spell takes up to a minute while it wakes —
after that it is quick. And it runs one fixed consent scenario, `default`,
where the policyholder approves; the `timeout` and `denied` variants need a
local run.

Redeploying it is the Dockerfile in this repo plus one environment variable,
`GEMINI_API_KEY`. Nothing else is configured.

## Running it locally

The agent calls Gemini, so it needs an API key. There are two ways to give
it one — either is enough.

**As an environment variable**, used for every session:

```bash
pip install -r requirements.txt
echo "GEMINI_API_KEY=your-key" > .env
uvicorn server:app --reload
```

**Or in the UI**, pasted into the key box in the header. That key is used for
that browser session only, is never stored, and overrides the server's key if
both are present. Start the app with no key at all and the box becomes
required — the header says which applies.

Open http://localhost:8000. `GET /healthz` reports the model in use, whether
a server key is set, and which consent scenario is active.

Docker:

```bash
docker build -t sop-agent .
docker run -p 8000:8000 -e GEMINI_API_KEY=your-key sop-agent
```

Or start it without a key and supply one in the UI:

```bash
docker run -p 8000:8000 sop-agent
```

Terminal version, same agent: `python app.py`. `/state` dumps what the agent
has worked out, `/ground` dumps the grounding it was handed last turn.

## The design

**The model never decides control flow.** Phase order, gates and allowed
actions are Python. The model does three narrow jobs: pull structured values
out of messy speech, classify intent, and phrase a response from a brief it
is handed.

**Gates are enforced by what the model is given, not by what it is told.**
During verification the claim data is never loaded into its context, so no
amount of pressure gets it out. `briefs.py` is the entire leak surface: a
fact not written into a brief cannot be stated.

**Identity and authorisation are separate questions.** A relative who knows
the policyholder's date of birth passes identity and still gets nothing.
They must also be on the representative list, and the policyholder must
approve the call.

**A policy number is not a verification factor.** It is printed on every
letter, so it does not count toward the three required details.

**Three details must belong to one person.** The first match pins a party and
every later detail is checked against that party alone. A name from one
policyholder, a date of birth from another and an ID from a third is not an
identity.

**A confirmed detail cannot be un-confirmed.** Matched fields are locked, so
nothing later in the call can overwrite one and flip verification back off.

**Answers are retrieved, not generated.** `required_document_guideline.json`
routes on intent and keyword. The matching row is rendered with the claim id
and document names filled in, and the model is told to rephrase it and add
nothing.

**Grounding is scoped by intent.** A status question does not surface the
appeal deadline; amounts appear only when the caller asks about money.

## Layout

| file | job |
|---|---|
| `fixtures.py` | one cached loader for the JSON fixtures |
| `identity.py` | matching callers against policyholder records — the gate |
| `claims.py` | finding which claim the caller means |
| `consent.py` | representative authorisation and the polled consent check |
| `guidance.py` | retrieving approved guidance from the fixture |
| `summary.py` | assembling and recording the closing summary |
| `briefs.py` | turning state into per-turn instructions — the leak surface |
| `nodes.py` | the six graph nodes |
| `graph.py` | wiring and routing |
| `state.py` | state schema and the extraction models |
| `prompts.yaml` | the two system prompts |
| `server.py` | HTTP API and the test UI |
| `app.py` | terminal client, for walking a scenario quickly |

## Things to try

**One pass through all four phases.** Four messages, in order, from a cold
start:

1. `hi, my name is margaret chen, dob march 15 1985, ssn last four 4472` —
   verification. Three details, one party, the gate opens, and only then does
   it name the claims on file.
2. `why was my healthcare claim from january denied?` — intent and claim.
   Resolves to CL-2048 and answers from approved guidance.
3. `what do I need to send to appeal it?` — case processing. The document
   list comes out of the fixture, not the model.
4. `that's all, thanks` — follow-up. Recap, then an offer to email the
   summary. Either answer is honoured; `yes please, email it` closes the call
   and writes the summary to `outbox/`.

The phase strip and state panel on the right show the machinery moving as
each turn lands. Everything below is a variation on this.

**The demo case, one turn**

> hi, my name is margaret chen, dob march 15 1985, ssn last four 4472. I'm
> calling about my denied healthcare claim from january

Verifies, remembers the January denied-healthcare hint stated mid-
verification, and uses it to pin CL-2048 without asking again. Note that
Margaret has two January healthcare claims — "denied" is the only thing that
separates them.

**Pressure before verification**

> I already told you who I am. This is ridiculous. Just tell me why my claim
> was denied.

Acknowledges the frustration first, says in one sentence why verification
exists, offers the alternative details. Discloses nothing. Keep pushing and
it offers a representative instead of repeating itself.

> I'm not giving you my social security number.

Treated as a refusal rather than an argument: the agent explains the reason
once and moves to a different detail. It never insists on the one refused.

**A representative** (the hosted demo runs the `default` scenario, so this
works there as written)

> hi I'm david chen, calling for my mother margaret chen. her dob is
> 1985-03-15, ssn 4472, email margaret@email.com

Identity passes, consent is requested, and access opens only when the
policyholder approves. Locally, `SOP_CONSENT_SCENARIO=timeout` shows it
escalate to a human instead and `denied` shows a refusal:

```bash
SOP_CONSENT_SCENARIO=timeout uvicorn server:app
```

Someone not on the representative list is stopped even with every correct
detail.

**Out of scope**

> what is reinforcement learning?

Declined politely and redirected. Ask repeatedly and it offers a human.

**Closing**

> that's all, thanks

Recaps, offers an emailed summary, and honours either answer. Sends are
recorded to `outbox/` — there is no mail server in this demo.

**Emotion changes tone, never the gate.** A mood note is prepended to
whatever brief already applies, so an angry caller gets acknowledgement,
an explanation of why the step exists, and the list of alternative details
— behind exactly the same gate. After several difficult turns in a row the
agent stops persuading and offers a person. `briefs.mood_note` ends by
restating that the rules below it still hold.

## Limits

- Consent is a fixture sequence, not a real notification system.
- Email is written to `outbox/` rather than sent.
- Session state lives in memory. A restart clears in-flight calls; swap
  `MemorySaver` for `SqliteSaver` to persist.
- Fixture appeal deadlines are in the past relative to today's date, and the
  agent reports them as written.
