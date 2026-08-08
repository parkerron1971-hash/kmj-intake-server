"""
test_pricing_config_dials.py — the config-driven credit system
(Kevin's ruling 2026-08-08: launch on conservative opening defaults,
refine against real data once the meter works).

Two things are under test here:

  1. THE METER READS AT ALL. usage_metering._month_start_iso() emitted
     `+00:00`, which decodes as a SPACE in a PostgREST query string, so
     Postgres answered `22007: invalid input syntax for type timestamp
     with time zone` on every usage read. PostgREST 400'd, the sb helper
     returned None, `or []` swallowed it, and weighted_usage_this_month()
     returned 0 for EVERY business forever — meter blank, credits never
     drawn down, every require_units() gate passing unconditionally.
     This is the regression test for that.

  2. EVERY PRICE IS A DIAL. No test below pins a price as a literal
     except where the literal IS the shipped default under test.
"""
import importlib
import os

import pytest


# ─── 1. The meter-reads-zero regression ──────────────────────────────

def test_month_start_iso_uses_z_form_not_plus_offset():
    """THE bug that made the whole billing system inert.

    `+00:00` in a query string decodes to a space. Postgres rejects
    "2026-08-01T00:00:00 00:00" outright (22007) — verified against the
    live database on 2026-08-08 — so the filter never matched anything.
    PR #196 swept this class repo-wide on 2026-07-21; usage_metering
    dates to 2026-06-10 and was missed."""
    import usage_metering as um
    s = um._month_start_iso()
    assert s.endswith("Z"), s
    assert "+00:00" not in s
    assert " " not in s          # the actual failure mode, stated plainly
    assert s[4] == "-" and s[8:11] == "01T"   # first instant of the month


def test_day_start_iso_uses_z_form():
    """Same rule for the fair-use window — a new query-string timestamp
    is exactly where this bug class reappears."""
    import usage_metering as um
    s = um._day_start_iso()
    assert s.endswith("Z") and "+00:00" not in s and " " not in s
    assert s.endswith("T00:00:00Z")


def test_next_month_start_iso_uses_z_form():
    """Returned to the UI rather than interpolated into a filter, but a
    module that emits two timestamp shapes is a trap for whoever copies
    the wrong one into a query next."""
    import usage_metering as um
    assert um._next_month_start_iso().endswith("Z")


def test_billing_limits_month_start_is_also_fixed():
    """The bug had TWO copies. Fixing one would have left
    chief_messages_this_month() reading zero."""
    import billing_limits as bl
    s = bl._month_start_iso()
    assert s.endswith("Z") and "+00:00" not in s and " " not in s


# ─── 2. Dials ────────────────────────────────────────────────────────

def _reload_config():
    import pricing_config
    return importlib.reload(pricing_config)


def test_opening_defaults_are_kevins_ruling(monkeypatch):
    """The 2026-08-08 opening defaults, with every env override cleared.
    These are the numbers we launch on; they are expected to move."""
    for k in list(os.environ):
        if k.startswith(("PRICE_", "CREDITS_", "LIMIT_")) or k in (
                "BUILD_BASE", "BUILD_PER_SECTION", "REVAMP_PRICE",
                "SECTION_REWRITE", "SMALL_EDIT", "HERO_REGEN", "DOC_GEN",
                "STARTER_CREDITS", "PRO_CREDITS", "PRACTICE_CREDITS",
                "CHAT_DAILY_SOFT_CEILING"):
            monkeypatch.delenv(k, raising=False)
    pc = _reload_config()
    assert pc.tier_credits() == {"starter": 3000, "professional": 10000,
                                 "practice": 25000}
    assert pc.build_base() == 600
    assert pc.build_per_section() == 100
    assert pc.revamp_price() == 300
    assert pc.section_rewrite() == 120
    assert pc.small_edit() == 40
    assert pc.hero_regen() == 30
    assert pc.doc_gen() == 40
    assert pc.chat_price() == 1
    assert pc.chat_daily_soft_ceiling() == 250


def test_a_three_section_build_is_20pct_of_the_starter_tank(monkeypatch):
    """The sizing Kevin reasoned from: ~3-section build = 600 credits =
    20% of the Starter tank, so the first build leaves plenty behind
    (3,000 -> 2,400). If a future tuning pass breaks that relationship
    it should be a decision, not a surprise."""
    pc = _reload_config()
    three_section = pc.build_base()          # base already covers ~3 sections
    assert three_section * 5 == pc.tier_credits()["starter"]


@pytest.mark.parametrize("env_name", ["PRICE_BUILD_BASE", "BUILD_BASE"])
def test_every_price_is_env_overridable(monkeypatch, env_name):
    """Both the namespaced and the bare form work: tuning is a Railway
    value change plus a restart, never a code deploy."""
    monkeypatch.setenv(env_name, "999")
    pc = _reload_config()
    assert pc.build_base() == 999
    assert pc.unit_weights()["/composer/compose"] == 999


def test_namespaced_env_wins_over_bare(monkeypatch):
    monkeypatch.setenv("BUILD_BASE", "111")
    monkeypatch.setenv("PRICE_BUILD_BASE", "222")
    pc = _reload_config()
    assert pc.build_base() == 222


def test_a_typoed_dial_falls_back_to_the_default_not_to_zero(monkeypatch):
    """Fail SAFE and LOUD. A malformed value must never price an action
    at zero — that is a silent revenue hole, which is the exact failure
    class this whole arc exists to close."""
    monkeypatch.setenv("PRICE_BUILD_BASE", "6oo")
    pc = _reload_config()
    assert pc.build_base() == 600


