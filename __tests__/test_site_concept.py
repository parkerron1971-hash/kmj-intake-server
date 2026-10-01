"""The concept layer (2026-10-01, the concept-layer plan, step 4).

Kevin's rulings, pinned: Plain for health, legal, finance and therapy;
Signature for everyone else; World only when the owner picks it, on one
offer page by default; the owner's pick wins; every in-world label keeps
its plain word."""
import pytest

import site_concept as sc


def _ctx(btype="Barbershop", taste=None):
    return {"business": {"type": btype},
            "site": {"site_config": {"discovery_dossier": {"taste": taste or {}}}}}


# ─── the dial's defaults ─────────────────────────────────────────────

@pytest.mark.parametrize("btype", ["Therapist", "Licensed counselor", "Family law attorney",
                                   "CPA & bookkeeping", "Insurance agency", "Dental clinic",
                                   "Chiropractor", "Financial advisor", "Tax preparation"])
def test_trust_trades_default_to_plain(btype):
    assert sc.default_intensity(btype) == "plain"


@pytest.mark.parametrize("btype", ["Barbershop", "Bakery", "Life coach", "Wedding photographer",
                                   "Pottery studio", "Ministry", "Fitness gym", ""])
def test_everyone_else_defaults_to_signature(btype):
    assert sc.default_intensity(btype) == "signature"


def test_world_is_never_a_default():
    for btype in ("Course creator", "Event planner", "Restaurant", "Retreat center"):
        assert sc.default_intensity(btype) != "world"


# ─── the owner's pick wins ───────────────────────────────────────────

def test_the_coach_cards_set_intensity_and_scope():
    pick = sc.owner_pick({"taste": {"concept": {"value": "world-offer", "source": "asked"},
                                    "concept_idea": {"value": "the course is a semester", "source": "asked"},
                                    "concept_offer": {"value": "Scholar by Design", "source": "asked"}}})
    assert pick["intensity"] == "world" and pick["scope"] == "offer"
    assert pick["idea"] == "the course is a semester" and pick["offer"] == "Scholar by Design"
    assert sc.owner_pick({"taste": {"concept": "world-site"}})["scope"] == "site"
    assert sc.owner_pick({"taste": {"concept": "maximal"}}) is None
    assert sc.owner_pick({}) is None and sc.owner_pick(None) is None


def test_resolve_puts_the_owner_before_the_trade():
    therapist_world = _ctx("Therapist", {"concept": {"value": "world-site", "source": "asked"}})
    got = sc.resolve(therapist_world)
    assert got["intensity"] == "world" and got["by"] == "owner"
    got = sc.resolve(_ctx("Therapist"))
    assert got["intensity"] == "plain" and got["by"] == "default" and got["scope"] == "site"


def test_attach_and_the_off_switch(monkeypatch):
    ctx = _ctx("Bakery")
    assert sc.attach(ctx)["intensity"] == "signature" and ctx["concept"]["by"] == "default"
    monkeypatch.setenv("SITE_CONCEPT", "off")
    ctx = _ctx("Bakery", {"concept": "world-site"})
    assert sc.attach(ctx)["intensity"] == "plain"


def test_the_brief_block_says_who_chose_and_where_world_lives():
    block = sc.brief_block({"intensity": "world", "scope": "offer", "idea": "a semester",
                            "offer": "Scholar by Design", "by": "owner"})
    assert "intensity: world" in block and "owner chose" in block
    assert "ONE OFFER PAGE" in block and "Scholar by Design" in block and "a semester" in block
    plain = sc.brief_block({"intensity": "plain", "scope": "site", "by": "default"})
    assert "trade's default" in plain and "scope" not in plain
    assert sc.brief_block(None) == ""


def test_the_director_law_teaches_the_sheet_and_the_plain_word_rule():
    law = sc.DIRECTOR_LAW
    for must in ("PLAIN", "SIGNATURE", "WORLD", "PLAIN-WORD RULE", "GENEROSITY RULE",
                 "INTENSITY:", "VOCABULARY:", "OBJECTS:", "PHOTO LIST:", "{OBJECT_CATALOG}"):
        assert must in law, must


# ─── the sheet ───────────────────────────────────────────────────────

SHEET = """=====
0. THE CONCEPT
INTENSITY: World
SCOPE: site
IDEA: The shop is a take-a-number counter.
GROUNDED IN: walk-ins welcome, two chairs, prices on the wall
VOCABULARY: Book -> Take a number | Prices -> The board | Barbers -> The chairs
OBJECTS: ticket (paper), letterboard (paper)
LIVING DETAIL: the now-serving number ticks up once
PHOTO LIST: both chairs from the door; a fade from behind the chair
=====
1. OVERVIEW
Objects: this line is section 1 copy, not the sheet.
"""


def test_parse_sheet_reads_section_zero_only():
    s = sc.parse_sheet(SHEET)
    assert s["intensity"] == "world" and s["scope"] == "site"
    assert s["idea"] == "The shop is a take-a-number counter."
    assert s["objects"] == "ticket (paper), letterboard (paper)"
    assert "photo_list" in s and "living_detail" in s
    assert sc.parse_sheet("1. OVERVIEW\nA page.")["intensity"] == ""
    assert sc.parse_sheet("INTENSITY: signature\nSCOPE: offer page for the course")["scope"] == "offer"


