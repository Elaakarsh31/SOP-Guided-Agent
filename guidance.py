import json
from pathlib import Path
 
FIXTURES = Path(__file__).parent / "insurance_claims"/"fixtures"
 
 
def load_guideline():
    with open(FIXTURES / "required_document_guideline.json") as f:
        return json.load(f)
 
 
# Which claim fields each intent is allowed to surface. A status question
# should not pull the appeal deadline and the allowed maximum along with it.
INTENT_FIELDS = {
    "denial_question": ["case_id", "case_type", "status", "created_at",
                        "denial_reason", "documents_needed", "appeal_deadline"],
    "document_submission": ["case_id", "case_type", "status",
                            "documents_needed", "appeal_deadline"],
    "next_steps": ["case_id", "case_type", "status", "documents_needed",
                   "appeal_deadline"],
    "status_inquiry": ["case_id", "case_type", "status", "created_at"],
    "general_claim_question": ["case_id", "case_type", "status", "created_at",
                               "documents_needed"],
}
 
BASE_FIELDS = ["case_id", "case_type", "status", "created_at"]
 
# Amounts are only surfaced when the caller actually asks about money.
MONEY_WORDS = ("amount", "how much", "paid", "pay out", "payout", "cost",
               "reimburse", "money", "dollar", "covered", "coverage limit",
               "balance", "owe")
 
MONEY_FIELDS = ["expected_reimbursement_amount", "allowed_max_amount",
                "net_pay", "net_fee"]
 
 
def claim_facts(claim, intent, text=""):
    """The subset of the claim row the agent may state this turn."""
    fields = INTENT_FIELDS.get(intent, BASE_FIELDS)
    facts = {f: claim[f] for f in fields if f in claim}
 
    low = (text or "").lower()
    if any(w in low for w in MONEY_WORDS):
        facts.update({f: claim[f] for f in MONEY_FIELDS if f in claim})
 
    return facts
 
 
def _render(template, claim, settings):
    documents = ", ".join(claim.get("documents_needed", [])) or "the requested files"
    return (template
            .replace("{case_id}", claim["case_id"])
            .replace("{documents}", documents)
            .replace("{average_processing_time_after_submission}",
                     settings.get("average_processing_time_after_submission", {})
                     .get("en", "")))
 
 
def followup_guidance(claim, intent, text, lang="en"):
    """Guidance rows matching this intent and this question.
 
    A row qualifies when the intent is listed AND, if the row has a match_any
    keyword list, one of those keywords appears in the caller's message.
    Rows marked requires_documents are skipped for claims with nothing
    outstanding.
    """
    guide = load_guideline()
    settings = guide.get("claim_followup_settings", {})
    low = (text or "").lower()
    has_docs = bool(claim.get("documents_needed"))
 
    keyword_hits, background = [], []
    for row in guide.get("claim_followup_guidance", []):
        if intent not in row.get("intent_hints", []):
            continue
        if row.get("requires_documents") and not has_docs:
            continue
 
        keywords = row.get("match_any")
        entry = {"topic": row["topic"], "text": _render(row[lang], claim, settings)}
 
        if keywords:
            if any(k in low for k in keywords):
                entry["matched_on"] = "keyword"
                keyword_hits.append(entry)
        else:
            entry["matched_on"] = "intent"
            background.append(entry)
 
    # A row that matched the caller's actual words beats a catch-all that only
    # matched the intent. Background rows are used only when nothing specific
    # fired, or when the caller says they cannot get a document.
    if keyword_hits:
        return keyword_hits
    return background
 
 
def document_requirements(claim, lang="en"):
    """Per-document upload rules, plus the fallback when one is missing."""
    guide = load_guideline()
    docs = guide.get("document_guidance", {})
    alts = guide.get("document_alternative_guidance", {})
 
    out = []
    for name in claim.get("documents_needed", []):
        entry = {"document": name}
        # Fixture keys are more specific than the claim's short names
        # ("original pathology report" vs "pathology report").
        for key, val in docs.items():
            if name in key or key in name:
                entry["requirements"] = val[lang]
                break
        for key, val in alts.items():
            if key != "default" and (name in key or key in name):
                entry["if_unavailable"] = val[lang]
                break
        entry.setdefault("if_unavailable", alts.get("default", {}).get(lang))
        out.append(entry)
    return out
 
 
def submission_basics(claim, lang="en"):
    """General and case-type upload guidance."""
    guide = load_guideline()
    parts = [guide.get("default_guidance", {}).get(lang)]
    by_type = guide.get("case_type_guidance", {}).get(claim["case_type"], {})
    if by_type.get(lang):
        parts.append(by_type[lang])
    return [p for p in parts if p]
 
 
def fallback(lang="en"):
    return load_guideline().get("claim_followup_fallback", {}).get(lang)
 