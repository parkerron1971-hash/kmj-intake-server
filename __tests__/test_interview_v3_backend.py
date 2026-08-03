"""Interview v3 backend tests (docs/CHIEF_GUIDED_INTERVIEW.md §4, B1–B6).

B1 — hero_verbs + inspiration_notes sanitize allowlist entries (R1: fields
     and allowlist entries ship in the same arc), intake-assembly labels.
B2 — GET /composer/interview/prefill/{business_id}: owner gate, exact
     response shape, null-prefs path, fail-soft.
B3 — POST /composer/interview/probe: mocked-LLM followup parse, CLEAR →
     null, error/timeout → null, per-business 6/hour rate limit → 429.
B4 — anti-convergence owner-direction exemption in agents/composer/drl.
B6 — POST /composer/interview/events: lenient validation, request cap 50,
     ring buffer cap 200.
"""
from __future__ import annotations

import json
import sys
import pathlib
import types

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import site_composer as sc  # noqa: E402
import site_llm  # noqa: E402
import rate_limit  # noqa: E402
from agents.composer.drl import passes as drl_passes  # noqa: E402
from agents.composer.drl import signals as drl_sig  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402


# ── shared fakes ────────────────────────────────────────────────────

def _user(uid):
    return types.SimpleNamespace(id=uid)


@pytest.fixture
def fb(monkeypatch):
    store = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", store.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer="rep": store.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", store.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", store.delete)
    return store


def _seed_business(store, bid="biz1", owner="owner-1", settings=None):
    store.rows("businesses").append(
        {"id": bid, "owner_id": owner, "settings": settings or {}})


def _settings_full():
    return {
        "site_prefs": {"offer": "I build brands", "feel_words": ["warm"]},
        "brand_kit": {
            "colors": {"primary": "#111111", "secondary": "#222222",
                       "accent": "#00ff59", "background": "#fafafa",
                       "text": "#0a0a0a"},
            "font_heading": "Fraunces", "font_body": "Inter",
            "fonts_locked": True,
            "visual_style": "quiet, editorial, unhurried",
        },
        "website_content": {"testimonials": [
            {"quote": "great", "show_on_website": True},
            {"quote": "hidden", "show_on_website": False},
            "legacy string row",
        ]},
        "media_library": {"gallery": [
            {"url": "https://x/1.jpg"},
            {"url": "https://x/2.jpg", "show_on_website": False},
            {"url": ""},
            {"no_url": True},
        ]},
    }


# ── B1: sanitize_design_prefs ───────────────────────────────────────

class TestB1Sanitize:
    def test_round_trip(self):
        out = sc.sanitize_design_prefs({
            "hero_verbs": ["build", "BRAND", "grow"],
            "inspiration_notes": "the space and the type"})
        assert out["hero_verbs"] == ["build", "BRAND", "grow"]
        assert out["inspiration_notes"] == "the space and the type"

    def test_trims_and_drops_empties(self):
        out = sc.sanitize_design_prefs(
            {"hero_verbs": ["  build  ", "", "   ", "grow"]})
        assert out["hero_verbs"] == ["build", "grow"]

    def test_caps_enforced(self):
        out = sc.sanitize_design_prefs({
            "hero_verbs": ["a" * 40, "one", "two", "three", "four"],
            "inspiration_notes": "n" * 500})
        assert out["hero_verbs"] == ["a" * 24, "one", "two"]   # ≤3, ≤24 each
        assert len(out["inspiration_notes"]) == 400            # ≤400

    def test_empty_after_cleaning_omitted(self):
        assert sc.sanitize_design_prefs({"hero_verbs": ["", "  "]}) is None
        assert sc.sanitize_design_prefs({"inspiration_notes": "   "}) is None

    def test_non_list_hero_verbs_dropped(self):
        out = sc.sanitize_design_prefs(
            {"hero_verbs": "build", "notes": "keep me"})
        assert "hero_verbs" not in out
        assert out["notes"] == "keep me"

    def test_unknown_keys_still_dropped(self):
        assert sc.sanitize_design_prefs({"brand_new_field": "x"}) is None
        out = sc.sanitize_design_prefs(
            {"notes": "real", "evil_key": {"nested": True}})
        assert out == {"notes": "real"}

    def test_existing_fields_untouched(self):
        # R1/regression: the v2 fields round-trip exactly as before.
        out = sc.sanitize_design_prefs({
            "feel_words": ["warm", "quiet", "bold", "dropped"],
            "type_personality": "EDITORIAL",
            "colors": {"use_brand": False, "direction": "deep_dark",
                       "love": ["#123456"]},
            "boldness": 2, "cta_goal": "book"})
        assert out["feel_words"] == ["warm", "quiet", "bold"]
        assert out["type_personality"] == "editorial"
        assert out["colors"]["love"] == ["#123456"]
        assert out["boldness"] == 2


