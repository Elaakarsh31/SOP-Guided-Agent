from typing import Annotated, Literal, Optional, Sequence

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

# These labels must match the intent_hints values in
# fixtures/required_document_guideline.json exactly, or PROCESS_CASE will
# match no guidance rows and silently fall back to generic wording.
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
    messages: Annotated[Sequence[BaseMessage], add_messages]
    phase: Literal["VERIFY_ID", "RESOLVE_INTENT", "PROCESS_CASE", "POST_PROCESS"]

    # --- identity ---
    party_id: Optional[str]      # pinned on first match; scoring never drifts
    claimed: dict                # accumulates across turns
    verified: bool
    gate: dict                   # rebuilt each turn by verify; field names only

    # --- third-party callers ---
    caller_role: Optional[str]        # "self" | "representative"
    rep_name: Optional[str]           # the caller's own name, when acting for someone
    relationship: Optional[str]       # from the representative record, once matched

    # Two separate questions, deliberately two keys. If authorized is False we
    # never asked for consent at all, so consent_status stays None.
    authorized: Optional[bool]        # on the policyholder's representative list?
    consent_status: Optional[str]     # pending | approved | timeout | denied
    consent_polls: int
    unauthorized_turns: int           # how often we have explained the dead end

    # --- parked memory ---
    # Written from ANY phase. Callers state why they are calling long before
    # they are verified, and that has to survive until RESOLVE_INTENT.
    hints: dict

    # --- case ---
    intent: Optional[str]
    case_id: Optional[str]
    switch_requested: bool       # turn-scoped: caller wants a different claim
    discussed: list              # intents covered, for the closing summary
    offtopic: bool               # turn-scoped: this message is out of scope
    offtopic_strikes: int        # consecutive off-topic turns

    # --- closing ---
    wrap_up: bool                # turn-scoped: caller signalled they are done
    wants_human: bool            # caller asked for a person; terminal
    email_offered: bool
    email_choice: Optional[str]  # "send" | "skip"
    email_sent: bool
    closed: bool

    # --- the only channel through which record data reaches the model ---
    grounding: dict


class Identity(BaseModel):
    """Details belonging to the POLICYHOLDER, whoever is on the phone."""

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
    """Who is actually on the phone, as distinct from whose policy it is."""

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


class Closing(BaseModel):
    """Signals about ending the call, extracted from the latest message."""

    wrap_up: Optional[bool] = Field(
        None, description="True if the caller signals they are finished - "
        "'that's all', 'nothing else', 'thanks, that helps', 'no more "
        "questions'. A new question is not a wrap-up."
    )
    wants_human: Optional[bool] = Field(
        None, description="True if the caller asks to speak to a person - "
        "'transfer me', 'I want a human', 'get me an agent', 'connect me'. "
        "Not true merely because they are frustrated."
    )
    email_choice: Optional[Literal["send", "skip"]] = Field(
        None, description="Only when an emailed summary has been offered. "
        "'send' if they accept - yes, please, sure, go ahead. 'skip' if they "
        "decline - no thanks, not needed, don't bother."
    )


class Request(BaseModel):
    """What the caller wants, and which claim they mean."""

    intent: Optional[INTENTS] = Field(
        None, description="What the caller wants. 'out_of_scope' for anything "
        "unrelated to insurance claims. 'none' if they stated no request."
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
    """Everything worth pulling out of one caller message.

    One call, three sections. The nesting decides where each field lands in
    state, so a field cannot silently end up in the wrong dict.
    """

    identity: Identity = Field(default_factory=Identity)
    caller: Caller = Field(default_factory=Caller)
    request: Request = Field(default_factory=Request)
    closing: Closing = Field(default_factory=Closing)