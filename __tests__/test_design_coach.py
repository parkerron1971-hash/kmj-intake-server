"""
test_design_coach.py — the Design Coach (discovery's conversational
door, 2026-07-25).

Pins the turn contract (strict JSON in/out), the save plumbing into
the ONE dossier with provenance 'asked', the known-context injection
(never re-ask), and the new dossier sections riding the practitioner
door + the Director's digest.
"""
import json
from unittest import mock

import design_coach as dc
import discovery


# ─── parse_turn: the strict-JSON contract ────────────────────────────

def _turn(**over):
    base = {"reply": "Tell me about your shop.", "chips": ["It's cozy"],
            "saves": [], "stage": "world", "done": False}
    base.update(over)
    return json.dumps(base)


def test_parse_turn_happy_path_with_fences():
    out = dc.parse_turn("```json\n" + _turn() + "\n```")
    assert out["reply"].startswith("Tell me")
    assert out["stage"] == "world" and out["done"] is False


def test_parse_turn_rejects_junk_and_empty_reply():
    assert dc.parse_turn("not json at all") is None
    assert dc.parse_turn(_turn(reply="")) is None


def test_parse_turn_sanitizes_saves_and_pair():
    raw = _turn(saves=[
        {"section": "story", "field": "voice", "value": "they say wow"},
        {"section": "hacking", "field": "x", "value": "nope"},   # bad section
        {"section": "taste", "field": "", "value": "x"},         # no field
        {"section": "identity", "field": "one_liner", "value": ""},  # empty
    ], pair={"key": "ground", "a": "Dark", "b": "Light"})
    out = dc.parse_turn(raw)
    assert len(out["saves"]) == 1
    assert out["saves"][0]["section"] == "story"
    assert out["pair"]["a"] == "Dark"
    # bad pair dropped
    assert dc.parse_turn(_turn(pair={"key": "x", "a": "only"}))["pair"] is None


def test_parse_turn_bad_stage_defaults_and_reflect_back_capped():
    out = dc.parse_turn(_turn(stage="nonsense",
                              reflect_back=[f"line {i}" for i in range(20)]))
    assert out["stage"] == "world"
    assert len(out["reflect_back"]) == 12


# ─── apply_saves → the ONE dossier, provenance 'asked' ───────────────

def test_apply_saves_merges_into_dossier_with_asked_provenance():
    store = {"d": discovery._empty_dossier()}

    def _answer(business_id, patch):
        store["d"] = discovery.apply_practitioner_patch(store["d"], patch)
        return store["d"]

    with mock.patch.object(discovery, "answer", side_effect=_answer):
        n = dc.apply_saves("b1", [
            {"section": "story", "field": "voice",
             "value": "clients say it feels like home"},
            {"section": "taste", "field": "ground", "value": "dark"},
            {"section": "signature", "field": "moment",
             "value": "the gold thread walking the page"},
            {"section": "truth", "field": "proven_stats",
             "value": [{"label": "years", "value": "15", "proof": "said so"}]},
        ])
    assert n == 4
    d = store["d"]
    assert d["story"]["voice"]["source"] == "asked"
    assert d["taste"]["ground"]["value"] == "dark"
    assert d["signature"]["moment"]["source"] == "asked"
    assert d["truth"]["proven_stats"][0]["value"] == "15"


def test_new_sections_ride_the_practitioner_door_and_digest():
    d = discovery._empty_dossier()
    merged = discovery.apply_practitioner_patch(d, {
        "world": {"room": {"value": "chrome and leather", "source": "asked"}},
        "story": {"origin": {"value": "started in a garage", "source": "asked"}},
        "signature": {"moment": {"value": "the dots", "source": "asked"}},
    })
    assert merged["world"]["room"]["value"] == "chrome and leather"
    digest = discovery.dossier_digest(merged)
    assert "chrome and leather" in digest and "the dots" in digest