class TestB1IntakeText:
    def _ctx(self, prefs):
        return {"bundle": {}, "business": {"name": "KMJ", "type": "studio"},
                "settings": {}, "offerings": [], "testimonials": [],
                "site_prefs": prefs}

    def test_labeled_lines_present(self):
        text = sc._assemble_intake_text(self._ctx({
            "hero_verbs": ["build", "brand", "grow"],
            "inspiration_notes": "the whitespace"}))
        assert ("Owner's three verbs (hero material): build, brand, grow"
                in text)
        assert ("What the owner loves about their inspiration sites: "
                "the whitespace" in text)

    def test_absent_fields_byte_identical(self):
        # The new lines render only when the fields are present.
        text = sc._assemble_intake_text(self._ctx({"notes": "plain"}))
        assert "hero material" not in text
        assert "inspiration sites" not in text


# ── B2: GET /composer/interview/prefill/{business_id} ───────────────

class TestB2Prefill:
    def test_non_owner_403(self, fb):
        _seed_business(fb, settings=_settings_full())
        with pytest.raises(HTTPException) as ei:
            sc.interview_prefill("biz1", user=_user("someone-else"))
        assert ei.value.status_code == 403

    def test_unknown_business_404(self, fb):
        with pytest.raises(HTTPException) as ei:
            sc.interview_prefill("nope", user=_user("owner-1"))
        assert ei.value.status_code == 404

    def test_shape_and_values(self, fb, monkeypatch):
        _seed_business(fb, settings=_settings_full())
        fb.rows("offerings").append({
            "id": "o1", "business_id": "biz1", "is_active": True,
            "name": "Brand sprint", "price": "1200",
            "description": "d" * 50})
        fb.rows("offerings").append({
            "id": "o2", "business_id": "biz1", "is_active": True,
            "name": "Thin", "price": None, "description": "short"})
        fb.rows("offerings").append({
            "id": "o3", "business_id": "biz1", "is_active": False,
            "name": "Inactive", "price": "5", "description": "d" * 50})
        import brand_engine
        monkeypatch.setattr(brand_engine, "get_bundle", lambda bid: {
            "practitioner_intelligence": {"about_business": "a" * 100},
            "voice": {"audience": "busy founders"}})

        out = sc.interview_prefill("biz1", user=_user("owner-1"))

        assert set(out.keys()) == {"site_prefs", "brand_design", "signals",
                                   "media"}
        assert out["site_prefs"] == {"offer": "I build brands",
                                     "feel_words": ["warm"]}
        assert out["brand_design"] == {
            "accent_color": "#00ff59", "primary_color": "#111111",
            "secondary_color": "#222222", "background_color": "#fafafa",
            "text_color": "#0a0a0a", "font_heading": "Fraunces",
            "font_body": "Inter", "fonts_locked": True,
            # Beat 6 offers this back for confirmation; the fixture's
            # site_prefs carries no confirmed answer, so the Brand Room's
            # stored sentence is what surfaces.
            "visual_style": "quiet, editorial, unhurried"}
        assert out["signals"] == {
            "offer_clear": True, "audience_known": True, "has_about": True,
            "offer_count": 2, "testimonial_count": 1}
        assert out["media"] == {"gallery_photos": 1}

    def test_legacy_flat_primary_color(self, fb, monkeypatch):
        _seed_business(fb, settings={
            "brand_kit": {"primary_color": "#abcdef"}})
        import brand_engine
        monkeypatch.setattr(brand_engine, "get_bundle", lambda bid: {})
        out = sc.interview_prefill("biz1", user=_user("owner-1"))
        assert out["brand_design"]["primary_color"] == "#abcdef"
        assert out["brand_design"]["accent_color"] is None
        assert out["brand_design"]["fonts_locked"] is False

    def test_null_prefs_and_fail_soft(self, fb, monkeypatch):
        _seed_business(fb, settings={})     # nothing stored at all
        import brand_engine
        def boom(bid):
            raise RuntimeError("bundle exploded")
        monkeypatch.setattr(brand_engine, "get_bundle", boom)
        out = sc.interview_prefill("biz1", user=_user("owner-1"))
        assert out["site_prefs"] is None
        assert out["signals"] == {
            "offer_clear": False, "audience_known": False,
            "has_about": False, "offer_count": 0, "testimonial_count": 0}
        assert out["media"] == {"gallery_photos": 0}


