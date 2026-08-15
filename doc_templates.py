"""
doc_templates.py — the document template library.

The ailawyer.pro answer, done our way: they ship 200 blank forms; we
ship nine documents that KNOW the business — the client comes from the
records, the voice comes from the voice profile, the money terms feed
the same approve → PDF → e-sign chain that already executes documents.

Reliability model (the reason this isn't just "ask Chief to write it"):

  fixed sections    — the load-bearing clauses, written here, byte-for-
                      byte reproducible. A retainer's replenishment
                      clause or an NDA's exclusions list must never
                      depend on a model's mood.
  drafted sections  — the personal paragraphs (an opener, a program
                      description) where the practitioner's voice
                      matters. One model call fills them; every drafted
                      section carries a `fallback` so generation
                      SUCCEEDS with the model down, degraded to neutral
                      wording rather than failing.
  conditional       — a section with `requires: <field>` renders only
                      when that field was given (no deposit → no
                      deposit clause, not a blank).

Substitution: {placeholders} resolve from the merged variable map
(business, contact, date, field values). _SafeMap leaves unknown keys
visible — a template typo shows itself in review instead of silently
rendering an empty hole in a contract.

Vertical fit: `suggested_for` RANKS the picker per business type; it
never gates. A barber can send an NDA; a lawyer's own paper doesn't
carry the attorney-review line (they are the attorney — everyone
else's does).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# ─── Shared blocks ───────────────────────────────────────────────────

_SIGNATURE_BLOCK = """ACCEPTED AND AGREED

{business_name}

By: ____________________________     Date: ______________
Name: {practitioner_name}
Title: {practitioner_title}


{client_name}

