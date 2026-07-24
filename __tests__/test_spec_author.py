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


def test_recalibration_generosity_and_coverage_laws():
    """Kevin rejected the first live spec on sight: an austere concept
    poster — no nav, no images, no form — while 7 real portfolio pieces
    sat in the DB. The recalibration makes abundance a law."""
    s = spec_author._SYSTEM
    assert "GENEROSITY RULE" in s
    assert "COVERAGE LAW" in s
    assert "DENSITY SKELETON" in s
    # restraint disciplines color/motion, never content
    assert "never CONTENT" in s
    # minimal = failure, stated plainly
    assert '"minimal," you have failed' in s
    # the non-negotiable functions
    for func in ("NAVIGATION", "CONTACT", "FOOTER", "portfolio"):
        assert func.lower() in s.lower(), f"missing mandatory function: {func}"
    # never ban imagery when real imagery exists
    assert "Never ban imagery" in s


def test_inventory_covers_slots_and_contact():
    """The first live spec never saw the portrait or the contact
    channels — the digest now itemizes both."""
    ctx = _ctx(
        gallery=[{"url": "https://x/a.png", "alt": ""}],
        contact={"email": "hello@kmjcreate.com", "phone": "", "website": "kmjcreate.com"},
        site={"site_config": {"slots": {
            "about_subject": {"custom_url": "https://x/portrait.png"},
            "hero_main": {"custom_url": "https://x/gone.png", "removed": True},
        }}},
    )
    d = spec_author._inventory_digest(ctx, [])
    assert "https://x/portrait.png" in d
    assert "owner's own upload" in d
    assert "https://x/gone.png" not in d          # removed stays removed
    assert "hello@kmjcreate.com" in d
    assert "phone" not in d.split("[contact")[1]  # empty channels skipped
    assert "AUTHOR a proper display caption" in d


def test_inventory_rides_the_prompt():
    p = spec_author.build_user_prompt(
        "D", _PLAN, inventory="[gallery]\n1. https://x/img.png — cross tee")
    assert "THE INVENTORY" in p
    assert "coverage law" in p
    assert "cross tee" in p
    # and absent when empty — no hollow section
    p2 = spec_author.build_user_prompt("D", _PLAN)
    assert "THE INVENTORY" not in p2


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


# ─── THE ARCHAEOLOGY (2026-07-24, "the design was already inside") ───
# claude.ai reproduced the same weak design from the same blueprint —
# the document was the problem, and the document was blind. Kevin's
# bar-setting prompt was authored by a mind that had SEEN his work.

def test_system_prompt_teaches_the_archaeology():
    s = spec_author._SYSTEM
    assert "THE ARCHAEOLOGY" in s
    assert "OBSERVED IN THE WORK:" in s
    assert "translate a visual voice that already exists" in s
    # traceability requirement — palette/type must come FROM the work
    assert "could not be traced back" in s


def test_system_prompt_teaches_the_imagination():
    """Kevin (mid-arc): 'it might not see any person's work to get its
    inspiration from' — the no-portfolio path must conjure from the
    business's WORLD, declared and accountable, never the safe median
    and never a vacuum."""
    s = spec_author._SYSTEM
    assert "THE IMAGINATION" in s
    assert "IMAGINED FOR THE WORK:" in s
    assert "mines the client's WORLD" in s
    assert "adjacent masters" in s
    assert "never design from a vacuum" in s
    # the ladder: work first, world second, no rung skipped
    assert "never skip a rung that exists" in s


def test_image_urls_priority_dedupe_and_cap():
    ctx = _ctx(
        gallery=[{"url": f"https://x/g{i}.png"} for i in range(8)],
        site={"site_config": {"slots": {
            "about_subject": {"custom_url": "https://x/portrait.png"},
            "hero_main": {"custom_url": "https://x/g0.png"},          # dupe w/ gallery? no — distinct
            "chamber_main": {"custom_url": "https://x/gone.png", "removed": True},
        }}},
    )
    urls = spec_author._image_urls(ctx, cap=6)
    assert len(urls) == 6
    # owner uploads lead (identity-dense first)
    assert urls[0] == "https://x/portrait.png"
    assert "https://x/gone.png" not in urls
    # dedupe holds
    assert len(set(urls)) == len(urls)


def test_image_urls_https_only():
    ctx = _ctx(gallery=[{"url": "http://insecure/x.png"},
                        {"url": "https://x/ok.png"}])
    assert spec_author._image_urls(ctx) == ["https://x/ok.png"]


# ─── the temperature-400 regression (live 502, 2026-07-24) ───────────
# First live author call 502'd: SPEC_AUTHOR_MODEL unset resolved to
# ATELIER_MODEL=claude-opus-4-8, which 400s on sampling params. The
# call must ride the model ladder (sampling_kwargs + fallback rungs).

def test_call_llm_rides_the_model_ladder(monkeypatch):
    import model_ladder

    captured = {}

    def fake_ladder(fn, model, task, business_id, max_tokens):
        captured["model"] = model
        captured["task"] = task

        class _Block:
            type = "text"
            text = "SPEC DOCUMENT"

        class _Usage:
            input_tokens = 1
            output_tokens = 1

        class _Msg:
            content = [_Block()]
            usage = _Usage()

        return _Msg(), model

    monkeypatch.setattr(model_ladder, "call_with_ladder", fake_ladder)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    out = spec_author._call_llm("sys", "user", "biz")
    assert out == "SPEC DOCUMENT"
    assert captured["task"] == "spec_author"


def test_opus_family_drops_temperature():
    import model_ladder
    assert model_ladder.sampling_kwargs("claude-opus-4-8", 0.7) == {}