# ── Visual style, confirmed at intake (2026-08-03) ──────────────────
#
# The Brand Room stores a one-line visual style, but taste moves. Beat 6
# offers it back; the value that reaches the build is the CONFIRMED one.
# Rule: a change mirrors back to the brand kit, a plain confirm does not.

class TestVisualStyleConfirmation:
    def test_prefill_prefers_a_previously_confirmed_answer(self, fb):
        """site_prefs beats the brand kit — re-asking a question they
        already answered would read as the system forgetting."""
        settings = _settings_full()
        settings["site_prefs"]["visual_style"] = "louder, more color"
        _seed_business(fb, settings=settings)
        out = sc.interview_prefill("biz1", user=_user("owner-1"))
        assert out["brand_design"]["visual_style"] == "louder, more color"

    def test_prefill_empty_when_nothing_stored(self, fb):
        _seed_business(fb, settings={})
        out = sc.interview_prefill("biz1", user=_user("owner-1"))
        assert out["brand_design"]["visual_style"] == ""

    def test_sanitize_trims_and_caps(self):
        out = sc.sanitize_design_prefs({"visual_style": "  spacious  "})
        assert out["visual_style"] == "spacious"
        long = sc.sanitize_design_prefs({"visual_style": "x" * 900})
        assert len(long["visual_style"]) == sc._PREF_STR_CAP
        # Blank / wrong type never creates the key.
        assert sc.sanitize_design_prefs({"visual_style": "   "}) is None
        assert sc.sanitize_design_prefs({"visual_style": 42}) is None

    def _kit_style(self, fb):
        return (fb.rows("businesses")[0]["settings"]
                .get("brand_kit", {}).get("visual_style"))

    def test_change_mirrors_back_to_the_brand_kit(self, fb):
        _seed_business(fb, settings=_settings_full())
        sc._persist_site_prefs("biz1", {"visual_style": "loud and modern"})
        assert self._kit_style(fb) == "loud and modern"
        # …and the confirmed answer is also on site_prefs for the build.
        sp = fb.rows("businesses")[0]["settings"]["site_prefs"]
        assert sp["visual_style"] == "loud and modern"

    def test_plain_confirm_does_not_touch_the_brand_kit(self, fb):
        """Tapping 'still right' sends back the identical string. The kit
        object must come out unchanged — no rewrite, no history churn."""
        settings = _settings_full()
        _seed_business(fb, settings=settings)
        before = dict(fb.rows("businesses")[0]["settings"]["brand_kit"])
        sc._persist_site_prefs("biz1",
                               {"visual_style": "quiet, editorial, unhurried"})
        assert fb.rows("businesses")[0]["settings"]["brand_kit"] == before

    def test_absent_visual_style_leaves_the_kit_alone(self, fb):
        """Owners who never reach beat 6 (or clear the field) must not have
        their stored sentence wiped."""
        _seed_business(fb, settings=_settings_full())
        sc._persist_site_prefs("biz1", {"feel_words": ["calm"]})
        assert self._kit_style(fb) == "quiet, editorial, unhurried"

    def test_confirmed_style_reaches_the_intake_text(self):
        """The whole point: the sentence becomes evidence the design pass
        can quote. Unconfirmed brand-kit text alone must NOT appear."""
        ctx = {
            "business": {"name": "KMJ", "type": "studio"},
            "bundle": {}, "settings": {"brand_kit": {
                "visual_style": "never confirmed"}},
            "site_prefs": {"visual_style": "airy, generous, unhurried"},
            "offerings": [],
        }
        text = sc._assemble_intake_text(ctx)
        assert "airy, generous, unhurried" in text
        assert "never confirmed" not in text