By: ____________________________     Date: ______________
Name: {client_name}
"""

# Appended for every business type EXCEPT lawyer (they are the counsel).
_REVIEW_NOTE = (
    "NOTE: This document was generated from a template and is not legal "
    "advice. For significant agreements, consider having an attorney "
    "review it for your situation.")


def sig(text: str) -> Dict[str, Any]:
    return {"kind": "fixed", "heading": None, "text": text}


def fixed(heading: Optional[str], text: str,
          requires: Optional[str] = None,
          requires_value: Optional[tuple] = None) -> Dict[str, Any]:
    """requires: render only when that field is non-empty.
    requires_value: ("field", "value") — render only when the field
    equals the value (the fee-model branch mechanism). Both may be set;
    they AND together."""
    d: Dict[str, Any] = {"kind": "fixed", "heading": heading, "text": text}
    if requires:
        d["requires"] = requires
    if requires_value:
        d["requires_value"] = {"field": requires_value[0],
                               "value": requires_value[1]}
    return d


def drafted(heading: Optional[str], brief: str, fallback: str) -> Dict[str, Any]:
    return {"kind": "drafted", "heading": heading,
            "brief": brief, "fallback": fallback}


def field(key: str, label: str, *, type_: str = "text", required: bool = False,
          placeholder: str = "", default: str = "",
          sticky: bool = False) -> Dict[str, Any]:
    """sticky=True marks a BUSINESS-STANDARD term (your hourly fee, your
    state, your cancellation window): once the practitioner fills it the
    first time, it is saved to the business's doc_defaults and pre-fills
    every later document — the first contract teaches the system. Facts
    about one engagement (a scope, an amount owed, an NDA's purpose) are
    NEVER sticky: reusing them would write one client's terms into
    another client's contract."""
    return {"key": key, "label": label, "type": type_, "required": required,
            "placeholder": placeholder, "default": default, "sticky": sticky}


def select_field(key: str, label: str, options: List[str], *,
                 required: bool = False, default: str = "",
                 sticky: bool = False) -> Dict[str, Any]:
    """A typed choice — the dialog renders a dropdown, Chief gets an
    enumerated set, and requires_value sections branch on it."""
    f = field(key, label, required=required, default=default, sticky=sticky)
    f["type"] = "select"
    f["options"] = options
    return f


def list_field(key: str, label: str, *, required: bool = False,
               placeholder: str = "", sticky: bool = False) -> Dict[str, Any]:
    """One item per line in the form; renders as a structured list in
    the document (deliverables, milestones)."""
    f = field(key, label, type_="textarea", required=required,
              placeholder=placeholder, sticky=sticky)
    f["type"] = "list"
    return f


# ─── The nine ────────────────────────────────────────────────────────

TEMPLATES: List[Dict[str, Any]] = [

    # ── 1. Engagement Letter ─────────────────────────────────────────
    {
        "id": "engagement_letter",
        "numbered": True,
        "title": "Engagement Letter",
        "subtitle": "Scope, Fees & How It Ends",
        "description": "Open a new client relationship properly: scope, fees, "
                       "responsibilities, and how it ends.",
        "category": "client",
        "suggested_for": ["lawyer", "consultant", "accountant"],
        "fields": [
            field("scope", "Scope of the engagement", type_="textarea", required=True,
                  placeholder="e.g. Representation in the negotiation and closing of the Northside lease"),
            field("fee", "Fee", required=True, sticky=True,
                  placeholder="e.g. $300/hour — or a flat $2,500 (just the amount; structure goes below)"),
            select_field("fee_model", "How the fee works",
                         ["flat_fee", "hourly", "retainer", "milestone"],
                         sticky=True),
            field("payment_terms", "Payment structure (optional)", type_="textarea",
                  sticky=True, default="",
                  placeholder="e.g. 50% due on signing; the remaining 50% due at completion."),
            field("deposit", "Retainer deposit amount (retainer model only)",
                  sticky=True, placeholder="e.g. $1,500"),
            field("expense_cap", "Written approval needed for costs over (optional)",
                  sticky=True, placeholder="e.g. $50"),
            field("state", "Governing state (optional)", sticky=True, placeholder="e.g. Georgia"),
            field("venue_county", "Venue county (optional)", sticky=True,
                  placeholder="e.g. Oakland"),
        ],
        "sections": [
            drafted(None,
                    "A one-paragraph professional opener: thank {client_name} for "
                    "engaging {business_name}, confirm this letter sets out the "
                    "terms, and set a confident, welcoming tone.",
                    "Dear {client_name},\n\nThank you for engaging {business_name}. "
                    "This letter confirms the terms of our engagement. Please read "
                    "it carefully and sign below to begin."),
            fixed("SCOPE OF ENGAGEMENT",
                  "{business_name} will provide the following services:\n\n{scope}\n\n"
                  "Services outside this scope are not covered by this letter and "
                  "will be agreed in writing before any additional work begins."),
            fixed("FEES AND BILLING",
                  "Our fee for this engagement is: {fee}. Invoices are payable upon "
                  "receipt unless stated otherwise on the invoice. Reasonable "
                  "out-of-pocket costs incurred on your behalf (such as "
                  "{expense_examples}) are billed at cost{expense_cap_clause}."),
            # ── Payment structure branches on the fee model. The
            # trust-drawdown language survives ONLY where it is true —
            # a retainer. A flat fee has no "unused balance" to argue
            # about, and the clause now says what a flat fee means.
            fixed("PAYMENT STRUCTURE",
                  "{payment_terms}\n\n"
                  "This is a flat-fee engagement. Any deposit or initial payment "
                  "is a milestone payment toward the flat fee and is not "
                  "refundable once work has begun. The remaining balance is due "
                  "at completion of the scope described above, and final work "
                  "product is released on receipt of payment in full.",
                  requires_value=("fee_model", "flat_fee")),
            fixed("PAYMENT STRUCTURE",
                  "Time is billed at {fee} and invoiced as the work proceeds. "
                  "{payment_terms}",
                  requires_value=("fee_model", "hourly")),
            fixed("PAYMENT STRUCTURE",
                  "Payment is tied to the milestones below. Each payment is due "
                  "on delivery of its milestone, and work on the next milestone "
                  "may pause until the prior payment is received.\n\n{payment_terms}",
                  requires_value=("fee_model", "milestone")),
            fixed("RETAINER",
                  "An initial deposit of {deposit} is due on signing and will be "
                  "held and applied against fees and costs as they are incurred, "
                  "in accordance with the rules applicable to client funds. If the "
                  "deposit is exhausted before the engagement concludes, we may "
                  "request that it be replenished. Any unused balance is returned "
                  "promptly at the end of the engagement.",
                  requires="deposit", requires_value=("fee_model", "retainer")),
            fixed("YOUR RESPONSIBILITIES",
                  "You agree to provide complete and accurate information, respond "
                  "to requests in a timely way, and tell us promptly about anything "
                  "that could affect the engagement. Our work depends on what you "
                  "give us."),
            fixed("COMMUNICATION",
                  "We will keep you informed of significant developments and "
                  "respond to inquiries within a reasonable time. You will be "
                  "consulted before decisions that materially affect the outcome "
                  "or the cost."),
            fixed("CONFIDENTIALITY",
                  "We treat the information you share with us in this engagement "
                  "as confidential, using it only to perform the services and "
                  "disclosing it only with your permission, to those who need it "
                  "to do the work, or as required by law. Nothing in this agreement prevents either party from reporting suspected unlawful conduct to a government agency or from making disclosures protected by law."),
            fixed("ENDING THE ENGAGEMENT",
                  "Either of us may end this engagement with written notice. You "
                  "remain responsible for fees and costs incurred through the "
                  "effective date of termination, and we will return your "
                  "{work_materials_term} and any unused deposit promptly."),
            fixed("GOVERNING LAW",
                  "This agreement is governed by the laws of "
                  "{state_full}.{venue_clause}",
                  requires="state"),
            sig(_SIGNATURE_BLOCK),
        ],
    },

    # ── 2. Retainer Agreement ────────────────────────────────────────
    {
        "id": "retainer_agreement",
        "numbered": True,
        "title": "Retainer Agreement",
        "subtitle": "Monthly Fee, Overage & Renewal",
        "description": "An ongoing relationship on a monthly retainer: what's "
                       "included, replenishment, and renewal.",
        "category": "client",
        "suggested_for": ["lawyer", "consultant", "coach", "creative"],
        "fields": [
            field("services", "Services covered by the retainer", type_="textarea", required=True,
                  placeholder="e.g. Ongoing contract review, employment questions, and up to two negotiations per month"),
            field("monthly_fee", "Monthly retainer fee", required=True, sticky=True,
                  placeholder="e.g. $1,200/month"),
            field("overage", "Rate for work beyond the retainer (optional)", sticky=True,
                  placeholder="e.g. $250/hour"),
            field("state", "Governing state (optional)", sticky=True, placeholder="e.g. Georgia"),
        ],
        "sections": [
            drafted(None,
                    "One short professional paragraph: {business_name} will serve "
                    "{client_name} on an ongoing retainer basis; this agreement "
                    "sets the terms.",
                    "This Retainer Agreement is between {business_name} and "
                    "{client_name}, effective on the date of the last signature "
                    "below."),
            fixed("RETAINED SERVICES",
                  "During each monthly term, {business_name} will provide:\n\n"
                  "{services}\n\nWork outside this description is not covered by "
                  "the retainer and will be quoted before it begins."),
            fixed("RETAINER FEE",
                  "The retainer fee is {monthly_fee}, due in advance on the first "
                  "day of each monthly term. The fee covers availability and the "
                  "services described above; it is earned as the month proceeds "
                  "and unused capacity does not roll over unless agreed in "
                  "writing."),
            fixed("WORK BEYOND THE RETAINER",
                  "Work beyond the retained scope is billed at {overage}, invoiced "
                  "monthly and payable upon receipt. We will tell you before "
                  "beginning any work that will be billed outside the retainer.",
                  requires="overage"),
            fixed("TERM AND RENEWAL",
                  "This agreement runs month to month and renews automatically. "
                  "Either party may end it with 30 days' written notice. Fees for "
                  "the current term are earned and non-refundable once the term "
                  "has begun, except any unused advance deposit, which is "
                  "returned."),
            fixed("GOVERNING LAW",
                  "This agreement is governed by the laws of {state_full}.{venue_clause}",
                  requires="state"),
            sig(_SIGNATURE_BLOCK),
        ],
    },

    # ── 3. Service Agreement ─────────────────────────────────────────
    {
        "id": "service_agreement",
        "numbered": True,
        "title": "Service Agreement",
        "subtitle": "Deliverables, Payment & Ownership",
        "description": "One project, cleanly scoped: deliverables, payment, "
                       "changes, and who owns the work.",
        "category": "client",
        "suggested_for": ["contractor", "creative", "personal_services", "consultant"],
        "fields": [
            field("services", "Services / deliverables", type_="textarea", required=True,
                  placeholder="e.g. Design and install kitchen cabinetry per the attached estimate"),
            field("price", "Price and payment schedule", required=True,
                  placeholder="e.g. $4,800 — half on signing, half on completion"),
            field("timeline", "Timeline (optional)",
                  placeholder="e.g. Work begins March 3 and completes by March 21"),
            field("state", "Governing state (optional)", sticky=True, placeholder="e.g. Georgia"),
        ],
        "sections": [
            drafted(None,
                    "One short paragraph: {business_name} agrees to perform the "
                    "services below for {client_name} on these terms.",
                    "This Service Agreement is between {business_name} and "
                    "{client_name}. {business_name} agrees to perform the services "
                    "described below on the terms set out here."),
            fixed("SERVICES",
                  "{services}\n\nAnything not listed above is out of scope. "
                  "Additional work is agreed in writing (a message counts) with "
                  "its price before it begins."),
            fixed("PAYMENT",
                  "{price}. Invoices are payable upon receipt unless the invoice "
                  "states otherwise. Amounts more than 15 days past due may accrue "
                  "a late charge of 1.5% per month or the maximum allowed by law, "
                  "whichever is less, and work may pause until the account is "
                  "current."),
            fixed("TIMELINE",
                  "{timeline}. Dates shift day-for-day where delays are caused by "
                  "the client (approvals, access, materials selection) or by "
                  "events outside either party's reasonable control.",
                  requires="timeline"),
            fixed("CHANGES",
                  "Either party may propose changes to the scope. A change takes "
                  "effect only when both parties have agreed to it and to any "
                  "price or timeline adjustment, in writing."),
            fixed("OWNERSHIP OF WORK",
                  "Upon receipt of full payment, ownership of the final "
                  "deliverables transfers to {client_name}. {business_name} "
                  "retains its pre-existing tools, methods and know-how, and may "
                  "display the finished work in its portfolio unless you ask us "
                  "not to in writing."),
            fixed("WARRANTY AND LIABILITY",
                  "Services are performed in a professional and workmanlike "
                  "manner. If something is not right, tell us within 30 days and "
                  "we will correct it at no charge where reasonably possible. "
                  "Each party's total liability under this agreement is limited "
                  "to the amounts paid for the services, except for liabilities "
                  "that cannot be limited by law."),
            fixed("TERMINATION",
                  "Either party may terminate with written notice. The client "
                  "pays for work completed and non-refundable commitments made "
                  "through the termination date; any unearned prepayment is "
                  "returned."),
            fixed("GOVERNING LAW",
                  "This agreement is governed by the laws of {state_full}.{venue_clause}",
                  requires="state"),
            sig(_SIGNATURE_BLOCK),
        ],
    },

    # ── 4. Consulting Agreement ──────────────────────────────────────
    {
        "id": "consulting_agreement",
        "numbered": True,
        "title": "Consulting Agreement",
        "subtitle": "Scope, Independence & Confidentiality",
        "description": "Advisory engagement with independent-contractor status, "
                       "confidentiality, and clean IP lines.",
        "category": "client",
        "suggested_for": ["consultant", "coach"],
        "fields": [
            field("engagement", "The engagement", type_="textarea", required=True,
                  placeholder="e.g. Advise on the Q4 pricing rollout: weekly working sessions plus a written recommendation"),
            field("fees", "Fees and invoicing", required=True, sticky=True,
                  placeholder="e.g. $5,000 flat, invoiced half up front — or $250/hour, invoiced monthly"),
            field("term", "Term (optional)", placeholder="e.g. Through December 31, 2026"),
            field("state", "Governing state (optional)", sticky=True, placeholder="e.g. Georgia"),
        ],
        "sections": [
            drafted(None,
                    "One short paragraph: {client_name} engages {business_name} as "
                    "an independent consultant; this agreement sets the terms.",
                    "{client_name} engages {business_name} as an independent "
                    "consultant on the terms below."),
            fixed("THE ENGAGEMENT",
                  "{engagement}\n\nThe consultant controls the manner and means of "
                  "the work; the client is buying outcomes and advice, not hours "
                  "of supervision."),
            fixed("INDEPENDENT CONTRACTOR",
                  "The consultant is an independent contractor, not an employee, "
                  "partner or agent of the client. The consultant is responsible "
                  "for its own taxes, insurance and business expenses, and may "
                  "serve other clients, provided confidentiality below is "
                  "honored."),
            fixed("FEES",
                  "{fees}. Invoices are payable upon receipt unless the invoice "
                  "states otherwise. Pre-approved, reasonable out-of-pocket "
                  "expenses are billed at cost."),
            fixed("CONFIDENTIALITY",
                  "Each party will protect the other's non-public business "
                  "information with at least the care it uses for its own, and "
                  "will use it only for this engagement. This obligation survives "
                  "the end of the engagement for two years, and indefinitely for "
                  "trade secrets."),
            fixed("WORK PRODUCT",
                  "Deliverables prepared specifically for the client under this "
                  "agreement belong to the client upon full payment. The "
                  "consultant retains its general skills, methods, templates and "
                  "know-how, including as improved during the engagement."),
            fixed("NO GUARANTEE",
                  "The consultant will bring professional skill and judgment to "
                  "the engagement. Business outcomes depend on factors outside "
                  "either party's control, and no particular result is promised."),
            fixed("TERM AND TERMINATION",
                  "Term: {term}. Either party may terminate earlier with 14 days' "
                  "written notice; the client pays for work performed through the "
                  "termination date.",
                  requires="term"),
            fixed("GOVERNING LAW",
                  "This agreement is governed by the laws of {state_full}.{venue_clause}",
                  requires="state"),
            sig(_SIGNATURE_BLOCK),
        ],
    },

    # ── 5. Coaching Agreement ────────────────────────────────────────
    {
        "id": "coaching_agreement",
        "numbered": True,
        "title": "Coaching Agreement",
        "subtitle": "Sessions, Cancellations & Boundaries",
        "description": "Program, sessions, cancellations — and the boundaries "
                       "that protect a coaching practice.",
        "category": "client",
        "suggested_for": ["coach", "personal_services"],
        "fields": [
            field("program", "The program", type_="textarea", required=True,
                  placeholder="e.g. 12-week leadership coaching: weekly 60-minute sessions plus email support between sessions"),
            field("investment", "Investment and payment", required=True,
                  placeholder="e.g. $2,400 — payable in full, or 3 monthly payments of $850"),
            field("cancel_window", "Cancellation notice for a session", sticky=True,
                  default="24 hours", placeholder="24 hours"),
        ],
        "sections": [
            drafted(None,
                    "A warm, professional one-paragraph welcome from "
                    "{business_name} to {client_name} for the coaching "
                    "relationship — encouraging, no hype.",
                    "Welcome — this agreement sets out how we will work together, "
                    "so both of us can focus on the work itself."),
            fixed("THE PROGRAM",
                  "{program}"),
            fixed("INVESTMENT",
                  "{investment}. Payment is due as scheduled regardless of "
                  "session usage; missed payments pause the program until the "
                  "account is current."),
            fixed("SCHEDULING AND CANCELLATIONS",
                  "Sessions are scheduled in advance. A session may be "
                  "rescheduled without charge with at least {cancel_window} "
                  "notice; later cancellations and no-shows count as delivered, "
                  "because the time was reserved for you."),
            fixed("YOUR COMMITMENT",
                  "Coaching works when you do: you agree to show up prepared, "
                  "complete what you commit to between sessions, and communicate "
                  "honestly about what is and isn't working."),
            fixed("CONFIDENTIALITY",
                  "What you share in coaching stays private, with narrow "
                  "exceptions required by law (risk of harm to yourself or "
                  "others, or a court order)."),
            fixed("COACHING, NOT THERAPY OR PROFESSIONAL ADVICE",
                  "Coaching is a development relationship. It is not therapy, "
                  "counseling, medical, legal or financial advice, and it does "
                  "not diagnose or treat any condition. If issues arise that need "
                  "a licensed professional, you agree to seek one. Results depend "
                  "on your own decisions and actions; no specific outcome is "
                  "guaranteed."),
            fixed("ENDING THE PROGRAM",
                  "You may end the program with 14 days' written notice. Sessions "
                  "already delivered and the current billing period are earned; "
                  "remaining prepaid, undelivered sessions are refunded."),
            sig(_SIGNATURE_BLOCK),
        ],
    },

    # ── 6. Mutual NDA ────────────────────────────────────────────────
    {
        "id": "mutual_nda",
        "numbered": True,
        "title": "Mutual Nondisclosure Agreement",
        "subtitle": "Definitions, Exclusions & Term",
        "description": "Both sides can talk freely: definitions, exclusions, "
                       "term, and remedies.",
        "category": "protect",
        "suggested_for": ["consultant", "creative", "contractor", "lawyer"],
        "fields": [
            field("purpose", "Purpose of the exchange", required=True,
                  placeholder="e.g. Evaluating a joint venture for event production services"),
            field("term_years", "Confidentiality term (years)", sticky=True, default="2",
                  placeholder="2"),
            field("state", "Governing state (optional)", sticky=True, placeholder="e.g. Georgia"),
        ],
        "sections": [
            fixed(None,
                  "This Mutual Nondisclosure Agreement is between "
                  "{business_name} and {client_name} (each a \"party\"), for the "
                  "purpose of: {purpose}."),
            fixed("CONFIDENTIAL INFORMATION",
                  "\"Confidential Information\" means non-public information a "
                  "party discloses in connection with the purpose above — "
                  "business, technical, financial or customer information — "
                  "whether marked confidential or not, where a reasonable person "
                  "would understand it to be confidential."),
            fixed("OBLIGATIONS",
                  "Each party will (a) use the other's Confidential Information "
                  "only for the purpose above, (b) protect it with at least the "
                  "care it uses for its own confidential information and no less "
                  "than reasonable care, and (c) share it only with people who "
                  "need it for the purpose and are bound by obligations at least "
                  "as protective as these."),
            fixed("EXCLUSIONS",
                  "These obligations do not apply to information that (a) is or "
                  "becomes public through no fault of the receiver, (b) the "
                  "receiver already lawfully had, (c) is received lawfully from a "
                  "third party without restriction, (d) is independently "
                  "developed without use of the discloser's information, or "
                  "(e) must be disclosed by law — with prompt notice to the "
                  "discloser where lawful, and disclosure limited to what is "
                  "required. Nothing in this agreement prevents either party from reporting suspected unlawful conduct to a government agency or from making disclosures protected by law."),
            fixed("TERM",
                  "This agreement covers disclosures made within one year of "
                  "signing. Confidentiality obligations last {term_years} years "
                  "from each disclosure; obligations for trade secrets last as "
                  "long as the information remains a trade secret."),
            fixed("RETURN AND NO LICENSE",
                  "On request, each party will return or destroy the other's "
                  "Confidential Information. Nothing here transfers ownership or "
                  "grants any license; no party is obligated to proceed with any "
                  "transaction."),
            fixed("REMEDIES",
                  "A breach of this agreement may cause harm money cannot fully "
                  "repair, so the injured party may seek injunctive relief in "
                  "addition to any other remedy available at law."),
            fixed("GOVERNING LAW",
                  "This agreement is governed by the laws of {state_full}.{venue_clause}",
                  requires="state"),
            sig(_SIGNATURE_BLOCK),
        ],
    },

    # ── 7. Independent Contractor Agreement ──────────────────────────
    {
        "id": "independent_contractor",
        "numbered": True,
        "title": "Independent Contractor Agreement",
        "subtitle": "Relationship, Pay & Work Product",
        "description": "Bring on 1099 help with the relationship, taxes, and "
                       "IP stated plainly.",
        "category": "protect",
        "suggested_for": ["contractor", "creative", "personal_services"],
        "fields": [
            field("services", "Services the contractor will perform", type_="textarea", required=True,
                  placeholder="e.g. Framing labor for the Deluth remodel, per plans provided"),
            field("pay", "Pay and schedule", required=True,
                  placeholder="e.g. $45/hour, invoiced weekly, paid within 7 days"),
            field("state", "Governing state (optional)", sticky=True, placeholder="e.g. Georgia"),
        ],
        "sections": [
            fixed(None,
                  "This Independent Contractor Agreement is between "
                  "{business_name} (\"Company\") and {client_name} "
                  "(\"Contractor\")."),
            fixed("SERVICES",
                  "{services}\n\nThe Contractor controls the manner and means of "
                  "performing the services, providing their own tools and "
                  "equipment unless agreed otherwise in writing."),
            fixed("RELATIONSHIP",
                  "The Contractor is an independent contractor, not an employee. "
                  "The Contractor is responsible for their own income and "
                  "self-employment taxes, insurance, and licenses, and is not "
                  "entitled to employee benefits. The Company will issue tax "
                  "reporting forms (e.g. Form 1099-NEC) as required by law."),
            fixed("PAYMENT",
                  "{pay}. The Contractor invoices the Company; approved invoices "
                  "are paid on the schedule above. Pre-approved materials and "
                  "expenses are reimbursed at cost with receipts."),
            fixed("WORK PRODUCT",
                  "Work product created for the Company under this agreement is "
                  "the Company's property upon payment, including intellectual "
                  "property rights in it, to the extent permitted by law. The "
                  "Contractor keeps their general skills, methods and know-how."),
            fixed("SAFETY AND CONDUCT",
                  "The Contractor will perform the services safely, comply with "
                  "applicable law and site rules, and carry any insurance "
                  "required for the work."),
            fixed("TERM AND TERMINATION",
                  "Either party may end this agreement with written notice. The "
                  "Company pays for services satisfactorily performed through the "
                  "termination date."),
            fixed("GOVERNING LAW",
                  "This agreement is governed by the laws of {state_full}.{venue_clause}",
                  requires="state"),
            sig(_SIGNATURE_BLOCK),
        ],
    },

    # ── 8. Demand Letter ─────────────────────────────────────────────
    {
        "id": "demand_letter",
        "title": "Demand Letter (Unpaid Balance)",
        "subtitle": "The Balance, the Deadline & What's Next",
        "description": "A firm, professional demand for payment — the letter "
                       "before further action.",
        "category": "money",
        "suggested_for": ["lawyer", "contractor", "consultant", "creative"],
        "fields": [
            field("amount", "Amount owed", required=True, placeholder="e.g. $1,850.00"),
            field("owed_for", "What it's owed for", type_="textarea", required=True,
                  placeholder="e.g. Invoice #2041 for the March brand design work, delivered March 18"),
            field("deadline_days", "Days to pay", sticky=True, default="14", placeholder="14"),
        ],
        "sections": [
            drafted(None,
                    "One firm but professional opening paragraph from "
                    "{business_name} to {client_name}: this letter is a formal "
                    "demand for the unpaid balance described below. No threats, "
                    "no apology — measured and direct.",
                    "This letter is a formal demand for payment of the unpaid "
                    "balance described below."),
            fixed("THE BALANCE",
                  "Amount due: {amount}\nFor: {owed_for}\n\nDespite prior "
                  "requests, this balance remains unpaid as of {date}."),
            fixed("DEMAND",
                  "Payment of {amount} in full is required within "
                  "{deadline_days} days of the date of this letter. Payment may "
                  "be made by the methods shown on your invoice; contact us if "
                  "you need those details reissued."),
            fixed("IF PAYMENT IS NOT RECEIVED",
                  "If the balance is not received within {deadline_days} days, "
                  "we will consider further steps to collect it, which may "
                  "include engaging a collection service or pursuing the amount "
                  "in court, along with any costs and interest allowed by law. "
                  "We would prefer to resolve this directly."),
            fixed("RESERVATION OF RIGHTS",
                  "This letter is not a complete statement of the facts or of "
                  "our rights and remedies, all of which are expressly "
                  "reserved. If you believe any part of this balance is in "
                  "error, contact us in writing within the period above."),
            fixed(None,
                  "Sincerely,\n\n{practitioner_name}\n{business_name}"),
        ],
    },

    # ── 9. Disengagement / Closing Letter ────────────────────────────
    {
        "id": "disengagement_letter",
        "title": "Closing Letter",
        "subtitle": "What Concluded, the File & What's Ahead",
        "description": "End an engagement cleanly: what concluded, the file, "
                       "and what you're no longer responsible for.",
        "category": "close",
        "suggested_for": ["lawyer", "consultant", "coach", "accountant"],
        "fields": [
            field("matter", "The engagement being closed", required=True,
                  placeholder="e.g. The Northside lease negotiation"),
            field("final_note", "Final balance or refund note (optional)",
                  placeholder="e.g. A final invoice for $220 follows — or — your unused deposit of $340 is being returned"),
        ],
        "sections": [
            drafted(None,
                    "A gracious one-paragraph note from {business_name} to "
                    "{client_name}: the engagement below has concluded; thank "
                    "them for the trust.",
                    "Dear {client_name},\n\nThis letter confirms that our "
                    "engagement described below has concluded. Thank you for "
                    "trusting {business_name} with it."),
            fixed("THE ENGAGEMENT",
                  "Concluded engagement: {matter}\nEffective date: {date}"),
            fixed("FINAL ACCOUNTING",
                  "{final_note}.",
                  requires="final_note"),
            fixed("YOUR FILE",
                  "Copies of the key documents from the engagement are available "
                  "to you on request. We retain our file for our records per our "
                  "retention practices; if you would like copies, ask within the "
                  "next 90 days for the quickest turnaround."),
            fixed("GOING FORWARD",
                  "With this engagement closed, {business_name} has no ongoing "
                  "responsibility for the matter — including monitoring "
                  "deadlines, renewals or obligations that may arise from it. If "
                  "anything new comes up, contact us and we would be glad to "
                  "open a new engagement."),
            fixed(None,
                  "With appreciation,\n\n{practitioner_name}\n{business_name}"),
        ],
    },
]

TEMPLATE_INDEX: Dict[str, Dict[str, Any]] = {t["id"]: t for t in TEMPLATES}


# ─── Vertical language — the document speaks the business's trade ────
# The system KNOWS the business type at generation time; these derived
# variables make the clauses use it. A rubric, not per-vertical forks:
# templates reference {expense_examples} / {outcome_factors} /
# {work_materials_term} and every vertical resolves them — unknown
# types get the neutral defaults.

VERTICAL_LANGUAGE: Dict[str, Dict[str, str]] = {
    "_default": {
        "expense_examples": "materials, licenses, and third-party charges",
        "outcome_factors": "circumstances outside our control",
        "work_materials_term": "materials and completed work product",
    },
    "lawyer": {
        "expense_examples": "filing fees, postage, and third-party charges",
        "outcome_factors": "decision-makers outside our control",
        "work_materials_term": "file",
    },
    "accountant": {
        "expense_examples": "filing fees, software, and third-party charges",
        "work_materials_term": "records and work papers",
    },
    "consultant": {
        "expense_examples": "travel and pre-approved third-party charges",
    },
    "creative": {
        "expense_examples": "domain registration, hosting, stock imagery, "
                            "fonts, and software licenses",
        "work_materials_term": "completed deliverables and source files",
    },
    "contractor": {
        "expense_examples": "materials, equipment rental, and permits",
        "outcome_factors": "site conditions and suppliers outside our control",
        "work_materials_term": "completed work and materials on site",
    },
    "coach": {
        "expense_examples": "pre-approved materials and venue charges",
        "outcome_factors": "your own decisions and effort, which coaching "
                           "cannot replace",
    },
    "personal_services": {
        "expense_examples": "products and supplies used in your services",
    },
}


def vertical_language(business_type: Optional[str]) -> Dict[str, str]:
    merged = dict(VERTICAL_LANGUAGE["_default"])
    merged.update(VERTICAL_LANGUAGE.get((business_type or "").lower(), {}))
    return merged


# Governing-law rendering: "the laws of MI" read like a form. Full
# names always; pass-through for anything already written out.
US_STATE_NAMES: Dict[str, str] = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut",
    "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine",
    "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri",
    "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota",
    "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "the District of Columbia",
}