def test_recon_never_overwrites_coach_answers():
    d = discovery._empty_dossier()
    d = discovery.apply_practitioner_patch(d, {
        "identity": {"one_liner": {"value": "the owner's words",
                                   "source": "asked"}}})
    merged = discovery.merge_recon(d, {
        "identity": {"one_liner": {"value": "recon guess",
                                   "source": "recon"}}})
    assert merged["identity"]["one_liner"]["value"] == "the owner's words"


# ─── exit-safe progress: the transcript rides the dossier ───────────

def test_session_persist_and_finish_clear():
    store = {"d": discovery._empty_dossier()}
    with mock.patch.object(discovery, "get_dossier",
                           side_effect=lambda b: store["d"]), \
         mock.patch.object(discovery, "save_dossier",
                           side_effect=lambda b, d: store.update(d=d) or True):
        dc._persist_session("b1",
                            [{"role": "assistant", "content": "Welcome!"},
                             {"role": "user", "content": "hey coach"}],
                            {"reply": "Tell me about the shop.",
                             "stage": "world", "chips": ["It's cozy"],
                             "pair": None, "gallery": None,
                             "reflect_back": []})
    sess = store["d"]["session"]
    assert sess["stage"] == "world"
    assert sess["messages"][-1] == {"role": "assistant",
                                    "content": "Tell me about the shop."}
    assert sess["messages"][0]["content"] == "Welcome!"
    assert sess["last"]["chips"] == ["It's cozy"]
    # the transcript never reaches the Director's prompt
    assert "Tell me about the shop" not in discovery.dossier_digest(store["d"])
    # finish clears the resume state (answers stay; thread resets)
    with mock.patch.object(discovery, "get_dossier",
                           side_effect=lambda b: store["d"]), \
         mock.patch.object(discovery, "save_dossier",
                           side_effect=lambda b, d: store.update(d=d) or True), \
         mock.patch.object(discovery, "derive_taste", return_value=None), \
         mock.patch.object(discovery, "answer", return_value={}):
        dc.finish_session("b1")
    assert "session" not in store["d"]


# ─── the prompt: known context rides every turn ──────────────────────

def test_turn_prompt_injects_known_context_first_user_message():
    with mock.patch.object(dc, "_known_context",
                           return_value="BUSINESS: KMJ (consultant)"):
        msgs = dc.build_turn_prompt("b1", [
            {"role": "assistant", "content": "Welcome!"},
            {"role": "user", "content": "hi coach"},
        ])
    assert msgs[0]["role"] == "user"
    joined = " ".join(m["content"] for m in msgs if m["role"] == "user")
    assert "KNOWN CONTEXT" in joined and "BUSINESS: KMJ" in joined
    assert "hi coach" in joined
    # alternation holds for the API
    roles = [m["role"] for m in msgs]
    assert all(a != b for a, b in zip(roles, roles[1:]))


def test_turn_prompt_mirrors_assistant_turns_as_json():
    """The lost-thread bug: prior coach replies fed back as prose made
    the model mirror prose by turn two. Assistant turns must ride the
    transcript in their JSON envelope."""
    with mock.patch.object(dc, "_known_context", return_value="X"):
        msgs = dc.build_turn_prompt("b1", [
            {"role": "assistant", "content": "Welcome to the studio!"},
            {"role": "user", "content": "thanks coach"},
        ])
    assistant = [m for m in msgs if m["role"] == "assistant"]
    assert len(assistant) == 1
    env = json.loads(assistant[0]["content"])
    assert env == {"reply": "Welcome to the studio!"}


def test_parse_turn_sanitizes_gallery():
    good = _turn(gallery={"kind": "looks",
                          "options": ["mural", "monograph", "junk"]})
    out = dc.parse_turn(good)
    assert out["gallery"] == {"kind": "looks",
                              "options": ["mural", "monograph"]}
    # unknown kind or too few valid options → dropped
    assert dc.parse_turn(_turn(gallery={"kind": "vibes",
                                        "options": ["a", "b"]}))["gallery"] is None
    assert dc.parse_turn(_turn(gallery={"kind": "motion",
                                        "options": ["kinetic-hero"]}))["gallery"] is None