# ── B3: POST /composer/interview/probe ──────────────────────────────

def _llm_msg(text):
    return types.SimpleNamespace(
        content=[types.SimpleNamespace(type="text", text=text)],
        model="fake")


@pytest.fixture
def probe_env(fb, monkeypatch):
    _seed_business(fb, bid="biz-probe")
    rate_limit._buckets.clear()             # in-process limiter isolation
    calls = []

    def fake_create(**kw):
        calls.append(kw)
        return _llm_msg("What do clients thank you for most?")
    monkeypatch.setattr(site_llm, "create_message", fake_create)
    return calls


def _probe(bid="biz-probe", answer="I do design stuff"):
    return sc.interview_probe(
        sc.InterviewProbeBody(business_id=bid, beat_id=1, answer=answer,
                              context={"business_name": "KMJ",
                                       "type": "studio"}),
        user=_user("owner-1"))


class TestB3Probe:
    def test_followup_parsed(self, probe_env):
        out = _probe()
        assert out == {"followup": "What do clients thank you for most?"}
        kw = probe_env[0]
        assert kw["max_tokens"] == 150
        assert kw["timeout"] == 10.0
        assert "CLEAR" in kw["system"]

    def test_clear_means_null(self, probe_env, monkeypatch):
        monkeypatch.setattr(site_llm, "create_message",
                            lambda **kw: _llm_msg("CLEAR"))
        assert _probe() == {"followup": None}
        monkeypatch.setattr(site_llm, "create_message",
                            lambda **kw: _llm_msg("CLEAR."))
        assert _probe() == {"followup": None}

    def test_empty_means_null(self, probe_env, monkeypatch):
        monkeypatch.setattr(site_llm, "create_message",
                            lambda **kw: _llm_msg("   "))
        assert _probe() == {"followup": None}

    def test_error_and_timeout_fail_silent(self, probe_env, monkeypatch):
        def boom(**kw):
            raise TimeoutError("10s budget blown")
        monkeypatch.setattr(site_llm, "create_message", boom)
        assert _probe() == {"followup": None}

    def test_empty_answer_skips_llm(self, probe_env):
        assert _probe(answer="   ") == {"followup": None}
        assert probe_env == []               # no LLM call spent

    def test_non_owner_403(self, probe_env):
        with pytest.raises(HTTPException) as ei:
            sc.interview_probe(
                sc.InterviewProbeBody(business_id="biz-probe", beat_id=1,
                                      answer="x"),
                user=_user("intruder"))
        assert ei.value.status_code == 403

    def test_seventh_call_in_an_hour_429s(self, probe_env):
        for _ in range(6):
            assert _probe()["followup"] is not None
        with pytest.raises(HTTPException) as ei:
            _probe()
        assert ei.value.status_code == 429
        assert ei.value.headers.get("Retry-After") == "3600"


# ── B4: anti-convergence owner-direction exemption ──────────────────

def _dro(**dec_over):
    decisions = {
        "palette": {"base": "deep_dark", "accent_strategy": "single_semantic",
                    "temperature": "warm"},
        "typography": {"display_personality": "condensed_impact"},
        "layout": {"symmetry": "centered_formal", "density": "airy"},
        "motion": {"temperature": "subtle_entrance"},
        "hero_concept": {"direction": "typographic_statement"},
        "whitespace": {"philosophy": "confidence_air"},
        "voice_to_visual": {"notes": []},
    }
    for k, v in dec_over.items():
        decisions.setdefault(k, {}).update(v)
    for block in decisions.values():
        block.setdefault("because", "fixture")
        block.setdefault("from_signals", [])
    return {"decisions": decisions}