def us_state_full(s: str) -> str:
    v = (s or "").strip()
    return US_STATE_NAMES.get(v.upper(), v)


def venue_unit(state: str) -> str:
    """The deterministic slice of state awareness: Louisiana has
    parishes, Alaska has boroughs — a venue clause that says 'County'
    there is simply wrong. Everything mechanical like this adjusts
    automatically; legal-judgment differences go to state_notes for
    the practitioner instead of being silently rewritten."""
    full = us_state_full(state).lower()
    if full == "louisiana":
        return "Parish"
    if full == "alaska":
        return "Borough"
    return "County"


# Derived variables build_vars computes on top of the field values.
# The placeholder-integrity test admits these alongside declared fields.
DERIVED_VARS = {
    "state_full", "venue_clause", "effective_date_resolved",
    "expense_examples", "outcome_factors", "work_materials_term",
    "expense_cap_clause", "extra_rate_clause", "practitioner_title",
}


# ─── Assembly ────────────────────────────────────────────────────────

class _SafeMap(dict):
    """Unknown {placeholder} stays visible instead of raising — a typo
    shows itself in review rather than 500ing generation."""
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def validate_params(template: Dict[str, Any],
                    params: Dict[str, str]) -> Optional[str]:
    """Returns an error message, or None when everything required is
    present. Defaults are applied by build_vars, not judged here."""
    for f in template["fields"]:
        if f["required"] and not (params.get(f["key"]) or "").strip():
            return f"'{f['label']}' is required for this document"
    return None


