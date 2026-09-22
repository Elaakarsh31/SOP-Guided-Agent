"""Decides what may be said about a claim, and supplies the approved wording.

claim_facts() picks the subset of the claim row the question justifies.
Everything else comes out of the guideline fixture with its placeholders
filled in, so no sentence here is generated.
"""

from fixtures import load


def load_guideline():
    return load("required_document_guideline.json")


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

MONEY_WORDS = ("amount", "how much", "paid", "pay out", "payout", "cost",
               "reimburse", "money", "dollar", "covered", "coverage limit",
               "balance", "owe")

MONEY_FIELDS = ["expected_reimbursement_amount", "allowed_max_amount",
                "net_pay", "net_fee"]


def claim_facts(claim, intent, text=""):
    """The part of the claim row the agent may state this turn.

    Amounts are held back until the caller's own words raise money.
    """
    fields = INTENT_FIELDS.get(intent, BASE_FIELDS)
    facts = {f: claim[f] for f in fields if f in claim}

    low = (text or "").lower()
    if any(w in low for w in MONEY_WORDS):
        facts.update({f: claim[f] for f in MONEY_FIELDS if f in claim})

    return facts


def _render(template, claim, settings):
    """Fill the placeholders in a guideline string from this claim."""
    documents = ", ".join(claim.get("documents_needed", [])) or "the requested files"
    processing_time = settings.get(
        "average_processing_time_after_submission", {}).get("en", "")
    return (template
            .replace("{case_id}", claim["case_id"])
            .replace("{documents}", documents)
            .replace("{average_processing_time_after_submission}", processing_time))


def followup_guidance(claim, intent, text, lang="en"):
    """The approved lines that answer this question.

    A row qualifies on intent, and rows carrying a match_any list also need
    one of those keywords in the message. Keyword hits win outright, since
    they were written for what the caller actually said.
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

        entry = {"topic": row["topic"], "text": _render(row[lang], claim, settings)}
        keywords = row.get("match_any")
        if not keywords:
            entry["matched_on"] = "intent"
            background.append(entry)
        elif any(k in low for k in keywords):
            entry["matched_on"] = "keyword"
            keyword_hits.append(entry)

    return keyword_hits or background


def _best_match(table, name, lang):
    """Look up a document by loose name match.

    Claims record short names ("pathology report") against guideline keys
    written out in full ("original pathology report").
    """
    for key, value in table.items():
        if key == "default":
            continue
        if name in key or key in name:
            return value.get(lang)
    return None


def document_requirements(claim, lang="en"):
    """What each outstanding document must contain, and what to do without it."""
    guide = load_guideline()
    docs = guide.get("document_guidance", {})
    alts = guide.get("document_alternative_guidance", {})
    default_alt = alts.get("default", {}).get(lang)

    out = []
    for name in claim.get("documents_needed", []):
        entry = {
            "document": name,
            "requirements": _best_match(docs, name, lang),
            "if_unavailable": _best_match(alts, name, lang) or default_alt,
        }
        out.append({k: v for k, v in entry.items() if v})
    return out


def submission_basics(claim, lang="en"):
    """How to send documents in: the general steps, plus any for this claim type."""
    guide = load_guideline()
    parts = [guide.get("default_guidance", {}).get(lang)]
    by_type = guide.get("case_type_guidance", {}).get(claim["case_type"], {})
    parts.append(by_type.get(lang))
    return [p for p in parts if p]


def fallback(lang="en"):
    """Wording for a question no guidance row covers."""
    return load_guideline().get("claim_followup_fallback", {}).get(lang)