# A recent cohort member sharing SIX axes with _dro(): palette.* (0-2),
# typography.display_personality (3), layout.symmetry (4), layout.density
# (5) — differing only on motion (6) and hero direction (7).
def _recent_cohort_member():
    return _dro(motion={"temperature": "expressive"},
                hero_concept={"direction": "portrait_presence"})


class TestB4ExemptAxes:
    def test_no_evidence_no_exemption(self):
        assert drl_passes.owner_exempt_axes() == set()
        assert drl_passes.owner_exempt_axes(site_prefs={"notes": "hi"}) == set()

    def test_type_personality_exempts_typography(self):
        ex = drl_passes.owner_exempt_axes(
            site_prefs={"type_personality": "editorial"})
        assert ex == {drl_sig.DISTINCTIVENESS_AXES.index(
            "typography.display_personality")}

    def test_fonts_pinned_exempts_typography(self):
        ex = drl_passes.owner_exempt_axes(fonts_pinned=True)
        assert ex == {drl_sig.DISTINCTIVENESS_AXES.index(
            "typography.display_personality")}

    def test_colors_love_exempts_palette(self):
        ex = drl_passes.owner_exempt_axes(
            site_prefs={"colors": {"love": ["#123456"]}})
        assert ex == {drl_sig.DISTINCTIVENESS_AXES.index(a) for a in
                      ("palette.base", "palette.accent_strategy",
                       "palette.temperature")}

    def test_inspiration_requires_successful_analysis(self):
        # URLs alone: nothing. A failed analysis: nothing.
        assert drl_passes.owner_exempt_axes(
            site_prefs={"inspiration_urls": ["https://a.com"]}) == set()
        assert drl_passes.owner_exempt_axes(
            site_prefs={"inspiration_urls": ["https://a.com"]},
            reference_analysis=[{"ok": False, "url": "https://a.com"}]) == set()
        ex = drl_passes.owner_exempt_axes(
            site_prefs={"inspiration_urls": ["https://a.com"]},
            reference_analysis=[{"ok": True, "url": "https://a.com"}])
        assert ex == {drl_sig.DISTINCTIVENESS_AXES.index(a) for a in
                      ("palette.base", "palette.accent_strategy",
                       "palette.temperature",
                       "typography.display_personality", "layout.density")}


class TestB4CollisionGate:
    def test_type_axis_match_not_rerolled_with_owner_choice(self):
        # THE spec case (§9.8): the fixture DRO shares 6/8 axes with the
        # cohort — over threshold — but one is typography, which the owner
        # explicitly chose. Without the exemption it collides; with it,
        # 5/8 on the remaining axes = no re-roll.
        dro, recent = _dro(), [_recent_cohort_member()]
        assert drl_passes._collides(dro, recent) is True     # baseline fires
        exempt = drl_passes.owner_exempt_axes(
            site_prefs={"type_personality": "editorial"})
        assert drl_passes._collides(dro, recent, exempt=exempt) is False
        check = drl_passes.run_distinctiveness(dro, recent, exempt=exempt)
        assert check["verdict"] == "distinct"
        assert check["axes_shared_with_nearest"] == 5

    def test_other_axes_keep_pressure(self):
        # A cohort member sharing 6 NON-exempt axes still collides even
        # with a type_personality exemption in force.
        recent = [_dro(typography={"display_personality": "editorial_serif"},
                       hero_concept={"direction": "portrait_presence"})]
        # shared: palette.*(0-2), layout.symmetry(4), layout.density(5),
        # motion(6) = 6 axes, typography NOT among them.
        exempt = drl_passes.owner_exempt_axes(
            site_prefs={"type_personality": "editorial"})
        assert drl_passes._collides(_dro(), recent) is True
        assert drl_passes._collides(_dro(), recent, exempt=exempt) is True

    def test_author_dro_skips_collision_regen(self, monkeypatch):
        calls = {"n": 0}
        monkeypatch.setattr(drl_passes, "_client", lambda: object())

        def fake_call(client, system, user, **kw):
            calls["n"] += 1
            return json.dumps(_dro())
        monkeypatch.setattr(drl_passes, "_call", fake_call)

        dro = drl_passes.author_dro(
            "biz-x", [], [_recent_cohort_member()],
            owner_direction={"site_prefs": {"type_personality": "editorial"},
                             "fonts_pinned": False})
        assert dro is not None
        assert calls["n"] == 1            # no regeneration was triggered

    def test_author_dro_still_regens_without_evidence(self, monkeypatch):
        calls = {"n": 0}
        monkeypatch.setattr(drl_passes, "_client", lambda: object())

        def fake_call(client, system, user, **kw):
            calls["n"] += 1
            return json.dumps(_dro())
        monkeypatch.setattr(drl_passes, "_call", fake_call)

        dro = drl_passes.author_dro("biz-x", [], [_recent_cohort_member()])
        assert dro is not None
        assert calls["n"] == 2            # collision regen fired as before
        assert (dro["anti_convergence"]["distinctiveness_check"]["verdict"]
                == "regenerated_once")