def build_vars(template: Dict[str, Any], params: Dict[str, str],
               *, business_name: str, practitioner_name: str,
               client_name: str, date_str: str,
               business_type: Optional[str] = None) -> Dict[str, str]:
    v = {
        "business_name": business_name,
        "practitioner_name": practitioner_name,
        "client_name": client_name,
        "date": date_str,
    }
    for f in template["fields"]:
        val = (params.get(f["key"]) or "").strip() or f.get("default", "")
        if f.get("type") == "list" and val:
            # one item per line in the form → a structured list on paper
            items = [ln.strip().lstrip("-•").strip()
                     for ln in val.split("\n") if ln.strip()]
            val = "\n".join(f"- {it}" for it in items)
        v[f["key"]] = val

    # Derived variables — where the vertical speaks (DERIVED_VARS).
    v.update(vertical_language(business_type))
    v["state_full"] = us_state_full(v.get("state", ""))
    venue = (v.get("venue_county") or "").strip()
    v["venue_clause"] = (f" Venue for any court proceeding lies in "
                         f"{venue} {venue_unit(v.get('state', ''))}."
                         if venue else "")
    v["effective_date_resolved"] = ((v.get("effective_date") or "").strip()
                                    or "the date of the last signature below")
    cap = (v.get("expense_cap") or "").strip()
    v["expense_cap_clause"] = (f"; any single cost over {cap} will be "
                               f"approved by you in writing before it is "
                               f"incurred" if cap else "")
    rate = (v.get("extra_rate") or "").strip()
    v["extra_rate_clause"] = (f"are billed at {rate} and" if rate
                              else "are quoted first and")
    v["practitioner_title"] = ((v.get("title") or "").strip()
                               or "____________________")
    return v


