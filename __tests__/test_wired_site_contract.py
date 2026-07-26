"""
test_wired_site_contract.py — THE WIRED-SITE CONTRACT (2026-07-26).

Kevin's ruling: the old interview's capability toggles ("BOOKING", …)
kept the builder from forgetting to wire connected systems into the
site; the Design Coach retired the form and lost the contract. This
suite pins its return at every layer: the dossier section, the coach's
mirror + normalized saves, the builder's CONNECTED SYSTEMS block and
deterministic door check, and Chief's chat-side verb.
"""
import json
from unittest import mock

import builder_v2 as v2
import design_coach as dc
import discovery


# ─── the dossier layer ───────────────────────────────────────────────

def test_empty_dossier_carries_capabilities_section():
    assert discovery._empty_dossier().get("capabilities") == {}


def test_practitioner_patch_accepts_capabilities():
    out = discovery.apply_practitioner_patch(
        discovery._empty_dossier(),
        {"capabilities": {"booking": {"value": "on", "source": "asked"}}})
    assert out["capabilities"]["booking"]["value"] == "on"


def test_digest_carries_capabilities_to_the_director():
    d = discovery._empty_dossier()
    d["identity"] = {"one_liner": {"value": "x", "source": "asked"}}
    d["capabilities"] = {"booking": {"value": "on", "source": "asked"}}
    digest = discovery.dossier_digest(d)
    assert "capabilities" in digest and "booking" in digest


# ─── the coach layer ─────────────────────────────────────────────────

def _turn(**over):
    base = {"reply": "ok", "chips": [], "saves": [], "stage": "truth",
            "done": False}
    base.update(over)
    return json.dumps(base)


def test_coach_saves_normalize_capabilities_to_on_off():
    out = dc.parse_turn(_turn(saves=[
        {"section": "capabilities", "field": "booking", "value": "Yes"},
        {"section": "capabilities", "field": "store", "value": "off"},
        {"section": "capabilities", "field": "booking", "value": "maybe"},
        {"section": "capabilities", "field": "hacking", "value": "on"},
    ]))
    assert out["saves"] == [
        {"section": "capabilities", "field": "booking", "value": "on"},
        {"section": "capabilities", "field": "store", "value": "off"},
    ]


def test_coach_prompt_teaches_the_working_doors():
    s = dc._SYSTEM
    assert "WORKING DOORS" in s
    assert "capabilities: booking, store" in s
    # confirm-from-truth, never blind
    assert "CONNECTED SYSTEMS" in s or "context doesn't list" in s


def test_known_context_mirrors_connected_systems():
    state = {"booking_enabled": True,
             "booking_url": "https://kmj.example/book",
             "store_url": "https://kmj.example/store",
             "site_slug": "kmj", "stripe_connected": False}
    with mock.patch("offering_profiles.business_state",
                    return_value=state):
        ctx = dc._known_context("b1")
    assert "CONNECTED SYSTEMS" in ctx
    assert "https://kmj.example/book" in ctx
    assert "https://kmj.example/store" in ctx


def test_known_context_omits_doors_the_platform_lacks():
    state = {"booking_enabled": False, "booking_url": "",
             "store_url": "", "site_slug": "", "stripe_connected": False}
    with mock.patch("offering_profiles.business_state",
                    return_value=state):
        ctx = dc._known_context("b1")
    assert "CONNECTED SYSTEMS" not in ctx


# ─── the builder layer ───────────────────────────────────────────────

_STATE = {"booking_enabled": True,
          "booking_url": "https://kmj.example/book",
          "store_url": "https://kmj.example/store",
          "site_slug": "kmj", "stripe_connected": False}


def _ctx(caps=None):
    dossier = {"capabilities": caps or {}}
    return {"site": {"site_config": {"discovery_dossier": dossier}}}


def test_connected_block_lists_live_doors_and_honors_owner_off():
    with mock.patch("offering_profiles.business_state",
                    return_value=dict(_STATE)), \
         mock.patch.object(v2, "_store_has_products", return_value=True):
        on = v2.connected_systems_block("b1", _ctx())
        assert "BOOKING: ON" in on and "https://kmj.example/book" in on
        assert "STORE: ON" in on
        # the owner's OFF wins over system truth
        off = v2.connected_systems_block(
            "b1", _ctx({"booking": {"value": "off", "source": "asked"}}))
        assert "BOOKING" not in off and "STORE: ON" in off


def test_connected_block_skips_empty_store():
    with mock.patch("offering_profiles.business_state",
                    return_value=dict(_STATE)), \
         mock.patch.object(v2, "_store_has_products", return_value=False):
        block = v2.connected_systems_block("b1", _ctx())
    assert "STORE" not in block and "BOOKING: ON" in block


def test_check_connected_flags_missing_door_url():
    data = ("CONNECTED SYSTEMS (working doors ...):\n"
            "- BOOKING: ON — every book/schedule action links to "
            "https://kmj.example/book")
    missing = v2.check_connected("<html><body>no door</body></html>", data)
    assert len(missing) == 1 and "BOOKING" in missing[0]
    ok = v2.check_connected(
        '<html><a href="https://kmj.example/book">Book</a></html>', data)
    assert ok == []
    # no block, no checks
    assert v2.check_connected("<html></html>", "BUSINESS: x") == []


def test_builder_and_spec_prompts_carry_the_connected_doors_law():
    assert "CONNECTED DOORS" in v2._SYSTEM
    import spec_author
    assert "THE CONNECTED DOORS" in spec_author._SYSTEM


# ─── the chief layer ─────────────────────────────────────────────────

def test_set_site_capability_is_registered_and_taught():
    import chief_of_staff as cos
    assert "set_site_capability" in cos.ACTION_HANDLERS
    assert cos.ACTION_HANDLERS["set_site_capability"] \
        is cos.handle_set_site_capability
