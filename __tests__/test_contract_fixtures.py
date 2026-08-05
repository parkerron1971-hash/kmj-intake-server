# __tests__/test_contract_fixtures.py
#
# The four fixture renders from Kevin's contract-engine spec:
#   creative / flat_fee    legal / retainer
#   contractor / milestone consulting / hourly
# Each render asserts: zero unresolved placeholders, no sentence-typed
# value breaking another sentence, the CORRECT fee-model clause present
# and the wrong ones absent, vertical language aligned to the business
# type, and no clause referencing a term the document never defines.

import pathlib
import re
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import doc_templates as dt  # noqa: E402


def _render(template_id, params, business_type, business_name="The Biz"):
    t = dt.TEMPLATE_INDEX[template_id]
    v = dt.build_vars(t, params, business_name=business_name,
                      practitioner_name="Pat Owner", client_name="Chris Client",
                      date_str="August 5, 2026", business_type=business_type)
    return dt.assemble(t, v, {}, include_review_note=False)


def _no_unresolved(body):
    leftovers = re.findall(r"\{[a-z_]+\}", body)
    assert not leftovers, f"unresolved placeholders: {leftovers}"


def test_creative_flat_fee():
    body = _render("creative_services_agreement", {
        "scope": "Design and build a five-page marketing site",
        "deliverables": "Homepage design\nFour interior pages\nLaunch on client hosting",
        "fee": "$200", "fee_model": "flat_fee",
        "payment_terms": "50% ($100) due on signing; the remaining $100 due at completion.",
        "state": "MI",
    }, "creative", "KMJ Creative Solutions")
    _no_unresolved(body)
    # payment prose is its own sentence block — never mid-sentence
    assert "50% ($100) due on signing; the remaining $100 due at completion." in body
    assert "($100), remaining $100 due at completion is due on signing" not in body
    # flat-fee concept, not trust drawdown
    assert "not refundable once work has begun" in body
    assert "exhausted" not in body and "replenished" not in body
    assert "unused balance" not in body
    # creative vertical language, not law-office residue
    assert "domain registration" in body and "filing fees" not in body
    assert "decision-makers" not in body
    # the spec's creative clauses
    assert "- Homepage design" in body                      # structured deliverables
    assert "COMPLETE when every" in body                    # completion defined
    assert "receipt of payment in full" in body             # IP on payment
    assert "portfolio" in body.lower()                      # showcase right
    assert "LIMITATION OF LIABILITY" in body                # capped exposure
    assert "third-party outages" in body
    # dangling-reference rule: IP carve-out allowed because IP is defined
    assert "intellectual property" in body and "OWNERSHIP" in body
    assert "CONFIDENTIALITY" in body
    assert "laws of Michigan" in body                       # full state name
    assert "not legal advice" not in body                   # note off the paper


def test_legal_retainer():
    body = _render("engagement_letter", {
        "scope": "Representation in the Northside lease dispute",
        "fee": "$300/hour", "fee_model": "retainer", "deposit": "$1,500",
        "state": "GA", "venue_county": "Fulton",
    }, "lawyer", "Reyes Law")
    _no_unresolved(body)
    # the drawdown language SURVIVES exactly where it is true
    assert "$1,500" in body and "replenished" in body and "unused balance" in body
    assert "rules applicable to client funds" in body
    # lawyer vertical language intact
    assert "filing fees" in body and "your file" in body
    assert "decision-makers" in body
    assert "laws of Georgia" in body and "Fulton County" in body
    # no flat-fee language bleeding in
    assert "not refundable once work has begun" not in body
    # dangling-reference rule: dispute carve-out only names confidential
    # information, which the letter now defines; never undefined IP
    assert "CONFIDENTIALITY" in body
    assert "intellectual property" not in body


def test_contractor_milestone():
    body = _render("engagement_letter", {
        "scope": "Kitchen remodel per the approved plans",
        "fee": "$18,000", "fee_model": "milestone",
        "payment_terms": "- $6,000 on demolition complete\n- $6,000 on cabinets installed\n- $6,000 on final walkthrough",
        "state": "Michigan",
    }, "contractor", "McCloud Builds")
    _no_unresolved(body)
    assert "tied to the milestones" in body
    assert "$6,000 on cabinets installed" in body
    assert "exhausted" not in body                          # no drawdown
    # contractor vertical language
    assert "equipment rental" in body and "permits" in body
    assert "site conditions" in body                        # outcome factors
    assert "laws of Michigan" in body                       # passthrough full name


def test_consulting_hourly():
    body = _render("engagement_letter", {
        "scope": "Advise on the Q4 pricing rollout",
        "fee": "$250/hour", "fee_model": "hourly",
        "payment_terms": "Invoices go out on the 1st of each month.",
        "state": "TX",
    }, "consultant", "North Star Advisory")
    _no_unresolved(body)
    assert "Time is billed at $250/hour" in body
    assert "Invoices go out on the 1st of each month." in body
    assert "replenished" not in body and "not refundable once work has begun" not in body
    assert "travel" in body and "filing fees" not in body   # consulting expenses
    assert "laws of Texas" in body


def test_no_fee_model_renders_clean_baseline():
    # An old-style call with no fee_model: no payment-structure block at
    # all — never a broken or wrong-concept clause.
    body = _render("engagement_letter", {
        "scope": "s", "fee": "$500", "deposit": "$100"}, "consultant")
    _no_unresolved(body)
    assert "PAYMENT STRUCTURE" not in body and "RETAINER" not in body
    assert "exhausted" not in body


def test_effective_date_and_signature_block():
    body = _render("engagement_letter", {
        "scope": "s", "fee": "$1", "fee_model": "flat_fee"}, "lawyer")
    assert "takes effect on the date of the last signature below" in body
    assert body.count("Name:") == 2 and "Title:" in body