def test_tier_credits_reach_plan_limits(monkeypatch):
    """The grant the practitioner actually receives comes from config —
    not a second hardcoded copy in feature_gates."""
    monkeypatch.setenv("CREDITS_STARTER_CREDITS", "4321")
    import pricing_config
    importlib.reload(pricing_config)
    import feature_gates
    importlib.reload(feature_gates)
    assert (feature_gates.plan_limits()["starter"]["chief_messages_monthly"]
            == 4321)


def test_every_priced_endpoint_is_a_label_something_actually_logs():
    """THE /director/build LESSON, pinned.

    The old table keyed 25 credits to "/director/build" — an endpoint
    NOTHING logged — so a $2 build metered as a handful of weight-1 rows
    and the allowance economics silently did not hold. A price on a
    label that never appears is not a price; it is a zero.

    Every key must be a string this repo really passes to the usage
    logger (or the documented legacy marker kept for historical rows)."""
    import re
    import pathlib
    import pricing_config as pc

    root = pathlib.Path(__file__).resolve().parent.parent
    logged = set()
    for path in root.rglob("*.py"):
        if "__tests__" in path.parts or ".venv" in path.parts:
            continue
        try:
            src = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        logged.update(re.findall(r'endpoint=f?"(/[^"{]*)"', src))
    # The DRL passes build their label from an f-string: /composer/drl/{task}
    logged.update({"/composer/drl/dro", "/composer/drl/dro_minimal",
                   "/composer/drl/signals"})
    # Documented legacy: retired engine, kept so historical rows price.
    legacy = {"/director/build"}

    priced = set(pc.unit_weights())
    orphans = priced - logged - legacy
    assert not orphans, (
        f"priced endpoints that nothing logs (silent zeros): {sorted(orphans)}")


# ─── 3. The chat fair-use brake ──────────────────────────────────────

def test_chat_ceiling_is_independent_of_billing_enforce(monkeypatch):
    """Abuse protection, not billing. Gating it behind BILLING_ENFORCE
    would ship it as a no-op on day one and leave the platform with no
    per-account runaway brake during the beta month it was built for."""
    monkeypatch.delenv("BILLING_ENFORCE", raising=False)   # enforcement OFF
    monkeypatch.setenv("CHAT_DAILY_SOFT_CEILING", "3")
    import pricing_config
    importlib.reload(pricing_config)
    import usage_metering as um
    importlib.reload(um)
    monkeypatch.setattr(um, "chat_turns_today", lambda b: 3)
    assert um.chat_fair_use_ok("b1") is False
    monkeypatch.setattr(um, "chat_turns_today", lambda b: 2)
    assert um.chat_fair_use_ok("b1") is True


def test_chat_ceiling_can_be_disabled_two_ways(monkeypatch):
    """A brake with no off switch is a brake nobody dares ship."""
    import pricing_config
    import usage_metering as um

    monkeypatch.setenv("CHAT_DAILY_SOFT_CEILING", "0")     # 0 = no ceiling
    importlib.reload(pricing_config)
    importlib.reload(um)
    monkeypatch.setattr(um, "chat_turns_today", lambda b: 99999)
    assert um.chat_fair_use_ok("b1") is True

    monkeypatch.setenv("CHAT_DAILY_SOFT_CEILING", "3")     # observe-only
    monkeypatch.setenv("CHAT_CEILING_ENFORCE", "off")
    importlib.reload(pricing_config)
    importlib.reload(um)
    monkeypatch.setattr(um, "chat_turns_today", lambda b: 500)
    assert um.chat_fair_use_ok("b1") is True


def test_chat_ceiling_fails_open(monkeypatch):
    """A metering read failure must never mute Chief."""
    import usage_metering as um

    def _boom(_b):
        raise RuntimeError("supabase down")

    monkeypatch.setattr(um, "chat_turns_today", _boom)
    assert um.chat_fair_use_ok("b1") is True


def test_fair_use_raises_429_not_402():
    """A rate limit is not a sales opportunity. A human does not reach
    250 turns in a day — the busiest observed human day on the platform
    is 34 — so tripping this is a loop to stop, never a tier to upsell."""
    from fastapi import HTTPException
    import billing_limits as bl
    import usage_metering as um

    orig = um.chat_fair_use_ok
    um.chat_fair_use_ok = lambda b: False
    try:
        with pytest.raises(HTTPException) as ei:
            bl.require_chat_fair_use("b1")
    finally:
        um.chat_fair_use_ok = orig
    assert ei.value.status_code == 429
    assert ei.value.detail["error"] == "chat_daily_limit"
    body = str(ei.value.detail).lower()
    assert "upgrade" not in body and "top up" not in body


# ─── 4. The practitioner-facing price list ───────────────────────────

def test_price_list_is_live_not_hardcoded(monkeypatch):
    """usage_summary()['weights'] used to be a hardcoded {1, 5, 25} that
    the UI displayed as fact while the real table said something else.
    The price list a practitioner reads must be the one they are
    charged."""
    monkeypatch.setenv("PRICE_HERO_REGEN", "77")
    import pricing_config
    importlib.reload(pricing_config)
    import usage_metering as um
    importlib.reload(um)
    assert um.price_list()["hero_regeneration"] == 77
    assert um.price_list()["site_build_base"] == pricing_config.build_base()