def test_prompt_carries_galleries_and_director_carries_motion():
    assert "THE GALLERIES" in dc._SYSTEM
    assert '"kind": "looks"' in dc._SYSTEM
    import spec_author as sa
    assert "THE KINETIC HERO" in sa._SYSTEM
    assert "THE ORBIT" in sa._SYSTEM
    assert "prefers-reduced-motion" in sa._SYSTEM
    # the audited material + modern-motion vocabulary (panels arc)
    assert "THE FOIL" in sa._SYSTEM and "THE EMBOSS" in sa._SYSTEM
    assert "THE TEAR" in sa._SYSTEM and "THE PIN" in sa._SYSTEM
    assert "MICRO-DELIGHT" in sa._SYSTEM


def test_system_prompt_carries_the_standing_rules():
    s = dc._SYSTEM
    assert "ONE question at a time" in s
    assert "NEVER RE-ASK" in s
    assert "dashes" in s            # the dash law reaches the coach too
    assert "screenshots ONE moment" in s
    # THE OPENING (Kevin's study): the coach greets FIRST, by name,
    # and never opens with a menu.
    assert "THE OPENING" in s and "BY NAME" in s
    assert '"how can I help"' in s
    # THE LANE (Kevin: "people must feel the difference"): brand, not
    # business plan — sensory questions only, business facts referenced.
    assert "NOT THE BUSINESS PLAN" in s
    assert "business-plan interview" in s



# ─── THE PHOTO STATION (2026-08-28, build quality 2/6) ───────────────

def test_photo_context_counts_the_inventory_the_build_will_use():
    empty = dc._photo_context({"brand_kit": {}})
    assert empty[0].startswith("PHOTOS ON FILE: 0")
    assert "BRAND MARK: none" in empty[0]
    assert any("NO PHOTOS YET" in line and '"ask": "photos"' in line
               for line in empty)
    full = dc._photo_context({
        "brand_kit": {"logo_url": "https://x/mark.png"},
        "media_library": {"gallery": [
            {"url": "https://x/a.jpg"}, {"url": "https://x/b.jpg"},
            {"url": "https://x/hidden.jpg", "show_on_website": False},
            {"url": ""}, "legacy-string"]}})
    assert full == ["PHOTOS ON FILE: 2 (the build's entire photo inventory) "
                    "— BRAND MARK: on file"]
    assert dc._photo_context(None)[0].startswith("PHOTOS ON FILE: 0")


def test_parse_turn_passes_the_photo_ask_through_and_drops_junk():
    assert dc.parse_turn(_turn(ask="photos"))["ask"] == "photos"
    assert dc.parse_turn(_turn(ask="Photos "))["ask"] == "photos"
    assert dc.parse_turn(_turn(ask="money"))["ask"] is None
    assert dc.parse_turn(_turn())["ask"] is None


# ─── THE CONCEPT CARDS (2026-10-01, the concept-layer plan) ──────────
# Kevin: "I like how you showed me options, so that is how I would want
# it done." The coach shows plain / signature / world as cards, each with
# a one-line pitch for this business, and the tap binds the build.

def test_the_concept_gallery_keeps_its_cards_and_their_pitches():
    out = dc.parse_turn(_turn(gallery={
        "kind": "concept", "options": ["signature", "plain", "world-offer", "neon"],
        "notes": {"signature": "your price list as the board on your wall",
                  "world-offer": "your Saturday shave club as its own page",
                  "neon": "not a concept card"}}))
    assert out["gallery"]["kind"] == "concept"
    assert out["gallery"]["options"] == ["signature", "plain", "world-offer"]
    assert set(out["gallery"]["notes"]) == {"signature", "world-offer"}
    assert "notes" not in dc.parse_turn(_turn(gallery={
        "kind": "concept", "options": ["plain", "signature"]}))["gallery"]


