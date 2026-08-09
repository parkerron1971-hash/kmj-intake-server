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
            "hero_main": {"custom_url": "https://x/g0.png"},   # dupe with gallery g0
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


def test_image_cap_default_covers_a_full_portfolio():
    """Cap 6 cut the owner's loudest pieces (the display-type flyers) —
    the Director observed the quiet half and speced Montserrat again.
    The default must see a 2-upload + 7-image portfolio whole."""
    ctx = _ctx(
        gallery=[{"url": f"https://x/g{i}.png"} for i in range(9)],
        site={"site_config": {"slots": {
            "about_subject": {"custom_url": "https://x/portrait.png"},
            "hero_main": {"custom_url": "https://x/hero.png"},
        }}},
    )
    urls = spec_author._image_urls(ctx)
    assert len(urls) == 11        # everything, nothing cut


def test_caption_truth_and_no_conditionals_taught():
    s = spec_author._SYSTEM
    assert "CAPTION TRUTH" in s
    assert "NO CONDITIONAL ENTRIES" in s


def test_brand_mark_urls_reads_the_brand_kit():
    """Kevin uploaded the mark to the Brand Kit (settings.brand_kit.
    logos.primary) — a source the eyes never read; the next draft still
    ran amber/no-green. The mark now leads the image feed."""
    ctx = _ctx(bundle={"business": {"settings": {"brand_kit": {
        "logos": {"primary": "https://x/mark.png",
                  "alt": "https://x/mark-alt.png"},
        "logo_url": "https://x/mark.png",
    }}}})
    urls = spec_author._brand_mark_urls(ctx, "")
    assert urls[0] == "https://x/mark.png"
    assert len(urls) <= 2
    assert len(set(urls)) == len(urls)
    # no settings, no business_id -> empty, never raises
    assert spec_author._brand_mark_urls(_ctx(), "") == []


def test_declaration_rule_taught():
    s = spec_author._SYSTEM
    assert "THE DECLARATION RULE" in s
    assert 'MUST begin "OBSERVED IN THE WORK:"' in s
    assert "zero-image business" in s
    assert "bind --sx-accent" in s


def test_brand_color_law_and_atmosphere_rule():
    """Kevin on the third render: 'why didn't it use the brand colors?
    no accent in this design. the background should be better.' Brand
    hues bind; the second brand color gets a job; and a flat ground
    fails the atmosphere budget even with every accent rule obeyed."""
    s = spec_author._SYSTEM
    assert "THE BRAND COLOR LAW" in s
    assert "inventing a NEW accent hue while brand colors exist" in s
    assert "the second is a real citizen" in s
    assert "THE ATMOSPHERE RULE" in s
    assert "accent scarcity is NOT atmosphere scarcity" in s
    assert "flat dark rectangle" in s


def test_image_urls_https_only():
    ctx = _ctx(gallery=[{"url": "http://insecure/x.png"},
                        {"url": "https://x/ok.png"}])
    assert spec_author._image_urls(ctx) == ["https://x/ok.png"]


# ─── THE SPEC TOKEN BRIDGE (the "old design living inside" bug) ──────
# The approved spec named its palette, but page tokens came from the
# stored brand DNA — the spec's look physically couldn't reach the
# page, and every canvas fallback re-dressed the site in the old
# regime (Anton + old accent + sig-underline).

_SPEC_SAMPLE = """
- --sx-bg: #0c0c0e (primary dark stage)
- --sx-accent: #d9a514 (THE amber)
- --sx-secondary: #9cad4e (THE brand green)
- --sx-line-green: rgba(156,173,78,0.22) (the Method strip's rule)
- DISPLAY / headlines: var(--sx-display) = Montserrat, 700-900 weight
- BODY / copy: var(--sx-body) = Open Sans, 400-600
"""


def test_extract_token_overrides():
    t = spec_author.extract_token_overrides(_SPEC_SAMPLE)
    assert t["--sx-accent"] == "#d9a514"
    assert t["--sx-secondary"] == "#9cad4e"
    assert t["--sx-line-green"] == "rgba(156,173,78,0.22)"
    assert "--sx-display" not in t          # fonts excluded here