# ── B6: POST /composer/interview/events ─────────────────────────────

@pytest.fixture
def events_env(fb):
    _seed_business(fb, bid="biz-ev")
    return fb


def _events(bid="biz-ev", events=None):
    return sc.interview_events(
        sc.InterviewEventsBody(business_id=bid, events=events or []),
        user=_user("owner-1"))


def _stored_events(fb, bid="biz-ev"):
    return (fb.rows("businesses")[0].get("settings") or {}).get(
        "interview_events") or []


class TestB6Events:
    def test_append(self, events_env):
        out = _events(events=[
            {"beat": 1, "event": "start", "at": "2026-07-19T10:00:00Z"},
            {"beat": 1, "event": "answer", "at": "2026-07-19T10:00:20Z"}])
        assert out == {"ok": True, "accepted": 2}
        buf = _stored_events(events_env)
        assert [e["event"] for e in buf] == ["start", "answer"]
        assert buf[0]["beat"] == 1

    def test_lenient_validation_drops_bad_rows(self, events_env):
        out = _events(events=[
            {"beat": 1, "event": "start"},
            {"beat": 2, "event": "bogus_kind"},        # bad enum → dropped
            {"event": "skip"},                          # no beat → dropped
            "not-a-dict",                               # → dropped
            {"beat": 3, "event": "skip", "at": "now"},
        ])
        assert out == {"ok": True, "accepted": 2}
        buf = _stored_events(events_env)
        assert [(e["beat"], e["event"]) for e in buf] == [(1, "start"),
                                                          (3, "skip")]

    def test_every_event_kind_accepted(self, events_env):
        kinds = ["start", "answer", "skip", "edit_back", "probe",
                 "skip_to_summary", "submit"]
        out = _events(events=[{"beat": i, "event": k}
                              for i, k in enumerate(kinds)])
        assert out["accepted"] == len(kinds)

    def test_request_capped_at_50(self, events_env):
        out = _events(events=[{"beat": 1, "event": "answer"}
                              for _ in range(60)])
        assert out["accepted"] == 50
        assert len(_stored_events(events_env)) == 50

    def test_ring_buffer_caps_at_200(self, events_env):
        seeded = [{"beat": 0, "event": "start", "at": i} for i in range(190)]
        events_env.rows("businesses")[0]["settings"] = {
            "interview_events": seeded}
        out = _events(events=[{"beat": 9, "event": "submit", "at": "new-%d" % i}
                              for i in range(50)])
        assert out["accepted"] == 50
        buf = _stored_events(events_env)
        assert len(buf) == 200                  # 190 + 50 = 240 → trimmed
        assert buf[-1]["at"] == "new-49"        # newest kept
        assert buf[0]["at"] == 40               # oldest 40 dropped

    def test_all_bad_rows_no_write(self, events_env):
        out = _events(events=[{"event": "nope"}])
        assert out == {"ok": True, "accepted": 0}
        assert _stored_events(events_env) == []

    def test_non_owner_403(self, events_env):
        with pytest.raises(HTTPException) as ei:
            sc.interview_events(
                sc.InterviewEventsBody(business_id="biz-ev",
                                       events=[{"beat": 1, "event": "start"}]),
                user=_user("intruder"))
        assert ei.value.status_code == 403