def test_a_tapped_concept_card_saves_its_key():
    for said, key in (("World: one offer page, that's the one.", "world-offer"),
                      ("World: the whole site, that's the one.", "world-site"),
                      ("World", "world-offer"),
                      ("Signature", "signature"), ("Plain", "plain"),
                      ("keep it simple", "plain")):
        out = dc.parse_turn(_turn(saves=[{"section": "taste", "field": "concept",
                                          "value": said}]))
        assert out["saves"] == [{"section": "taste", "field": "concept", "value": key}], said
    junk = dc.parse_turn(_turn(saves=[{"section": "taste", "field": "concept",
                                       "value": "maximalist"}]))
    assert junk["saves"] == []


def test_the_coach_is_taught_the_cards_and_the_rulings():
    s = dc._SYSTEM
    assert 'kind "concept"' in s and "world-offer" in s and "world-site" in s
    assert "CONCEPT DEFAULT" in s and "Never pick for them" in s
    assert "concept_idea" in s and "concept_offer" in s


# ─── the quick session (2026-10-03): Chief opens the coach from the chat ──

def test_session_mode_defaults_to_the_full_sit_down():
    assert dc.session_mode("quick") == "quick"
    assert dc.session_mode(" QUICK ") == "quick"
    for raw in (None, "", "deep", "fast", 3):
        assert dc.session_mode(raw) == "deep"


def test_quick_session_rides_the_lead_only_when_asked():
    with mock.patch.object(dc, "_known_context", return_value="BUSINESS: X"):
        quick = dc.build_turn_prompt("b1", [], mode="quick")
        deep = dc.build_turn_prompt("b1", [])
    assert "QUICK SESSION" in quick[0]["content"]
    assert "QUICK SESSION" not in deep[0]["content"]
    # the contract line still closes the lead, after the quick block
    lead = quick[0]["content"]
    assert lead.index("QUICK SESSION") < lead.index("Run the session")


def test_quick_session_keeps_the_picture_cards_and_the_photo_ask():
    """The quick session still shows the looks and concept cards and still
    asks for photos when there are none: those are the choices that move
    the design most, and the phone is where the photos are."""
    q = dc.QUICK_SESSION
    assert "LOOKS gallery" in q and "CONCEPT gallery" in q
    assert '"ask": "photos"' in q and "NO PHOTOS YET" in q
    assert "bans" in q


def test_run_turn_passes_the_mode_to_the_prompt():
    seen = {}

    def fake_prompt(business_id, messages, mode="deep"):
        seen["mode"] = mode
        raise RuntimeError("stop here")

    with mock.patch.object(dc, "build_turn_prompt", side_effect=fake_prompt), \
            mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "k"}), \
            mock.patch.object(dc.llm_call, "sdk_client", return_value=object()):
        out = dc.run_turn("b1", [], mode="quick")
    assert seen["mode"] == "quick"
    assert "error" in out


# ─── the empty shop (2026-10-03, live test on Vertical Test Coach) ───
# Every business with a site gets a store_url, so the coach told an owner
# with zero products "your store page is already live" and asked twice
# whether to link it. The STORE door is offered only when the public
# store page would show something.

def _context_with(products, booking=False):
    import offering_profiles
    import sb_clients

    def fake_get(path):
        if path.startswith("/products"):
            assert "status=eq.active" in path and "display_on_website=eq.true" in path
            return products
        return []

    state = {"store_url": "https://x.mysolutionist.app/store",
             "booking_enabled": booking,
             "booking_url": "https://x.mysolutionist.app/book" if booking else ""}
    with mock.patch.object(sb_clients, "sb_get_as_service", side_effect=fake_get), \
         mock.patch.object(offering_profiles, "business_state", return_value=state), \
         mock.patch.object(discovery, "get_dossier", return_value=None):
        return dc._known_context("b1")


def test_an_empty_shop_is_not_a_door():
    ctx = _context_with([])
    assert "STORE" not in ctx
    assert "CONNECTED SYSTEMS" not in ctx


def test_a_shop_with_something_in_it_is_a_door():
    ctx = _context_with([{"id": "p1"}])
    assert "STORE page exists at https://x.mysolutionist.app/store" in ctx


def test_booking_still_rides_without_a_store():
    ctx = _context_with([], booking=True)
    assert "BOOKING is LIVE" in ctx
    assert "STORE" not in ctx