def assemble(template: Dict[str, Any], variables: Dict[str, str],
             drafted_texts: Dict[int, str], *,
             include_review_note: bool) -> str:
    """Sections → the finished document body. drafted_texts maps a
    section index to the model's text; a drafted section with no entry
    uses its fallback, so the document always completes."""
    safe = _SafeMap(variables)
    parts: List[str] = []
    # Agreements number their headed sections AT ASSEMBLY — a hidden
    # conditional clause (no deposit → no deposit section) can then
    # never leave a gap in the numbering. Letters stay unnumbered.
    numbered = bool(template.get("numbered"))
    clause_no = 0
    for i, s in enumerate(template["sections"]):
        req = s.get("requires")
        if req and not (variables.get(req) or "").strip():
            continue
        rv = s.get("requires_value")
        if rv and (variables.get(rv["field"]) or "").strip().lower() != rv["value"]:
            continue
        if s["kind"] == "drafted":
            text = (drafted_texts.get(i) or "").strip() or s["fallback"]
        else:
            text = s["text"]
        rendered = text.format_map(safe)
        if s.get("heading"):
            heading = s["heading"]
            if numbered:
                clause_no += 1
                heading = f"{clause_no}. {heading}"
            rendered = f"{heading}\n\n{rendered}"
        parts.append(rendered)
    if include_review_note:
        parts.append(_REVIEW_NOTE)
    return "\n\n".join(parts)


# ─── The back page — the armor every signed agreement carries ────────
# The clauses that look like filler and do the real work when things
# go wrong: entire-agreement kills "but you said on the phone",
# severability keeps one dead clause from killing the contract, and
# the signatures clause is load-bearing HERE because execution runs
# through an e-signature service. Spliced before the signature block
# of the seven agreements; the two letters stay letters.
# Deliberate absence: NO liability cap on engagement_letter or
# retainer_agreement — prospectively limiting professional (e.g.
# malpractice) liability is ethically prohibited for lawyers in most
# states, so those two omit it on purpose.

_GENERAL_TERMS = fixed("GENERAL TERMS",
    "(a) Entire agreement. This document is the entire agreement between "
    "the parties about its subject and replaces every earlier discussion, "
    "promise, or writing about it.\n"
    "(b) Changes. A change to this agreement counts only when it is in "
    "writing and accepted by both parties; a clear written exchange "
    "(including email) is enough.\n"
    "(c) Severability. If any part of this agreement is found "
    "unenforceable, that part is limited or removed to the minimum extent "
    "necessary, and the rest stays in force.\n"
    "(d) Assignment. Neither party may transfer this agreement to someone "
    "else without the other's written consent, except as part of a sale "
    "of substantially all of a party's business.\n"
    "(e) Notices. Formal notices go in writing to the addresses or email "
    "addresses the parties regularly use with each other, and count when "
    "received.\n"
    "(f) Events beyond control. Neither party is responsible for delay or "
    "failure caused by events beyond its reasonable control (illness, "
    "disaster, outage, or similar), provided the affected party gives "
    "prompt notice and resumes as soon as reasonably possible.\n"
    "(g) Signatures. This agreement may be signed in counterparts, and "
    "electronic signatures — including through an e-signature service — "
    "are as valid as ink.\n"
    "(h) Effective date. This agreement takes effect on "
    "{effective_date_resolved}.")

_DISPUTE = fixed("DISPUTE RESOLUTION",
    "If a dispute arises under this agreement, the parties will first try "
    "in good faith to resolve it directly within 30 days of one party "
    "raising it in writing. If that fails, they will consider mediation "
    "before either begins a court proceeding — except that either party "
    "may go straight to court to protect confidential information. Where the law allows, the prevailing party in "
    "any proceeding may recover its reasonable costs.")

_NO_GUARANTEE_PRO = fixed("NO GUARANTEE OF OUTCOME",
    "We will bring professional skill, care, and judgment to this "
    "engagement. Outcomes depend on facts, third parties, and "
    "{outcome_factors}, and no particular result is promised or "
    "implied.")

_OVERDUE = fixed("OVERDUE ACCOUNTS",
    "Amounts more than 15 days past due may accrue a late charge of 1.5% "
    "per month or the maximum the law allows, whichever is less, and work "
    "may pause until the account is current. You are responsible for the "
    "reasonable costs of collecting seriously overdue amounts where the "
    "law allows.")

_RELATIONSHIP = fixed("RELATIONSHIP OF THE PARTIES",
    "{business_name} is an independent contractor, not an employee, "
    "partner, or agent of {client_name}. Neither party may bind the "
    "other, and nothing in this agreement creates a joint venture.")

_INDEMNITY = fixed("RESPONSIBILITY FOR CLAIMS",
    "Each party will be responsible for, and will hold the other harmless "
    "from, third-party claims to the extent they arise out of that "
    "party's own negligence, willful misconduct, or breach of this "
    "agreement. Neither party takes on the other's independent "
    "obligations to third parties.")

_LIABILITY_CAP = fixed("LIMITATION OF LIABILITY",
    "Except for breaches of confidentiality, amounts owed under this "
    "agreement, or liabilities that cannot be limited by law, each "
    "party's total liability under this agreement is limited to the fees "
    "paid or payable for the engagement.")

_BACK_PAGE: Dict[str, List[Dict[str, Any]]] = {
    "engagement_letter":      [_NO_GUARANTEE_PRO, _OVERDUE, _DISPUTE, _GENERAL_TERMS],
    "retainer_agreement":     [_NO_GUARANTEE_PRO, _OVERDUE, _DISPUTE, _GENERAL_TERMS],
    "service_agreement":      [_RELATIONSHIP, _INDEMNITY, _DISPUTE, _GENERAL_TERMS],
    "consulting_agreement":   [_LIABILITY_CAP, _DISPUTE, _GENERAL_TERMS],
    "coaching_agreement":     [_DISPUTE, _GENERAL_TERMS],
    "mutual_nda":             [_GENERAL_TERMS],
    "independent_contractor": [_INDEMNITY, _DISPUTE, _GENERAL_TERMS],
}

for _t in TEMPLATES:
    _extra = _BACK_PAGE.get(_t["id"])
    if _extra:
        _sig_block = _t["sections"].pop()   # signature block is last
        _t["sections"].extend(list(_extra) + [_sig_block])


# ─── The tenth: Creative Services Agreement ──────────────────────────
# Kevin's live-fire finding (8/05): creative work had no agreement of
# its own, so the engagement letter — correct for a lawyer — was the
# nearest suggestion, and its trust-drawdown and law-office language
# leaked onto a design job. This is the variant built for the work:
# IP that transfers ON PAYMENT IN FULL, revision rounds and change
# orders, deemed acceptance, an explicit DEFINITION of completion
# (payment hangs on it), client-delay protection, client-materials
# warranty, a liability cap, and third-party services responsibility.
# Shared spine (dispute w/ IP carve-out + general terms) splices in
# below like every other agreement.

_DISPUTE_IP = fixed("DISPUTE RESOLUTION",
    "If a dispute arises under this agreement, the parties will first try "
    "in good faith to resolve it directly within 30 days of one party "
    "raising it in writing. If that fails, they will consider mediation "
    "before either begins a court proceeding — except that either party "
    "may go straight to court to protect confidential information or "
    "intellectual property. Where the law allows, the prevailing party in "
    "any proceeding may recover its reasonable costs.")

_CONFIDENTIALITY_MUTUAL = fixed("CONFIDENTIALITY",
    "Each party will protect the other's non-public business information "
    "with at least the care it uses for its own, use it only for this "
    "project, and disclose it only to those who need it for the work or "
    "as required by law. This obligation survives the end of the project "
    "for two years, and indefinitely for trade secrets. Nothing in this agreement prevents either party from reporting suspected unlawful conduct to a government agency or from making disclosures protected by law.")

