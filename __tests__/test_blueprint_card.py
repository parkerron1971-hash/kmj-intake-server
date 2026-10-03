"""
test_blueprint_card.py — the blueprint in a few plain lines for the chat
card (2026-10-03): Chief brings the Design Coach in, the Director writes
the blueprint, and Chief comes back with the idea, the setting, what is
missing and the price, then asks "build it?".
"""
from unittest import mock

import blueprint_card as bc
import site_concept

SPEC = {"status": "draft",
        "text": "0. THE CONCEPT\nOBJECTS: letterboard, marker\n1. THE PAGE\n..."}


def _ctx(taste=None, signature=None):
    dossier = {}
    if taste:
        dossier["taste"] = taste
    if signature:
        dossier["signature"] = signature
    return {"site": {"site_config": {"discovery_dossier": dossier}}}


def _sheet(**kw):
    return mock.patch.object(site_concept, "parse_sheet", return_value=kw)


def _not_free():
    import usage_metering
    return mock.patch.object(usage_metering, "trial_first_build_is_free",
                             return_value=False)


def test_no_blueprint_no_card():
    assert bc.summary(None, _ctx()) is None
    assert bc.summary({"status": "draft", "text": "  "}, _ctx()) is None


def test_signature_card_reads_the_idea_look_moment_and_objects():
    ctx = _ctx(taste={"look": {"value": "Neon", "source": "asked"}},
               signature={"sharpened": {"value": "the price on the wall"}})
    with _sheet(intensity="signature", scope="site",
                idea="the shop is a working counter"), _not_free():
        card = bc.summary(SPEC, ctx, "b1", plan_sections=0)
    assert card["status"] == "draft"
    assert card["idea"] == "the shop is a working counter"
    assert card["setting"]["key"] == "signature"
    assert card["setting"]["label"] == "Signature"
    assert card["look"] == "neon"
    assert card["moment"] == "the price on the wall"
    assert len(card["objects"]) == 2
    assert card["offer_page"] is None


def test_world_offer_names_the_offer_page_and_prices_it_in():
    with _sheet(intensity="world", scope="offer", idea="a semester",
                scope_raw="offer (The Six-Week Course)"), _not_free():
        card = bc.summary(SPEC, _ctx(), "b1", plan_sections=5)
    assert card["setting"]["key"] == "world-offer"
    assert card["offer_page"]["name"] == "The Six-Week Course"
    assert card["offer_page"]["path"].startswith("/")
    import pricing_config
    assert card["price"]["credits"] == pricing_config.price_for_build(5, offer_page=True)
    assert "offer page" in card["price"]["line"]


def test_world_offer_with_offer_pages_switched_off_has_no_offer_page():
    with _sheet(intensity="world", scope="offer", idea="x",
                scope_raw="offer (The Course)"), _not_free():
        card = bc.summary(SPEC, _ctx(), "b1", plan_sections=5,
                          offer_pages_on=False)
    assert card["offer_page"] is None
    import pricing_config
    assert card["price"]["credits"] == pricing_config.price_for_build(5)


def test_the_owner_pick_fills_in_when_the_sheet_is_silent():
    ctx = _ctx(taste={"concept": {"value": "plain"}})
    with _sheet(), _not_free():
        card = bc.summary(SPEC, ctx, "b1")
    assert card["setting"]["key"] == "plain"


def test_price_without_a_plan_states_the_rule_not_a_guess():
    import pricing_config
    with _not_free():
        p = bc.price("b1", 0, offer_page=False)
    assert p["free"] is False
    assert p["credits"] == pricing_config.build_base()
    assert "sections included" in p["line"]
    assert "Charged only when the site is ready" in p["line"]


def test_trial_first_build_is_free_on_the_card():
    import usage_metering
    with mock.patch.object(usage_metering, "trial_first_build_is_free",
                           return_value=True):
        p = bc.price("b1", 6, offer_page=True)
    assert p == {"free": True, "credits": 0,
                 "line": "Your first build is on the house."}


def test_a_failing_trial_check_shows_the_price():
    import usage_metering
    with mock.patch.object(usage_metering, "trial_first_build_is_free",
                           side_effect=RuntimeError("db down")):
        p = bc.price("b1", 4, offer_page=False)
    assert p["free"] is False and p["credits"] > 0


def _session(uid="u1"):
    return type("S", (), {"user": type("U", (), {"id": uid})()})()


def test_the_blueprint_read_carries_the_card():
    import site_composer as sc
    import spec_author
    ctx = {"site": {"site_config": {}}}
    with mock.patch.object(sc, "_require_owner"), \
            mock.patch.object(spec_author, "get_spec", return_value=SPEC), \
            mock.patch.object(sc, "gather_context", return_value=ctx), \
            mock.patch.object(bc, "summary", return_value={"idea": "x"}) as summ:
        out = sc.get_design_spec("b1", _session())
    assert out["spec"] == SPEC
    assert out["card"] == {"idea": "x"}
    assert "readiness" in out
    assert summ.call_args.kwargs["plan_sections"] == 0


def test_no_context_means_no_card_and_no_readiness_lines():
    """Lines read from an empty context would say they have nothing."""
    import site_composer as sc
    import spec_author
    with mock.patch.object(sc, "_require_owner"), \
            mock.patch.object(spec_author, "get_spec", return_value=SPEC), \
            mock.patch.object(sc, "gather_context", side_effect=RuntimeError("down")):
        out = sc.get_design_spec("b1", _session())
    assert out == {"spec": SPEC, "readiness": None, "card": None}
