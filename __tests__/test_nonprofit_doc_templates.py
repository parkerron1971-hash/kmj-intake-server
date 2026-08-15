"""Nonprofit governance paper — and the documents we must never generate.

A grant application's standing attachments split in two, and the split
is the whole point of this file.

WRITTEN BY THE ORGANISATION — board list, conflict-of-interest policy,
whistleblower policy, document-retention policy, nondiscrimination
statement, mission narrative. Drafting one of these is help.

ISSUED TO THE ORGANISATION — the IRS determination letter, a filed Form
990, audited financials. The IRS issues a determination letter; an
independent auditor issues an audit; a 990 is a return that was FILED.
A template for any of them would let the platform manufacture an
official record, and a funder receiving one would be receiving a
forgery. Those slots take an upload of the real thing.

The most important test here is the one asserting those three do NOT
exist.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import doc_templates as dt

NEW_IDS = [
    "board_list", "conflict_of_interest_policy", "whistleblower_policy",
    "document_retention_policy", "nondiscrimination_statement",
    "mission_history",
]


def _tpl(tid):
    return dt.TEMPLATE_INDEX[tid]


# ── The line ─────────────────────────────────────────────────────────

def test_we_never_template_a_document_someone_else_issues():
    """The determination letter, the 990 and an audit are not ours to write.

    If a future change adds one of these, it is not a feature — it is the
    platform producing a counterfeit government or auditor record.
    """
    ids = {t["id"] for t in dt.TEMPLATES}
    names = " ".join(t["title"].lower() for t in dt.TEMPLATES)
    for forbidden in ("determination_letter", "irs_determination",
                      "form_990", "990", "audited_financials", "audit_report"):
        assert forbidden not in ids, f"template {forbidden!r} must not exist"
    for phrase in ("determination letter", "form 990", "audited financial"):
        assert phrase not in names, f"a template is named after {phrase!r}"


def test_the_mission_narrative_does_not_draft_impact():
    """The one paragraph most likely to acquire an unevidenced number.

    A fabricated outcome in a grant application is a legal exposure, not
    a formatting problem — the impact section renders only what the
    practitioner typed, and vanishes when they typed nothing.
    """
    impact = [s for s in _tpl("mission_history")["sections"]
              if s.get("heading") == "Impact"]
    assert len(impact) == 1
    assert impact[0]["kind"] == "fixed", "impact must never be model-drafted"
    assert impact[0].get("requires") == "proof"


def test_drafted_sections_forbid_invention():
    """Every drafted section in this set is told what NOT to make up."""
    for tid in NEW_IDS:
        for s in _tpl(tid)["sections"]:
            if s["kind"] != "drafted":
                continue
            brief = s["brief"].lower()
            assert ("invent" in brief or "do not" in brief or "only" in brief), (
                f"{tid}: a drafted section with no constraint on invention")


# ── Shape ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tid", NEW_IDS)
def test_template_is_registered_and_well_formed(tid):
    assert tid in dt.TEMPLATE_INDEX
    t = _tpl(tid)
    assert t["title"] and t["description"] and t["subtitle"]
    assert t["category"] in ("client", "protect", "money", "close")
    assert t["sections"], "a template with no sections renders nothing"
    assert "nonprofit" in t["suggested_for"]
    if tid == "nondiscrimination_statement":
        # THE ONE EXCEPTION, and it is a correction to this file's own
        # first pass. As written the statement commits the organisation
        # to non-discrimination on religion, sex, gender identity and
        # sexual orientation IN EMPLOYMENT — which many congregations
        # contradict via the ministerial exception and Title VII's
        # religious-organisation exemption. Generating it for a church
        # can create a written policy contradicting actual practice,
        # which is worse than having none. A ministry variant scoped to
        # programs and services is the fix; until then it is not offered.
        assert "ministry" not in t["suggested_for"]
    else:
        assert "ministry" in t["suggested_for"], (
            "a ministry needs the same governance paper a nonprofit does")


@pytest.mark.parametrize("tid", NEW_IDS)
def test_every_drafted_section_has_a_fallback(tid):
    """The file's standing rule: generation succeeds with the model down.

    A governance policy is exactly where a placeholder would be worst —
    an empty procedure is worse than a plain one the board can amend.
    """
    for s in _tpl(tid)["sections"]:
        if s["kind"] == "drafted":
            assert s.get("fallback"), f"{tid}: drafted section with no fallback"
            assert len(s["fallback"]) > 40, f"{tid}: fallback is a stub"


@pytest.mark.parametrize("tid", NEW_IDS)
def test_every_placeholder_has_a_field(tid):
    """An unfilled {placeholder} ships a document with a hole in it."""
    import re
    t = _tpl(tid)
    declared = {f["key"] for f in t["fields"]}
    for s in t["sections"]:
        for ph in re.findall(r"\{(\w+)\}", s.get("text") or ""):
            assert ph in declared, f"{tid}: {{{ph}}} has no field"


@pytest.mark.parametrize("tid", NEW_IDS)
def test_conditional_sections_name_a_real_field(tid):
    t = _tpl(tid)
    declared = {f["key"] for f in t["fields"]}
    for s in t["sections"]:
        req = s.get("requires")
        if req:
            assert req in declared, f"{tid}: requires={req!r} is not a field"


def test_org_name_is_sticky_everywhere():
    """It is a business-standard fact, not a per-document one — typed once."""
    for tid in NEW_IDS:
        org = [f for f in _tpl(tid)["fields"] if f["key"] == "org_name"]
        assert org, f"{tid} has no org_name"
        assert org[0]["sticky"], f"{tid}: org_name should be sticky"


# ── The 990 Part VI trio ─────────────────────────────────────────────

def test_the_three_form_990_policies_all_exist():
    """Part VI asks whether the filer HAS each of these. Without them a
    nonprofit answers 'no' three times on a public filing."""
    for tid in ("conflict_of_interest_policy", "whistleblower_policy",
                "document_retention_policy"):
        assert tid in dt.TEMPLATE_INDEX


def test_retention_policy_carries_a_litigation_hold():
    """A retention schedule without one tells an organisation to destroy
    records that an investigation may be about to ask for."""
    body = " ".join(s.get("text") or "" for s in _tpl("document_retention_policy")["sections"]).lower()
    assert "litigation" in body or "investigation" in body
    assert "overrides" in body


def test_whistleblower_policy_forbids_retaliation():
    body = " ".join(s.get("text") or "" for s in _tpl("whistleblower_policy")["sections"]).lower()
    assert "retaliation" in body


def test_conflict_policy_requires_recusal_and_minutes():
    body = " ".join(s.get("text") or "" for s in _tpl("conflict_of_interest_policy")["sections"]).lower()
    assert "leaves the meeting" in body
    assert "minutes" in body


# ── Language ─────────────────────────────────────────────────────────

def test_nonprofit_language_says_organization_not_firm():
    lang = dt.VERTICAL_LANGUAGE.get("nonprofit")
    assert lang and lang.get("self") == "the Organization"
    assert dt.VERTICAL_LANGUAGE.get("ministry") == lang


def test_nonprofit_language_keeps_the_default_keys():
    """It EXTENDS the default rather than replacing it — a missing key
    falls through to a literal '{...}' in a rendered clause."""
    default = dt.VERTICAL_LANGUAGE.get("_default") or {}
    lang = dt.VERTICAL_LANGUAGE["nonprofit"]
    for k in default:
        assert k in lang, f"nonprofit language dropped {k!r}"


# ── The picker's vertical lookup ─────────────────────────────────────

def test_suggested_lookup_is_canonicalized():
    """A business stamped 'church' must reach the ministry templates.

    suggested_for lists CANONICAL verticals, businesses.type legitimately
    holds aliases, and the picker compared them raw — so a church saw a
    library with no suggestions at all, including the six governance
    templates written for it.
    """
    import inspect
    import vertical_registry
    import doc_templates_router as r

    src = inspect.getsource(r.doctemplates_list)
    assert "vertical_registry.resolve" in src, (
        "the picker compares businesses.type raw against canonical keys")

    canon = vertical_registry.resolve("church")
    assert canon == "ministry"
    # Five, not six: the nondiscrimination statement is deliberately not
    # offered to a congregation (see above).
    for_church = [t for t in dt.TEMPLATES if canon in t.get("suggested_for", [])]
    assert len(for_church) >= 5, [t["id"] for t in for_church]


def test_every_suggested_for_entry_is_a_real_vertical():
    """A typo'd vertical in suggested_for is invisible: it simply never
    matches, and the template quietly suggests itself to nobody."""
    import vertical_registry
    canonical = set(vertical_registry.CANONICAL)
    for t in dt.TEMPLATES:
        for v in t.get("suggested_for", []):
            assert v in canonical or vertical_registry.resolve(v) in canonical, (
                f"{t['id']} suggests {v!r}, which is not a vertical")