def test_extract_font_overrides():
    f = spec_author.extract_font_overrides(_SPEC_SAMPLE)
    assert f["--sx-font-heading"] == "Montserrat"
    assert f["--sx-font-body"] == "Open Sans"


def test_apply_spec_overrides_injects_and_retires_old_chrome():
    html = "<html><head><title>x</title></head><body class='sx-sig-underline'>hi</body></html>"
    out = spec_author.apply_spec_overrides(html, _SPEC_SAMPLE)
    assert 'id="sx-spec-overrides"' in out
    assert "--sx-accent:#d9a514" in out
    assert "fonts.googleapis.com" in out and "Montserrat" in out
    # the legacy underline chrome is retired when a spec governs
    assert "content:none!important" in out
    # injected before </head>, exactly once
    assert out.index("sx-spec-overrides") < out.index("</head>")


def test_apply_spec_overrides_fails_open():
    html = "<html><head></head><body></body></html>"
    assert spec_author.apply_spec_overrides(html, "no tokens here") == html
    assert spec_author.apply_spec_overrides("no head tag", _SPEC_SAMPLE) == "no head tag"


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


def test_filled_space_law_rides_the_system_prompt():
    """Kevin's 2026-07-25 review of his own live page: a lit hero with
    an empty half, scroll-deserts between chapters, every section
    arriving with the same fade. The law makes filled space and varied
    arrival grammar the floor for EVERY site, not a per-site note."""
    s = spec_author._SYSTEM
    assert "FILLED-SPACE LAW" in s
    assert "off-axis half" in s
    assert "REVEAL GRAMMAR VARIETY" in s
    # the one-signature-motion discipline survives the addition
    assert "ONE signature motion moment" in s


# ═══ The blueprint that vanished (2026-08-09) ════════════════════════
#
# Kevin drafted a blueprint after a 14-turn coach session. The call ran
# 30,594 in / 7,800 out, SUCCEEDED server-side, and cost 20.88c — and the
# browser gave up before the response arrived. He saw "failed to fetch".
# The stored design_spec was still revision 13 from 2026-07-25, so the
# draft was generated, charged for, and lost.
#
# Two defects, both pinned below: save_spec dropped its PATCH result on
# the floor (a failed write was indistinguishable from a good one), and
# a multi-minute LLM call sat on a synchronous HTTP request.

import pytest


class _FakeSB:
    """Minimal sb_clients stand-in: one site row, a togglable PATCH."""
    def __init__(self, patch_ok=True, has_row=True):
        self.patch_ok, self.has_row = patch_ok, has_row
        self.patches = []
        self.config = {"design_spec": {"text": "old", "status": "approved",
                                       "revision": 13}}

    def sb_get_as_service(self, path):
        if not self.has_row:
            return []
        return [{"id": "site-1", "site_config": self.config}]

    def sb_patch_as_service(self, path, body):
        self.patches.append(body)
        if not self.patch_ok:
            return None            # what sb_clients returns on 4xx/5xx
        self.config = body["site_config"]
        return [{"id": "site-1"}]  # Prefer: return=representation


def _wire(monkeypatch, fake):
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake.sb_get_as_service)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fake.sb_patch_as_service)


def test_save_spec_raises_when_the_write_does_not_land(monkeypatch):
    """THE SILENT-LOSS BUG. save_spec used to return the spec dict
    whether or not the PATCH succeeded, so the API could answer 'here is
    your blueprint, revision 14' with nothing in the database."""
    fake = _FakeSB(patch_ok=False)
    _wire(monkeypatch, fake)
    with pytest.raises(spec_author.SpecSaveFailed):
        spec_author.save_spec("biz-1", "a fresh document")
    # And the stored spec is untouched — the old revision survives.
    assert fake.config["design_spec"]["revision"] == 13


def test_save_spec_bumps_revision_when_the_write_lands(monkeypatch):
    fake = _FakeSB(patch_ok=True)
    _wire(monkeypatch, fake)
    saved = spec_author.save_spec("biz-1", "a fresh document")
    assert saved["revision"] == 14 and saved["status"] == "draft"
    assert fake.config["design_spec"]["text"] == "a fresh document"