_CREATIVE_TEMPLATE: Dict[str, Any] = {
    "id": "creative_services_agreement",
    "numbered": True,
    "title": "Creative Services Agreement",
    "subtitle": "Deliverables, Revisions, Ownership & Getting Paid",
    "description": "Built for design, web, brand, and content work: "
                   "revisions, acceptance, IP on payment, and a defined "
                   "finish line.",
    "category": "client",
    # NOT personal_services — see IRRELEVANT_FOR. A barber, nail tech,
    # cleaner or groomer has no deliverables list, revision rounds,
    # deemed acceptance, source files or IP transfer. It was suggested
    # to them since it shipped.
    "suggested_for": ["creative"],
    "fields": [
        field("scope", "The project", type_="textarea", required=True,
              placeholder="e.g. Design and build a five-page marketing site for Walton Wellness"),
        list_field("deliverables", "Deliverables (one per line)", required=True,
                   placeholder="Homepage design\nFour interior pages\nMobile layouts\nLaunch on client hosting"),
        field("fee", "Project fee", required=True, sticky=True,
              placeholder="e.g. $2,400 (just the amount; structure below)"),
        select_field("fee_model", "How the fee works",
                     ["flat_fee", "hourly", "milestone"],
                     default="flat_fee", sticky=True),
        field("payment_terms", "Payment structure (optional)", type_="textarea",
              sticky=True, default="",
              placeholder="e.g. 50% due on signing; the remaining 50% due at completion."),
        field("revision_rounds", "Revision rounds included", default="2",
              sticky=True, placeholder="2"),
        field("extra_rate", "Rate for extra rounds / out-of-scope work (optional)",
              sticky=True, placeholder="e.g. $85/hour"),
        field("acceptance_days", "Days until silent delivery counts as accepted",
              default="7", sticky=True, placeholder="7"),
        field("abandon_days", "Days of client silence before the project closes out",
              default="30", sticky=True, placeholder="30"),
        field("expense_cap", "Written approval needed for costs over (optional)",
              sticky=True, placeholder="e.g. $50"),
        select_field("portfolio_ok", "May the work appear in your portfolio?",
                     ["yes", "no"], default="yes", sticky=True),
        field("state", "Governing state (optional)", sticky=True,
              placeholder="e.g. Michigan"),
    ],
    "sections": [
        drafted(None,
                "A one-paragraph professional opener from {business_name} to "
                "{client_name}: excited to take on the project, this agreement "
                "sets the working terms so both sides can focus on the work.",
                "Dear {client_name},\n\nThank you for choosing {business_name}. "
                "This agreement sets out how we will work together on your "
                "project — read it carefully and sign below to begin."),
        fixed("THE PROJECT",
              "{scope}"),
        fixed("DELIVERABLES",
              "The deliverables for this project:\n\n{deliverables}\n\n"
              "Anything not listed is out of scope until it is added by a "
              "written change order."),
        fixed("FEES AND EXPENSES",
              "The project fee is: {fee}. Reasonable pre-approved costs "
              "incurred on your behalf (such as {expense_examples}) are "
              "billed at cost{expense_cap_clause}."),
        fixed("PAYMENT STRUCTURE",
              "{payment_terms}\n\n"
              "This is a flat-fee project. Any deposit or initial payment is "
              "a milestone payment toward the project fee and is not "
              "refundable once work has begun. The remaining balance is due "
              "at completion as defined below, and final deliverables and "
              "source files are released on receipt of payment in full.",
              requires_value=("fee_model", "flat_fee")),
        fixed("PAYMENT STRUCTURE",
              "Time is billed at {fee} and invoiced as the work proceeds. "
              "{payment_terms}",
              requires_value=("fee_model", "hourly")),
        fixed("PAYMENT STRUCTURE",
              "Payment is tied to the deliverables above: each payment is due "
              "on delivery of its milestone, and work on the next milestone "
              "may pause until the prior payment is received.\n\n{payment_terms}",
              requires_value=("fee_model", "milestone")),
        fixed("REVISIONS AND CHANGE ORDERS",
              "The fee includes {revision_rounds} rounds of revisions per "
              "deliverable. Additional rounds and out-of-scope requests "
              "{extra_rate_clause} proceed only by a written change order "
              "(a clear written exchange counts) describing the work, the "
              "price, and any timeline effect."),
        fixed("ACCEPTANCE AND COMPLETION",
              "Each deliverable is accepted when you approve it in writing, "
              "or automatically if {acceptance_days} days pass after delivery "
              "with no written feedback. The project is COMPLETE when every "
              "deliverable listed in this agreement has been delivered and "
              "accepted. The final balance is due at completion."),
        fixed("CLIENT DELAY",
              "The project needs your input to move. If we cannot get a "
              "response from you for {abandon_days} days, the project is "
              "deemed complete as delivered and the remaining balance becomes "
              "due. Restarting after that may carry a reactivation fee of up "
              "to 10% of the project fee."),
        fixed("OWNERSHIP",
              "On receipt of payment in full, ownership of the final "
              "deliverables transfers to {client_name}. {business_name} "
              "retains ownership of its pre-existing and reusable tools, "
              "components, templates, and frameworks, including as improved "
              "during this project, with a license to you to use them as part "
              "of the deliverables."),
        fixed("PORTFOLIO",
              "{business_name} may display the finished work in its portfolio "
              "and marketing once the project is public or complete.",
              requires_value=("portfolio_ok", "yes")),
        fixed("PORTFOLIO",
              "{business_name} will not display this work in its portfolio or "
              "marketing without your prior written permission.",
              requires_value=("portfolio_ok", "no")),
        fixed("CLIENT MATERIALS",
              "You confirm you have the rights to the materials you provide "
              "for the project — logos, copy, images, fonts, and similar — "
              "and you will be responsible for any third-party claim that "
              "those materials infringe someone else's rights."),
        fixed("THIRD-PARTY SERVICES",
              "Hosting, domains, plugins, fonts, and platform subscriptions "
              "used in the deliverables are your ongoing responsibility and "
              "cost after handoff. {business_name} is not responsible for "
              "third-party outages, changes, or price increases."),
    ],
}

_CREATIVE_TEMPLATE["sections"].extend([
    _CONFIDENTIALITY_MUTUAL,
    _LIABILITY_CAP,
    fixed("GOVERNING LAW",
          "This agreement is governed by the laws of "
          "{state_full}.{venue_clause}",
          requires="state"),
    _DISPUTE_IP,
    _GENERAL_TERMS,
    sig(_SIGNATURE_BLOCK),
])

TEMPLATES.append(_CREATIVE_TEMPLATE)
TEMPLATE_INDEX[_CREATIVE_TEMPLATE["id"]] = _CREATIVE_TEMPLATE

# Creative stops being pointed at the generic service agreement — its
# own paper outranks it (ranking only; nothing is ever gated).
for _t in TEMPLATES:
    if _t["id"] == "service_agreement" and "creative" in _t["suggested_for"]:
        _t["suggested_for"].remove("creative")


# ─── Nonprofit governance paper ──────────────────────────────────────
#
# The documents a funder asks for BEFORE it asks anything about the
# project. A grant application's standing attachments split cleanly in
# two, and the split is the important part:
#
#   ISSUED TO THE ORGANISATION — the IRS determination letter, a filed
#   Form 990, audited financials. These are NOT here and must never be.
#   The IRS issues a determination letter; an independent auditor issues
#   an audit; a 990 is a return that was filed. Generating any of them
#   would be manufacturing an official record, and a funder receiving one
#   would be receiving a forgery. Those slots take an UPLOAD of the real
#   document and a pointer to where it comes from.
#
#   WRITTEN BY THE ORGANISATION — everything below. A board list, three
#   governance policies, a nondiscrimination statement, a mission
#   narrative. The organisation authors these, so drafting one is help
#   rather than fabrication.
#
# The three policies earn their place on a fact rather than a hunch:
# Form 990 Part VI asks whether the filer HAS a conflict-of-interest
# policy, a whistleblower policy and a document-retention policy. A
# nonprofit without them answers "no" three times on a public filing
# every prospective funder can read.
#
# Every drafted section carries a fallback, and each fallback is the
# conservative standard wording rather than a placeholder — a governance
# policy containing "[describe your procedure]" is worse than one with a
# plain procedure the board can amend.

_BOARD_LIST = {
    "id": "board_list",
    "title": "Board of Directors",
    "subtitle": "Names, Roles & Affiliations",
    "description": "The board roster funders ask for, with roles and affiliations.",
    "category": "protect",
    "numbered": False,
    "suggested_for": ["nonprofit", "ministry"],
    "fields": [
        field("org_name", "Organization name", required=True, sticky=True),
        field("as_of", "Current as of", placeholder="e.g. August 2026"),
        list_field("members", "Board members", required=True,
                   placeholder="One per line: Name - Role - Affiliation"),
        field("meeting_cadence", "How often the board meets",
              placeholder="e.g. quarterly", sticky=True),
    ],
    "sections": [
        fixed(None, "{org_name}\nBoard of Directors\n{as_of}"),
        fixed("Members", "{members}"),
        fixed("Governance", "The Board of Directors meets {meeting_cadence}.",
              requires="meeting_cadence"),
        drafted(
            "Board composition",
            "Two or three plain sentences describing the board's composition "
            "and the independence of its members, using ONLY the roster "
            "given. Do not invent expertise, employers or demographics that "
            "are not in the list.",
            "The Board of Directors is responsible for the governance and "
            "fiduciary oversight of the organization."),
    ],
}