def test_vocabulary_pairs():
    pairs = sc.vocabulary_pairs(sc.parse_sheet(SHEET))
    assert pairs == [("Book", "Take a number"), ("Prices", "The board"), ("Barbers", "The chairs")]
    assert sc.vocabulary_pairs({"vocabulary": "Tuition → Tuition"}) == []


# ─── the page held to its sheet ──────────────────────────────────────

def _nav(*links):
    return "<nav>" + "".join(links) + "</nav>"


def test_a_plain_page_carries_no_concept_props():
    page = '<div class="sxo sxo-ticket" data-sx-object="ticket"></div>'
    found = sc.check_page(page, {"intensity": "plain", "scope": "site"})
    assert found and "PLAIN" in found[0]
    ok = '<section class="sxo sxo-edge" data-sx-object="edge"></section>'
    assert sc.check_page(ok, {"intensity": "plain", "scope": "site"}) == []


def test_named_objects_must_be_on_the_page():
    sheet = sc.parse_sheet(SHEET)
    page = _nav('<a href="#b">Take a number<small>Book</small></a>') + \
        '<article data-sx-object="ticket"></article>'
    found = " ".join(sc.check_page(page, sheet))
    assert "letterboard" in found
    assert "at least two" in found


def test_in_world_menu_labels_keep_their_plain_word():
    sheet = sc.parse_sheet(SHEET)
    objs = '<article data-sx-object="ticket"></article><div data-sx-object="letterboard"></div>'
    bad = _nav('<a href="#b">Take a number</a>', '<a href="#p">The board</a>') + objs
    found = " ".join(sc.check_page(bad, sheet))
    assert "'Take a number' (keep 'Book')" in found and "'The board' (keep 'Prices')" in found
    good = _nav('<a href="#b">Take a number <small>Book</small></a>',
                '<a href="#p" aria-label="The board: prices">The board</a>') + objs
    assert sc.check_page(good, sheet) == []


def test_an_offer_scoped_home_is_not_held_to_world_objects():
    sheet = dict(sc.parse_sheet(SHEET), scope="offer")
    page = _nav('<a href="#b">Book</a>')
    assert sc.check_page(page, sheet) == []


def test_no_sheet_no_findings():
    assert sc.check_page("<p>x</p>", {}) == []
    assert sc.check_page("<p>x</p>", {"intensity": ""}) == []


# ─── THE SAMENESS GUARD (2026-10-01) ─────────────────────────────────

def _rows():
    world = ("0. THE CONCEPT\nINTENSITY: world\nIDEA: The shop is a take-a-number counter.\n"
             "OBJECTS: ticket (paper), letterboard (paper)\n1. OVERVIEW\nx")
    plain = "0. THE CONCEPT\nINTENSITY: plain\n1. OVERVIEW\nx"
    mine = "0. THE CONCEPT\nINTENSITY: world\nIDEA: My own idea.\n1. OVERVIEW\nx"
    return [{"business_id": "other-1", "spec": world}, {"business_id": "other-2", "spec": plain},
            {"business_id": "me", "spec": mine}, {"business_id": "other-3", "spec": None}]


def test_recent_concepts_read_other_businesses_ideas(monkeypatch):
    import sb_clients
    seen = {}
    monkeypatch.setattr(sc, "_recent_cache", {"at": 0.0, "rows": []})
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path: seen.setdefault("path", path) and _rows())
    got = sc.recent_concepts("me")
    assert got == [{"intensity": "world", "idea": "The shop is a take-a-number counter.",
                    "objects": "ticket (paper), letterboard (paper)"}]
    assert "spec:site_config->design_spec->>text" in seen["path"], "the spec text alone, never the pages"
    block = sc.recent_block(got)
    assert "never repeat an idea" in block and "take-a-number counter" in block
    assert sc.recent_block([]) == ""


def test_recent_concepts_are_cached(monkeypatch):
    import sb_clients
    calls = []
    monkeypatch.setattr(sc, "_recent_cache", {"at": 0.0, "rows": []})
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: calls.append(path) or _rows())
    sc.recent_concepts("me")
    sc.recent_concepts("me")
    assert len(calls) == 1


def test_the_director_sees_recent_concepts_when_the_site_wears_one(monkeypatch):
    import spec_author
    seen = {}
    monkeypatch.setattr(spec_author, "_call_llm",
                        lambda system, user, bid, image_urls=None, mark_urls=None:
                        seen.setdefault("user", user) and "0. THE CONCEPT\nINTENSITY: signature")
    monkeypatch.setattr(sc, "recent_concepts", lambda bid, limit=12: [
        {"intensity": "world", "idea": "The course is a semester.", "objects": "schedule-card"}])
    ctx = {"business": {"name": "Wheelhouse", "type": "Pottery studio"}, "site": {"site_config": {}}}
    spec_author.author_spec("biz-1", ctx, None, [])
    assert "RECENT CONCEPTS ON THE PLATFORM" in seen["user"] and "The course is a semester." in seen["user"]
    seen.clear()
    plain = {"business": {"name": "Calm", "type": "Licensed therapist"}, "site": {"site_config": {}}}
    spec_author.author_spec("biz-2", plain, None, [])
    assert "RECENT CONCEPTS" not in seen["user"], "a plain site wears no concept to repeat"
