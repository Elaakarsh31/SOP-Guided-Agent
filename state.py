"""Shared state, and the shapes the extractor fills in.

The Field descriptions on the models below are part of the extraction
prompt, so changing their wording changes what the model returns.
"""

from typing import Annotated, Literal, Optional, Sequence

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

# Must stay in step with the intent_hints values in
# fixtures/required_document_guideline.json.
INTENTS = Literal[
    "denial_question",
    "status_inquiry",
    "document_submission",
    "next_steps",
    "general_claim_question",
    "out_of_scope",
    "none",
]


class AgentState(TypedDict):
    """Everything carried between turns of one call.

    Fields marked turn-scoped are rewritten by extract() every turn; the
    rest accumulate. authorized and consent_status are separate questions:
    an unauthorised caller is never asked for consent, so consent_status
    stays None.
    """

    messages: Annotated[Sequence[BaseMessage], add_messages]
    phase: Literal["VERIFY_ID", "RESOLVE_INTENT", "PROCESS_CASE", "POST_PROCESS"]

    party_id: Optional[str]
    claimed: dict
    verified: bool
    gate: dict

    caller_role: Optional[str]
    rep_name: Optional[str]
    relationship: Optional[str]
    authorized: Optional[bool]
    consent_status: Optional[str]
    consent_polls: int
    unauthorized_turns: int
    bad_attempts: int

    # Written from any phase, since callers state their business before verifying.
    hints: dict

    intent: Optional[str]
    case_id: Optional[str]
    switch_requested: bool       # turn-scoped
    discussed: list
    offtopic: bool               # turn-scoped
    offtopic_strikes: int

    emotion: Optional[str]
    refusing: bool
    friction: int                # consecutive difficult turns behind a gate

    wrap_up: bool                # turn-scoped
    wants_human: bool
    email_offered: bool
    email_choice: Optional[str]
    email_sent: bool
    closed: bool

    # The only key through which record data reaches the responder.
    grounding: dict


class Identity(BaseModel):
    """Verification details, always the policyholder's, never the caller's."""

    full_name: Optional[str] = Field(
        None, description="The POLICYHOLDER's full name as spoken. If someone is "
        "calling on their behalf, this is still the policyholder's name, never "
        "the caller's. Do not correct spelling."
    )
    dob: Optional[str] = Field(
        None, description="Date of birth as YYYY-MM-DD. Convert whatever format "
        "the caller used. '15th of March 1985' -> '1985-03-15'. Two-digit years "
        "before 30 are 20xx, otherwise 19xx."
    )
    phone: Optional[str] = Field(
        None, description="Phone as digits only, no punctuation or country code. "
        "'(650) 521-2836' -> '6505212836'."
    )
    email: Optional[str] = Field(
        None, description="Email, lowercase. 'margaret at email dot com' -> "
        "'margaret@email.com'."
    )
    id_last4: Optional[str] = Field(
        None, description="Last 4 digits of SSN or national ID as a string. "
        "Keep leading zeros: '0472' not 472."
    )
    policy_number: Optional[str] = Field(
        None, description="Policy number such as POL-9921."
    )


class Caller(BaseModel):
    """Who is on the phone, as opposed to whose policy it is."""

    caller_role: Optional[Literal["self", "representative"]] = Field(
        None, description="'representative' if calling on someone else's behalf "
        "- a relative, carer or agent. 'self' if they are the policyholder."
    )
    rep_name: Optional[str] = Field(
        None, description="The CALLER'S OWN name, only when they are calling for "
        "someone else. 'I'm David Chen calling for my mother Margaret' -> "
        "rep_name is 'David Chen' and identity.full_name is 'Margaret Chen'."
    )
    relationship: Optional[str] = Field(
        None, description="How the caller is related, e.g. son, daughter, spouse."
    )


class Mood(BaseModel):
    """How the caller sounds, judged from their wording."""

    emotion: Optional[Literal["calm", "frustrated", "angry", "anxious",
                              "confused", "upset"]] = Field(
        None, description="The caller's tone in this message. 'calm' when "
        "neutral or businesslike. Judge from what they wrote, not from the "
        "topic being serious."
    )
    refusing: Optional[bool] = Field(
        None, description="True if they decline to give something asked for - "
        "'I'm not giving you my SSN', 'why do you need that', 'I already told "
        "you'. Not true merely because they are annoyed."
    )


class Closing(BaseModel):
    """Signals about ending the call, extracted from the latest message."""

    wrap_up: Optional[bool] = Field(
        None, description="True if the caller signals they are finished - "
        "'that's all', 'nothing else', 'thanks, that helps', 'no more "
        "questions'. A new question is not a wrap-up."
    )
    wants_human: Optional[bool] = Field(
        None, description="True ONLY if the caller explicitly asks to be "
        "connected to a person: 'transfer me', 'let me speak to someone', "
        "'get me an agent', 'I want a human'. Anger, insults, or demands "
        "about the claim itself - 'just approve it', 'pass my claim', 'this "
        "is ridiculous' - are NOT a request for a person. When in doubt, "
        "false."
    )
    email_choice: Optional[Literal["send", "skip"]] = Field(
        None, description="Only when an emailed summary has been offered. "
        "'send' if they accept - yes, please, sure, go ahead. 'skip' if they "
        "decline - no thanks, not needed, don't bother."
    )


class Request(BaseModel):
    """What the caller wants, and which claim they mean."""

    intent: Optional[INTENTS] = Field(
        None, description="What the caller wants. 'next_steps' for 'what now', "
        "'what do I do', 'what happens next', 'what should I be doing'. "
        "'document_submission' for how or where to send something. "
        "'denial_question' for why a claim was refused. 'status_inquiry' for "
        "where a claim stands. 'out_of_scope' for anything unrelated to "
        "insurance claims. 'none' if they stated no request."
    )
    case_id: Optional[str] = Field(
        None, description="Claim id if spoken, e.g. CL-2048."
    )
    case_type: Optional[Literal["healthcare", "dental", "auto"]] = Field(
        None, description="Kind of claim mentioned. 'medical'/'hospital'/'doctor' "
        "-> healthcare. 'car'/'accident'/'collision' -> auto."
    )
    status: Optional[Literal["denied", "open", "closed"]] = Field(
        None, description="Claim status the caller mentioned. 'rejected'/'turned "
        "down'/'refused' -> denied. 'settled'/'paid' -> closed."
    )
    period: Optional[str] = Field(
        None, description="When the claim was filed, if mentioned. Prefer "
        "'YYYY-MM' when the year is clear, otherwise the month name alone, "
        "e.g. 'january'."
    )
    switch_case: Optional[bool] = Field(
        None, description="True only if the caller wants to move to a DIFFERENT "
        "claim than the one being discussed - 'what about my auto claim', "
        "'actually a different one', 'let's talk about the dental claim'. "
        "A follow-up question about the same claim is not a switch."
    )


class Extraction(BaseModel):
    """One model call, five sections, each copied into its own part of state."""

    identity: Identity = Field(default_factory=Identity)
    caller: Caller = Field(default_factory=Caller)
    request: Request = Field(default_factory=Request)
    mood: Mood = Field(default_factory=Mood)
    closing: Closing = Field(default_factory=Closing)