_CONFLICT_POLICY = {
    "id": "conflict_of_interest_policy",
    "title": "Conflict of Interest Policy",
    "subtitle": "Disclosure, Recusal & Review",
    "description": "The governance policy Form 990 Part VI asks whether you have.",
    "category": "protect",
    "numbered": True,
    "suggested_for": ["nonprofit", "ministry"],
    "fields": [
        field("org_name", "Organization name", required=True, sticky=True),
        field("adopted_on", "Date adopted by the board"),
    ],
    "sections": [
        fixed(None, "{org_name}\nCONFLICT OF INTEREST POLICY"),
        fixed("Purpose",
              "The purpose of this policy is to protect the interests of "
              "{org_name} when it contemplates entering into a transaction or "
              "arrangement that might benefit the private interest of an "
              "officer or director, or might result in a possible excess "
              "benefit transaction."),
        fixed("Who this covers",
              "This policy applies to every director, officer, and member of "
              "a committee with board-delegated powers, and to any employee "
              "who can influence a transaction on the organization's behalf."),
        fixed("What must be disclosed",
              "An interested person must disclose the existence and nature of "
              "any financial interest, and all material facts, to the "
              "directors considering the proposed transaction."),
        fixed("How a conflict is handled",
              "After disclosure, the interested person leaves the meeting "
              "while the transaction is discussed and voted upon. The "
              "remaining board members decide whether a conflict exists and, "
              "if so, whether the transaction is in the organization's best "
              "interest and is fair and reasonable. The minutes record the "
              "disclosure, the discussion, and the vote."),
        fixed("Annual statement",
              "Each person covered by this policy signs a statement annually "
              "affirming that they have received, read, and understood the "
              "policy, and agree to comply with it."),
        fixed("Violations",
              "If the board has reasonable cause to believe a covered person "
              "has failed to disclose an actual or possible conflict, it "
              "informs that person of the basis for the belief and gives them "
              "an opportunity to explain before taking corrective action."),
        fixed("Adoption", "Adopted by the Board of Directors on {adopted_on}.",
              requires="adopted_on"),
    ],
}

_WHISTLEBLOWER_POLICY = {
    "id": "whistleblower_policy",
    "title": "Whistleblower Policy",
    "subtitle": "Reporting Without Retaliation",
    "description": "How concerns get reported, and the protection for reporting them.",
    "category": "protect",
    "numbered": True,
    "suggested_for": ["nonprofit", "ministry"],
    "fields": [
        field("org_name", "Organization name", required=True, sticky=True),
        field("report_to", "Who concerns are reported to",
              placeholder="e.g. the Board Chair", sticky=True),
        field("adopted_on", "Date adopted by the board"),
    ],
    "sections": [
        fixed(None, "{org_name}\nWHISTLEBLOWER POLICY"),
        fixed("Purpose",
              "{org_name} requires directors, officers, staff and volunteers "
              "to observe high standards of business and personal ethics. This "
              "policy exists so that anyone who in good faith reports a "
              "suspected violation can do so without fear of retaliation."),
        fixed("Reporting a concern",
              "Concerns about suspected illegal, unethical or fraudulent "
              "conduct, or about the accuracy of the organization's financial "
              "records, should be reported to {report_to}.",
              requires="report_to"),
        fixed("No retaliation",
              "No director, officer, employee or volunteer who in good faith "
              "reports a concern shall suffer harassment, retaliation, or "
              "adverse employment consequence. Anyone who retaliates against "
              "a good-faith reporter is subject to discipline up to and "
              "including termination."),
        fixed("Good faith",
              "A person filing a report must be acting in good faith and have "
              "reasonable grounds for believing the information indicates a "
              "violation. An allegation made maliciously or known to be false "
              "is itself a serious disciplinary matter."),
        fixed("Confidentiality",
              "Reports are treated as confidential to the extent possible, "
              "consistent with the need to conduct an adequate investigation."),
        fixed("Handling",
              "Reports are investigated promptly, and corrective action is "
              "taken where warranted. The person receiving the report advises "
              "the Board of Directors of the report and of the outcome."),
        fixed("Adoption", "Adopted by the Board of Directors on {adopted_on}.",
              requires="adopted_on"),
    ],
}

_RETENTION_POLICY = {
    "id": "document_retention_policy",
    "title": "Document Retention Policy",
    "subtitle": "What To Keep, And For How Long",
    "description": "Retention schedules plus the litigation hold that overrides them.",
    "category": "protect",
    "numbered": True,
    "suggested_for": ["nonprofit", "ministry"],
    "fields": [
        field("org_name", "Organization name", required=True, sticky=True),
        field("adopted_on", "Date adopted by the board"),
    ],
    "sections": [
        fixed(None, "{org_name}\nDOCUMENT RETENTION AND DESTRUCTION POLICY"),
        fixed("Purpose",
              "This policy governs how {org_name} retains and disposes of its "
              "records, so that documents are kept as long as they are needed "
              "and no longer, and so that nothing is destroyed while it may "
              "be relevant to an investigation or legal proceeding."),
        fixed("Permanent records",
              "Articles of incorporation, bylaws, the IRS determination "
              "letter, board minutes, annual financial statements and filed "
              "Forms 990 are retained permanently."),
        fixed("Records kept seven years",
              "Accounting records, bank statements, invoices, contracts after "
              "expiration, grant records after the final report, and "
              "employment and payroll records after termination are retained "
              "for seven years."),
        fixed("Records kept three years",
              "Correspondence of general significance, insurance policies "
              "after expiration, and unsuccessful job applications are "
              "retained for three years."),
        fixed("Litigation hold",
              "If an official investigation, audit or legal action is under "
              "way or reasonably anticipated, destruction of any related "
              "record stops immediately and does not resume until the matter "
              "is concluded. This overrides every schedule above."),
        fixed("Electronic records",
              "Electronic records are subject to the same schedules as their "
              "paper equivalents, and backups are maintained so that records "
              "within a retention period can be produced."),
        fixed("Adoption", "Adopted by the Board of Directors on {adopted_on}.",
              requires="adopted_on"),
    ],
}

_NONDISCRIMINATION = {
    "id": "nondiscrimination_statement",
    "title": "Nondiscrimination Statement",
    "subtitle": "Programs, Services & Employment",
    "description": "The statement commonly required with federal civil-rights assurances.",
    "category": "protect",
    "numbered": False,
    # NOT ministry — see IRRELEVANT_FOR below. As written this commits the
    # organisation to non-discrimination on religion, sex, gender identity
    # and sexual orientation IN EMPLOYMENT, which many congregations
    # contradict via the ministerial exception and Title VII's
    # religious-organisation exemption.
    "suggested_for": ["nonprofit"],
    "fields": [
        field("org_name", "Organization name", required=True, sticky=True),
        field("programs", "What this covers",
              default="all programs, services, and employment"),
    ],
    "sections": [
        fixed(None, "{org_name}\nNONDISCRIMINATION STATEMENT"),
        fixed(None,
              "{org_name} does not discriminate on the basis of race, color, "
              "national origin, religion, sex, gender identity, sexual "
              "orientation, age, disability, veteran status, or any other "
              "characteristic protected by applicable federal, state or local "
              "law, in {programs}."),
        drafted(
            None,
            "One sentence naming who to contact about the policy and how, "
            "using only the organization name. Do not invent an email "
            "address, a phone number or a staff member's name.",
            "Questions about this policy may be directed to the "
            "organization's administrative office."),
    ],
}

_MISSION_NARRATIVE = {
    "id": "mission_history",
    "title": "Mission and History",
    "subtitle": "Organizational Background",
    "description": "The organizational background you paste into every application.",
    "category": "client",
    "numbered": False,
    "suggested_for": ["nonprofit", "ministry"],
    "fields": [
        field("org_name", "Organization name", required=True, sticky=True),
        field("founded", "Year founded", sticky=True),
        field("mission", "Mission statement", type_="textarea", required=True,
              sticky=True),
        list_field("programs", "Main programs", placeholder="One per line"),
        field("served", "Who you serve", sticky=True,
              placeholder="e.g. families in Dane County"),
        field("proof", "Something you can evidence", type_="textarea",
              placeholder="A number you can stand behind - leave blank if unsure"),
    ],
    "sections": [
        fixed(None, "{org_name}\nMission and History"),
        fixed("Mission", "{mission}"),
        drafted(
            "History",
            "Two or three sentences of organizational history using ONLY the "
            "founding year, mission and programs given. Invent NOTHING - no "
            "milestones, no award names, no growth figures, no partner "
            "organizations. If the founding year is blank, do not guess it.",
            "The organization was established to advance the mission stated "
            "above and continues to deliver its programs today."),
        fixed("Programs", "{programs}", requires="programs"),
        fixed("Who we serve", "{served}", requires="served"),
        # NOT drafted, deliberately. An impact paragraph is exactly where
        # a grant application acquires a number nobody can evidence, and a
        # fabricated outcome there is a legal exposure rather than a
        # formatting problem. This renders only what the practitioner
        # typed, and disappears when they typed nothing.
        fixed("Impact", "{proof}", requires="proof"),
    ],
}

