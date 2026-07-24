"""
test_spec_author.py — Director's Cut arc 3: the Spec Author.

The quality thesis (Kevin, 2026-07-24): a fully-DECIDED spec produced
the same excellent page from five different models — the prompt did
the designing. These tests pin the pure parts: the taught anatomy,
the decidedness demands, prompt assembly, and the spec leading the
canvas brief.
"""
import spec_author
from canvas_brief import compile_canvas_brief


# ─── the taught anatomy ──────────────────────────────────────────────

def test_system_prompt_teaches_the_anatomy():
    s = spec_author._SYSTEM
    for section in ("OVERVIEW", "BRAND IDENTITY", "LAYOUT & SECTIONS",
                    "INTERACTIONS & ANIMATIONS", "DESIGN RULES"):
        assert section in s, f"anatomy section missing: {section}"


def test_system_prompt_demands_decidedness_not_vibes():
    s = spec_author._SYSTEM
    assert "write the headline" in s.lower() or "Write the ACTUAL words" in s
    assert "hex" in s.lower()
    # truth law + the anti-crutch ban both present
    assert "Real or removed" in s or "real or removed" in s.lower()
    assert "gold-underline" in s.lower()


# ─── prompt assembly (pure) ──────────────────────────────────────────

_PLAN = [
    {"module": "hero", "variant": "constructed", "content": {"headline": "x"}},
    {"module": "offerings", "variant": "", "content": {}},
]


def test_build_user_prompt_carries_dossier_and_plan():
    p = spec_author.build_user_prompt("DOSSIER TEXT HERE", _PLAN)
    assert "DOSSIER TEXT HERE" in p
    assert "1. hero (constructed)" in p
    assert "2. offerings" in p
    assert "THE PRIOR SPEC" not in p
    assert "REVISION NOTES" not in p


def test_build_user_prompt_revision_mode():
    p = spec_author.build_user_prompt(
        "D", _PLAN, prior_spec="OLD SPEC BODY", feedback="greens too loud")
    assert "OLD SPEC BODY" in p
    assert "greens too loud" in p
    assert "REVISING, not restarting" in p


def test_empty_plan_asks_for_proposal():
    p = spec_author.build_user_prompt("D", [])
    assert "propose a section list" in p


# ─── the spec leads the canvas brief ─────────────────────────────────

def _ctx(**over):
    base = {
        "business": {"name": "KMJ Creative Solutions", "type": "consultant"},
        "dna": {"palette": {"accent": "#C9A84C", "mode": "dark"},
                "typography": {"heading": "Bebas Neue", "body": "DM Sans"}},
        "site_prefs": {},
    }
    base.update(over)
    return base


def test_approved_spec_leads_the_brief():
    brief = compile_canvas_brief(_ctx(
        design_spec_text="SPEC DOCUMENT: BUILD. BRAND. GROW.",
        owner_brief="navy and gold",
    ), None, _PLAN)
    assert "THE APPROVED SPEC" in brief
    assert "SPEC DOCUMENT: BUILD. BRAND. GROW." in brief
    # the spec outranks — it appears before the owner's words and overview
    assert brief.index("THE APPROVED SPEC") < brief.index("THE OWNER'S WORDS")
    assert brief.index("THE APPROVED SPEC") < brief.index("== OVERVIEW ==")


def test_brief_unchanged_without_spec():
    brief = compile_canvas_brief(_ctx(), None, _PLAN)
    assert "THE APPROVED SPEC" not in brief
