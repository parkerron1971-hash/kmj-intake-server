"""Reading the finished document before the client does.

The whole game is FALSE POSITIVES. A practitioner who dismisses a wrong
finding twice stops reading the panel, and from then on the auditor is
worse than absent — it creates a false sense of having been checked.

So the most important test in this file is not any of the rules. It is
the harness at the bottom: every template in the library, rendered and
audited, must produce ZERO blockers. A rule that fires on our own
reviewed paper is either wrong or has found a template bug, and either
way it must not reach a practitioner.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import doc_audit as da
import doc_templates as dt


def codes(body, **kw):
    return [f["code"] for f in da.audit_document(body, **kw)["findings"]]


# ── It catches what it claims to ─────────────────────────────────────

def test_an_unfilled_placeholder_is_a_blocker():
    r = da.audit_document("The deposit of {deposit} is due on signing.")
    assert r["findings"][0]["code"] == "placeholder_unfilled"
    assert r["findings"][0]["severity"] == da.BLOCKER


@pytest.mark.parametrize("hole", [
    "[CLIENT NAME]", "TBD", "XXX", "<insert scope>", "Lorem ipsum dolor",
])
def test_human_placeholder_text_is_caught_too(hole):
    """Learned templates and hand edits carry these, not {braces}."""
    assert "placeholder_human" in codes(f"Payment due from {hole} on signing.")


def test_a_number_that_disagrees_with_its_word():
    assert "number_word_mismatch" in codes("within thirty (14) days of notice")
    assert "number_word_mismatch" in codes("within 30 (fourteen) days of notice")


def test_a_number_that_agrees_is_silent():
    assert "number_word_mismatch" not in codes("within fourteen (14) days")
    assert "number_word_mismatch" not in codes("within 14 (fourteen) days")


def test_an_impossible_date_is_a_blocker():
    r = da.audit_document("Payment is due February 30, 2026.")
    assert r["findings"][0]["code"] == "date_impossible"
    assert r["findings"][0]["severity"] == da.BLOCKER


def test_a_wild_year_is_flagged_but_not_blocking():
    got = [f for f in da.audit_document("Effective January 5, 2062.")["findings"]
           if f["code"] == "date_far_off"]
    assert got and got[0]["severity"] == da.HIGH


def test_two_amounts_in_one_clause():
    r = da.audit_document("x", sections=[
        {"text": "Amount due: $1,850.00. Pay $1,580.00 within 14 days."}])
    assert "money_conflict" in [f["code"] for f in r["findings"]]


def test_amounts_in_different_clauses_are_fine():
    """A contract names a fee in one clause and a deposit in another.
    Comparing across the document would fire on every real agreement."""
    r = da.audit_document("x", sections=[
        {"text": "The fee is $5,000."}, {"text": "The deposit is $1,500."}])
    assert "money_conflict" not in [f["code"] for f in r["findings"]]


def test_a_numbered_agreement_without_a_signature_block():
    assert "signature_block_missing" in codes("1. TERMS\nSome text.", numbered=True)
    assert "signature_block_missing" not in codes(
        "1. TERMS\nSome text.\nACCEPTED AND AGREED", numbered=True)
    # a letter is not numbered and needs no signature block
    assert "signature_block_missing" not in codes("Dear Dana,\nRegards.", numbered=False)


def test_mechanical_defects():
    assert "doubled_word" in codes("the the agreement stands")
    assert "mojibake" in codes("the clientâ€™s obligations")
    assert "confusable" in codes("This aggreement is binding.")
    assert "confusable" in codes("beyond the statue of limitations")


# ── And stays quiet on paper that is fine ────────────────────────────

def test_the_signature_block_underscores_are_not_placeholders():
    """The single most likely false positive in the whole library.

    Audited AFTER substitution, which is the only state it is ever in
    when a practitioner sees it — the raw template naturally carries
    {business_name} and friends."""
    filled = dt._SIGNATURE_BLOCK.format(
        business_name="Reyes Law", practitioner_name="Marisol Reyes",
        practitioner_title="Principal", client_name="Dana Whitfield")
    assert da.audit_document(filled)["counts"].get(da.BLOCKER, 0) == 0
    assert "____" in filled, "the fixture stopped covering the underscores"


@pytest.mark.parametrize("safe", [
    "Interest accrues at 1.5% per month on overdue balances.",
    "A Form 1099-NEC will be issued for payments over $600.",
    "See SF-424 and the SF-425 report.",
    "Signed: ____________________",
    "The fee is $5,000.00 and no other amount appears here.",
    "Payment is due within 14 (fourteen) days.",
])
def test_known_good_text_produces_nothing(safe):
    r = da.audit_document(safe)
    assert r["findings"] == [], (safe, r["findings"])


def test_an_exception_yields_no_findings_rather_than_an_error():
    """The auditor has no veto anywhere. It must never be the reason a
    document cannot ship."""
    r = da.audit_document(None)  # type: ignore[arg-type]
    assert r["ok"] is True
    assert r["findings"] == []


def test_findings_are_capped():
    body = " ".join("{hole_%d}" % i for i in range(30))
    r = da.audit_document(body)
    assert len(r["findings"]) <= sum(da.MAX_PER_SEVERITY.values())
    assert r["more"] > 0, "dropped findings must be counted, not hidden"


def test_every_finding_explains_itself_and_names_a_fix():
    """A finding you cannot act on is a finding you ignore."""
    r = da.audit_document("The fee is {fee} and the term is thirty (14) days.")
    assert r["findings"]
    for f in r["findings"]:
        assert f["title"] and f["detail"]
        assert f["fix"] in ("fill_field", "edit_text", "review")
        assert f["source"] == "deterministic"


def test_only_deterministic_rules_can_block():
    """A model may never emit a blocker. Nothing here calls one, so this
    pins the invariant for whoever adds the model pass later."""
    r = da.audit_document("{x} and February 30, 2026")
    for f in r["findings"]:
        if f["severity"] == da.BLOCKER:
            assert f["source"] == "deterministic"


# ── THE HARNESS ──────────────────────────────────────────────────────

# THE HARNESS RUNS THROUGH build_vars, the same function the router uses.
#
# The first version passed a hand-built dict straight to assemble() and
# failed all sixteen templates on placeholders the real path always
# fills — build_vars walks EVERY declared field and substitutes "" for a
# blank one, so an untouched optional field leaves no hole. Testing
# beside the production seam instead of through it produced sixteen
# findings that could never happen.

def _params_for(t, required_only=False):
    """What a practitioner would type into the form."""
    out = {}
    for f in t["fields"]:
        if required_only and not f.get("required"):
            continue
        key = f["key"]
        if f["type"] == "select":
            opts = [o for o in (f.get("options") or []) if o]
            out[key] = opts[-1] if opts else ""
        elif f["type"] == "list":
            out[key] = "First item\nSecond item"
        elif "date" in key or key in ("as_of", "adopted_on"):
            out[key] = "March 4, 2026"
        elif any(k in key for k in ("fee", "amount", "deposit", "investment", "balance")):
            out[key] = "$2,500.00"
        elif "days" in key or "years" in key or key == "founded":
            out[key] = "14"
        else:
            out[key] = f.get("default") or ("Sample " + key.replace("_", " "))
    return out


def _render(t, required_only=False):
    variables = dt.build_vars(
        t, _params_for(t, required_only),
        business_name="Reyes Law", practitioner_name="Marisol Reyes",
        client_name="Dana Whitfield", date_str="March 4, 2026")
    return dt.assemble(t, variables, drafted_texts={}, include_review_note=False)


@pytest.mark.parametrize("tid", [t["id"] for t in dt.TEMPLATES])
def test_every_template_audits_clean_when_filled(tid):
    """THE test. Our own reviewed paper must produce no blockers.

    A rule that fires here is either wrong or has found a genuine
    template bug — and either way it is not allowed near a practitioner.
    """
    t = dt.TEMPLATE_INDEX[tid]
    body = _render(t)
    r = da.audit_document(body, numbered=bool(t.get("numbered")))
    blockers = [f for f in r["findings"] if f["severity"] == da.BLOCKER]
    assert not blockers, f"{tid}: {blockers}"


@pytest.mark.parametrize("tid", [t["id"] for t in dt.TEMPLATES])
def test_every_template_audits_clean_with_only_required_fields(tid):
    """The minimal fill — optional fields blank, conditional sections
    gone. This is the shape most first documents actually take."""
    t = dt.TEMPLATE_INDEX[tid]
    body = _render(t, required_only=True)
    r = da.audit_document(body, numbered=bool(t.get("numbered")))
    blockers = [f for f in r["findings"] if f["severity"] == da.BLOCKER]
    assert not blockers, f"{tid}: {blockers}"
