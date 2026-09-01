"""The loan agreement — the first template where the business PAYS.

Pinned here: the role naming (the contact is the Lender, the business
the Borrower), the two select branches and the blank-figure holes they
must not paper over, the money-conflict rule, and the two places its
general terms deliberately differ from the shared block.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import doc_audit
import doc_templates as dt

T = dt.TEMPLATE_INDEX["loan_agreement"]

FULL = {
    "principal": "$10,000.00",
    "funding_date": "September 5, 2026",
    "purpose": "Equipment for the second chair",
    "interest_type": "simple interest",
    "interest_rate": "5%",
    "repayment_type": "monthly installments",
    "installment_amount": "$500.00",
    "first_payment_date": "October 1, 2026",
    "due_date": "September 1, 2028",
    "grace_days": "10",
    "late_fee": "$25.00",
    "security": "secured",
    "collateral": "The 2023 Ford Transit van",
    "state": "GA",
}


def _render(params):
    v = dt.build_vars(T, params, business_name="Fade Factory",
                      practitioner_name="Kevin", client_name="Aunt Rose",
                      date_str="September 1, 2026")
    sections = dt.render_sections(T, v, {})
    body = dt.assemble(T, v, {}, include_review_note=False)
    return v, sections, body


def _headings(sections):
    return [s.get("heading") for s in sections if s.get("heading")]


def test_roles_are_named_not_pronouns():
    _, _, body = _render(FULL)
    assert 'Aunt Rose (the "Lender")' in body
    assert 'Fade Factory (the "Borrower")' in body
    # the signature block says who is who
    assert "BORROWER: Fade Factory" in body and "LENDER: Aunt Rose" in body
    assert body.count("By: ___") == 2


def test_full_note_passes_the_audit_clean():
    v, sections, body = _render(FULL)
    audit = doc_audit.audit_document(body, sections=sections, numbered=True,
                                     contract=T["contract"], variables=v)
    assert doc_audit.blocking_count(audit) == 0, audit
    assert not [f for f in audit["findings"] if f["code"] == "money_conflict"], audit
    assert dt.verify_contract(T, sections) == []


def test_interest_branches_render_exactly_one_clause():
    _, s, body = _render(FULL)
    assert _headings(s).count("INTEREST") == 1
    assert "simple interest at 5% per year" in body
    _, s, body = _render({**FULL, "interest_type": "no interest", "interest_rate": ""})
    assert _headings(s).count("INTEREST") == 1
    assert "bears no interest" in body


def test_simple_interest_without_a_rate_is_a_blocker_not_a_hole():
    """'simple interest' with the rate blank must not print 'at  per
    year'. The clause requires the rate, so it vanishes — and the
    declared contract turns the missing fee article into a blocker."""
    v, s, body = _render({**FULL, "interest_rate": ""})
    assert "INTEREST" not in _headings(s)
    assert "per year from the day" not in body
    assert "fees" in dt.verify_contract(T, s)
    audit = doc_audit.audit_document(body, sections=s, numbered=True,
                                     contract=T["contract"], variables=v)
    assert doc_audit.blocking_count(audit) >= 1


def test_repayment_branches_and_the_first_payment_line():
    _, s, body = _render(FULL)
    assert _headings(s).count("REPAYMENT") == 1
    assert "monthly installments of $500.00" in body
    assert "The first installment is due on October 1, 2026." in body
    lump = {**FULL, "repayment_type": "one payment on the due date",
            "installment_amount": "", "first_payment_date": ""}
    _, s, body = _render(lump)
    assert _headings(s).count("REPAYMENT") == 1
    assert "in a single payment on or before September 1, 2028" in body
    assert "first installment" not in body
    # installments chosen, amount blank → no payment article → blocker
    _, s, _ = _render({**FULL, "installment_amount": ""})
    assert "REPAYMENT" not in _headings(s)
    assert "payment" in dt.verify_contract(T, s)


def test_no_clause_names_two_amounts():
    """Principal, installment and late fee each live in their own clause
    so doc_audit's money_conflict rule never fires on a well-formed note."""
    _, s, _ = _render(FULL)
    for sec in s:
        amounts = {a.replace(" ", "") for a in doc_audit._MONEY.findall(sec["text"])}
        assert len(amounts) <= 1, (sec.get("heading"), amounts)


def test_late_fee_and_security_are_conditional():
    _, s, body = _render(FULL)
    assert "late fee of $25.00" in body
    assert "security interest in the following property" in body
    assert "The 2023 Ford Transit van" in body
    _, s, body = _render({**FULL, "late_fee": "", "security": "unsecured", "collateral": ""})
    assert "late fee of" not in body
    assert _headings(s).count("SECURITY") == 1
    assert "This Loan is unsecured" in body


def test_default_clause_reaches_the_grace_period_and_acceleration():
    _, _, body = _render(FULL)
    assert "not received within 10 days after its due date" in body
    assert "declare the entire unpaid balance of the Loan immediately due" in body


def test_general_terms_are_the_notes_own():
    """No force-majeure excuse on a payment obligation the borrower
    wrote; the lender may pass the note on; everything the back-page
    test holds every agreement to is still there."""
    _, _, body = _render(FULL)
    assert "Events beyond control" not in body
    assert "The Lender may transfer its rights under this Note" in body
    assert "Entire agreement" in body and "Severability" in body
    assert "electronic signatures" in body
    assert "This is a loan, not an investment." in body


def test_numbering_never_gaps_across_branches():
    import re
    for params in (FULL,
                   {**FULL, "interest_type": "no interest", "interest_rate": "",
                    "repayment_type": "one payment on the due date",
                    "installment_amount": "", "first_payment_date": "",
                    "late_fee": "", "security": "unsecured", "collateral": "",
                    "funding_date": "", "purpose": "", "state": ""}):
        _, _, body = _render(params)
        nums = [int(m.group(1)) for m in re.finditer(r"^(\d+)\. ", body, re.M)]
        assert nums == list(range(1, len(nums) + 1)), nums


def test_it_is_money_paper_and_hidden_from_nobody():
    assert T["category"] == "money"
    assert "loan_agreement" not in dt.IRRELEVANT_FOR