def test_save_spec_returns_none_without_a_site_row(monkeypatch):
    """No site to attach to is a DIFFERENT condition from a failed
    write — harmless, and must not raise."""
    _wire(monkeypatch, _FakeSB(has_row=False))
    assert spec_author.save_spec("biz-1", "doc") is None


def test_set_status_also_verifies_its_write(monkeypatch):
    """Approving a blueprint is the same write through the same door."""
    fake = _FakeSB(patch_ok=False)
    _wire(monkeypatch, fake)
    with pytest.raises(spec_author.SpecSaveFailed):
        spec_author.set_status("biz-1", "approved")


def test_authoring_reports_a_lost_save_without_inviting_a_reretry(monkeypatch):
    """The expensive failure needs different WORDS from the cheap one.

    'The author didn't answer' costs the practitioner nothing. 'We wrote
    it and lost it' already spent their credits — saying only "try again"
    would invite a second full charge while hiding that the first one
    was lost."""
    import site_composer
    monkeypatch.setattr(site_composer, "_spec_inputs",
                        lambda b: ({}, None, []))
    monkeypatch.setattr(spec_author, "author_spec",
                        lambda *a, **k: "a real document")

    def _boom(*a, **k):
        raise spec_author.SpecSaveFailed("PATCH did not land")
    monkeypatch.setattr(spec_author, "save_spec", _boom)

    out = site_composer.author_spec_work("biz-1")
    assert out["ok"] is False
    assert "couldn't be saved" in out["error"]
    assert "nothing was lost" in out["error"].lower()

    # The cheap failure reads differently and says nothing was charged.
    monkeypatch.setattr(spec_author, "author_spec", lambda *a, **k: None)
    out2 = site_composer.author_spec_work("biz-1")
    assert out2["ok"] is False and "didn't answer" in out2["error"]
    assert out2["error"] != out["error"]


def test_revise_refuses_without_a_prior_or_notes(monkeypatch):
    """Honest ok:false results, not crashes — a job carries its reason."""
    import site_composer
    monkeypatch.setattr(spec_author, "get_spec", lambda b: None)
    out = site_composer.author_spec_work("biz-1", notes="bolder", revise=True)
    assert out["ok"] is False and "draft one first" in out["error"]

    monkeypatch.setattr(spec_author, "get_spec", lambda b: {"text": "prior"})
    out2 = site_composer.author_spec_work("biz-1", notes="  ", revise=True)
    assert out2["ok"] is False and "notes are required" in out2["error"]


def test_blueprint_is_a_registered_background_job_kind():
    """The fix for the timeout itself: authoring rides chief_jobs, the
    same road rebuild_site already uses, so the work outlives the tab."""
    import chief_jobs
    for kind in ("author_spec", "revise_spec"):
        assert kind in chief_jobs.KIND_META, kind
        meta = chief_jobs.KIND_META[kind]
        assert meta["nav"] == "build:mysite"
        assert meta["working"] and meta["done"]


def test_spec_usage_row_now_carries_duration(monkeypatch):
    """duration_ms was async-only, so every one of the thirteen prior
    spec runs logged NULL — the one number that would have said whether
    the call was slow enough to time out the browser.

    Asserted BEHAVIOURALLY (what reaches the logger), not by reading the
    source: a test that greps for a variable name passes happily while
    the value it names is wrong."""
    import model_ladder
    import api_usage_logger

    class _Msg:
        stop_reason = "end_turn"
        usage = type("U", (), {"input_tokens": 30594, "output_tokens": 7800})()
        content = [type("B", (), {"type": "text", "text": "THE DOCUMENT"})()]

    def _slow_call(fn, **kw):
        import time as _t
        _t.sleep(0.05)                 # 50ms of measurable wall-clock
        return _Msg(), "claude-sonnet-5"

    logged = {}
    monkeypatch.setattr(model_ladder, "call_with_ladder", _slow_call)
    monkeypatch.setattr(api_usage_logger, "log_api_usage_sync",
                        lambda **kw: logged.update(kw))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(spec_author.llm_call, "sdk_client",
                        lambda **kw: object())

    out = spec_author._call_llm("sys", "user", "biz-1")
    assert out == "THE DOCUMENT"
    assert logged["endpoint"] == "/composer/spec"
    assert logged["duration_ms"] >= 50, logged
    assert logged["output_tokens"] == 7800
