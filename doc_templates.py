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
          requires: Optional[str] = None) -> Dict[str, Any]:
    d: Dict[str, Any] = {"kind": "fixed", "heading": heading, "text": text}
    if requires:
        d["requires"] = requires
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
                  placeholder="e.g. $300/hour, billed monthly — or a flat $2,500"),
            field("deposit", "Initial deposit / retainer (optional)", sticky=True,
                  placeholder="e.g. $1,500"),
            field("state", "Governing state (optional)", sticky=True, placeholder="e.g. Georgia"),
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
                  "out-of-pocket costs incurred on your behalf (filing fees, "
                  "postage, third-party charges) are billed at cost."),
            fixed("DEPOSIT",
                  "An initial deposit of {deposit} is due on signing and will be "
                  "held and applied against fees and costs as they are incurred, "
                  "in accordance with the rules applicable to client funds. If the "
                  "deposit is exhausted before the engagement concludes, we may "
                  "request that it be replenished. Any unused balance is returned "
                  "promptly at the end of the engagement.",
                  requires="deposit"),
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
            fixed("ENDING THE ENGAGEMENT",
                  "Either of us may end this engagement with written notice. You "
                  "remain responsible for fees and costs incurred through the "
                  "effective date of termination, and we will return your file and "
                  "any unused deposit promptly."),
            fixed("GOVERNING LAW",
                  "This agreement is governed by the laws of {state}.",
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
                  "This agreement is governed by the laws of {state}.",
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
                  "This agreement is governed by the laws of {state}.",
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
                  "This agreement is governed by the laws of {state}.",
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
                  "required."),
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
                  "This agreement is governed by the laws of {state}.",
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
                  "This agreement is governed by the laws of {state}.",
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
               client_name: str, date_str: str) -> Dict[str, str]:
    v = {
        "business_name": business_name,
        "practitioner_name": practitioner_name,
        "client_name": client_name,
        "date": date_str,
    }
    for f in template["fields"]:
        val = (params.get(f["key"]) or "").strip() or f.get("default", "")
        v[f["key"]] = val
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
    "are as valid as ink.")

_DISPUTE = fixed("DISPUTE RESOLUTION",
    "If a dispute arises under this agreement, the parties will first try "
    "in good faith to resolve it directly within 30 days of one party "
    "raising it in writing. If that fails, they will consider mediation "
    "before either begins a court proceeding — except that either party "
    "may go straight to court to protect confidential information or "
    "intellectual property. Where the law allows, the prevailing party in "
    "any proceeding may recover its reasonable costs.")

_NO_GUARANTEE_PRO = fixed("NO GUARANTEE OF OUTCOME",
    "We will bring professional skill, care, and judgment to this "
    "engagement. Outcomes depend on facts, third parties, and "
    "decision-makers outside our control, and no particular result is "
    "promised or implied.")

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