for _npt in (_BOARD_LIST, _CONFLICT_POLICY, _WHISTLEBLOWER_POLICY,
             _RETENTION_POLICY, _NONDISCRIMINATION, _MISSION_NARRATIVE):
    TEMPLATES.append(_npt)
    TEMPLATE_INDEX[_npt["id"]] = _npt

# Nonprofit language for the shared clause pools, so a generated document
# says "the Organization" rather than "the Firm".
VERTICAL_LANGUAGE["nonprofit"] = dict(VERTICAL_LANGUAGE.get("_default") or {})
VERTICAL_LANGUAGE["nonprofit"].update({
    "self": "the Organization",
    "client": "the participant",
    "engagement": "the program",
})
VERTICAL_LANGUAGE["ministry"] = dict(VERTICAL_LANGUAGE["nonprofit"])


# ─── Which paper belongs in which room ───────────────────────────────
#
# /doctemplates/list returned all sixteen templates to every business.
# suggested_for only SORTED them, so a nonprofit was shown a demand
# letter and a coaching agreement, a barber was shown an engagement
# letter, and six of the fourteen verticals got a completely flat list
# because their type appeared in no suggested_for at all.
#
# HIDDEN, NOT GATED. The library's standing rule is that nothing is ever
# withheld — a business's needs are its own, and the one time we guess
# wrong we would be blocking real work. So an irrelevant template is
# hidden behind "Show all templates", never removed. That asymmetry is
# what makes the table below safe to be opinionated in: an over-hide
# costs one click, an under-hide can cost a professional-ethics
# violation.
#
# EVERY HIDE CARRIES ITS REASON. A hide with no reason is someone's
# taste, and taste drifts. A test asserts the reasons exist.

IRRELEVANT_FOR: Dict[str, Dict[str, str]] = {

    "engagement_letter": {
        "coach": "duplicates the coaching agreement while DROPPING the 'coaching "
                 "is not therapy' clause — the one clause protecting an unlicensed coach",
        "contractor": "trades work is a quoted contract with a deposit and a draw "
                      "schedule, not an engagement opened with a retainer",
        "course_creator": "one product sold to many students; this is bilateral "
                          "per-client paper with a named counterparty",
        "creative": "trust-drawdown and law-office language on a design job — the "
                    "exact leak creative_services_agreement was built to replace",
        "fitness_wellness": "no professional-engagement shape",
        "ministry": "a congregation has no billable engagements to open",
        "nonprofit": "counterparties are donors, grantors, volunteers and vendors",
        "personal_services": "a chair is not an engagement",
        "therapist": "no fit; the practice's paper is policies and fees, not a matter",
    },

    "retainer_agreement": {
        "course_creator": "bilateral per-client paper; the product is sold, not retained",
        # Not merely irrelevant — actively wrong paper.
        "fitness_wellness": "DANGEROUS: a membership is an auto-renewing consumer "
                            "contract under state health-club and automatic-renewal "
                            "statutes. This template's 'fees for the current term are "
                            "earned and non-refundable' would produce a non-compliant "
                            "membership agreement",
        "ministry": "a congregation retains nobody monthly",
        "nonprofit": "not the shape of donor or grantor money",
        "therapist": "practice policies cover the standing relationship",
    },

    "service_agreement": {
        "coach": "deliverables, IP transfer and acceptance describe nothing in a "
                 "twelve-week coaching engagement",
        "financial_educator": "curriculum delivery has no deliverables list",
        # The sharpest finding in the audit.
        "lawyer": "IT CAPS LIABILITY. engagement_letter and retainer_agreement omit "
                  "a cap on purpose, because prospectively limiting professional "
                  "liability is ethically prohibited for lawyers in most states — and "
                  "then this was shown to every lawyer with a cap in it",
    },

    "consulting_agreement": {
        "contractor": "trades work is quoted and built, never advised on retainer",
        "course_creator": "bilateral per-client paper",
        "fitness_wellness": "training is delivered in sessions, not advised on",
        "lawyer": "carries _LIABILITY_CAP, for the same ethics reason as "
                  "service_agreement above. A lawyer doing genuine non-legal "
                  "advisory work can still reach it under Show all",
        "ministry": "no billable advisory engagements",
        "personal_services": "a chair has no advisory engagement to paper",
    },

    "coaching_agreement": {
        "consultant": "the cancellation-window and 'not therapy' framing reads as "
                      "unserious to a corporate buyer",
        "contractor": "a job is scheduled and completed, not run as sessions",
        "creative": "a project runs to deliverables, not to a session count",
        "lawyer": "a firm does not coach; this carries no legal-engagement terms",
        "nonprofit": "programs are not coaching engagements",
        # The important one.
        "therapist": "HAZARD: its 'COACHING, NOT THERAPY' clause asserts the exact "
                     "opposite of what a therapist does, and its confidentiality "
                     "section is a generic exceptions list, NOT a HIPAA- or "
                     "state-accurate privacy disclosure. Sending it tells a client "
                     "something untrue about their own privacy rights",
    },

    "disengagement_letter": {
        "contractor": "a job closes with a punch list, a final invoice and a lien "
                      "waiver, not a file-retention letter",
        "course_creator": "no per-client matter to close",
        "creative": "creative closes with delivery and a final invoice",
        "fitness_wellness": "a membership lapses or cancels; nothing is closed out",
        "ministry": "no engagements to close",
        "nonprofit": "no engagements to close",
        "personal_services": "a client simply stops booking; there is no matter to close",
        # Scope boundary, not taste.
        "therapist": "HAZARD: the therapist analogue of closing a matter is "
                     "TERMINATION OF TREATMENT — a clinical event carrying referral, "
                     "continuity-of-care and abandonment exposure. Its 'we retain our "
                     "file' language also invites treating this platform as custodian "
                     "of the clinical record, which is what vertical_scope.py exists "
                     "to prevent",
    },

    "creative_services_agreement": {
        "coach": "no deliverables or revision rounds",
        "consultant": "revision rounds and portfolio permission are not advisory terms",
        "contractor": "no source files or IP transfer on a job site",
        "course_creator": "bilateral per-client paper",
        "financial_educator": "no deliverables shape",
        "fitness_wellness": "no deliverables shape",
        "lawyer": "a firm does not coach; this carries no legal-engagement terms",
        "ministry": "no client deliverables",
        "nonprofit": "no client deliverables",
        # Was in its suggested_for, and plainly wrong.
        "personal_services": "a barber, nail tech, cleaner or groomer has no "
                             "deliverables list, revision rounds, deemed acceptance, "
                             "source files or IP transfer",
        "therapist": "no deliverables shape",
    },
}

# The six nonprofit governance documents are irrelevant to every vertical
# that has no board and files no 990. Listed as one block because the
# reason is identical, and kept OUT of a hard gate because these take
# org_name as a FIELD rather than binding to the business — so a lawyer
# or consultant serving nonprofit clients can legitimately produce them
# for a client organisation, under Show all.
_NO_BOARD_NO_990 = (
    "no board and no Form 990 — this is a nonprofit's governance paper, "
    "reachable under Show all for anyone producing it for a client")
for _gov in ("board_list", "conflict_of_interest_policy", "whistleblower_policy",
             "document_retention_policy", "nondiscrimination_statement",
             "mission_history"):
    IRRELEVANT_FOR[_gov] = {
        v: _NO_BOARD_NO_990
        for v in ("coach", "consultant", "contractor", "course_creator", "creative",
                  "financial_educator", "fitness_wellness", "lawyer",
                  "personal_services", "service_provider", "therapist")
    }

# And one correction to yesterday's work, which is a content problem
# rather than a relevance one.
IRRELEVANT_FOR["nondiscrimination_statement"]["ministry"] = (
    "As written this commits the organisation to non-discrimination on "
    "religion, sex, gender identity and sexual orientation IN EMPLOYMENT. "
    "Many churches rely on the ministerial exception and Title VII's "
    "religious-organisation exemption and hold doctrinal hiring positions "
    "this contradicts. Generating it for a congregation can create a "
    "written policy contradicting actual practice, which is worse than "
    "having none. A ministry variant scoped to programs and services — "
    "preserving the religious-employment exemption — is the fix; until "
    "that exists this is not offered to ministry")

# mutual_nda, independent_contractor and demand_letter appear in NO list
# above, deliberately. Every business signs an NDA eventually, every
# business hires 1099 help eventually, and every business eventually
# invoices someone who does not pay. Gating those would be the guess this
# table is careful not to make.


def is_irrelevant(template_id: str, canonical_vertical: str) -> bool:
    """True when this template would be noise in this vertical's list.

    Never a refusal — the caller hides it behind Show all."""
    return canonical_vertical in IRRELEVANT_FOR.get(template_id, {})


def irrelevance_reason(template_id: str, canonical_vertical: str) -> Optional[str]:
    return IRRELEVANT_FOR.get(template_id, {}).get(canonical_vertical)
