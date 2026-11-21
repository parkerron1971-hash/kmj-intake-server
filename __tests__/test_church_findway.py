"""Chief knows where everything is on a church's menu (church_findway).

Kevin, 2026-11-16: "major navigation issues such as where everything is."
A pastor paying a deacon back for paint was told about invoices, because
Chief's directions listed the business rooms. These tests pin that the
church's menu reaches the prompt, that a "where" or a "how" is handed the
Help Center's own answer, that a login kept to a lane is never pointed at
a page it does not have, and that the copy of the map still fits the app's
page list.
"""
from collections import defaultdict

import pytest

import chief_of_staff as chief
import church_findway as way
import system_destinations

CHURCH = {"id": "c1", "type": "church", "name": "Grace Fellowship"}
COACH = {"id": "b1", "type": "coach", "name": "KMJ"}
PEOPLE_LANE = {"areas": ["people_care"], "role": "manager", "lane": "people_care"}


# ─── The copy of the map ──────────────────────────────────────────────

def test_the_map_has_the_eleven_doors_in_the_menus_order():
    assert [d["id"] for d in way._map()["doors"]] == [
        "home", "sunday", "people", "giving", "messages", "office", "media", "reach", "web", "settings", "help"]


def test_every_page_on_the_map_is_a_page_chief_can_open():
    routes = system_destinations.CONTRACT["routes"]
    for page in way.pages():
        if page["sub"] in ("@roster", "overview"):       # a module's own id; a room's first page
            continue
        assert page["sub"] in routes[page["tab"]], f"{page['key']} is on the map but not on the server's page list"


def test_every_page_has_a_name_a_sentence_and_a_place():
    for page in way.pages():
        assert page["name"] and page["what"], page["key"]
        assert page["where"].startswith(page["door"]), page["key"]
    ids = [a["id"] for p in way.pages() for a in p["answers"]]
    assert len(ids) == len(set(ids)) and len(ids) > 200


def test_pages_the_marketing_desk_replaced_are_not_listed():
    keys = {p["key"] for p in way.pages()}
    assert not keys & way.NOT_ON_THE_MENU
    assert "Posts (grow/content)" not in way._menu_text()


# ─── The menu in the prompt ───────────────────────────────────────────

def test_a_church_gets_its_menu_and_a_business_does_not():
    menu = way.menu_block(CHURCH)
    assert menu.startswith("THIS CHURCH'S MENU")
    assert "Money out: Check requests (operate/checks) [money]" in menu
    assert "Home (home)" in menu and "Help Center (operate/help-center)" in menu
    assert "Members (operate/contacts) [people]" in menu
    assert way.menu_block(COACH) == ""
    assert way.menu_block(None) == ""


def test_the_menu_is_the_same_for_every_login_so_it_caches():
    assert way.menu_block(CHURCH) is way.menu_block({"id": "c2", "type": "ministry"})


def test_the_menu_sits_in_the_per_business_part_of_the_prompt():
    ctx = defaultdict(list, {"business": {**CHURCH, "settings": {}}})
    prompt = chief._build_system_prompt(ctx, False)
    assert "THIS CHURCH'S MENU" in prompt
    stable, _, tail = prompt.partition("[[CHIEF_CACHE_SPLIT]]")
    assert "THIS CHURCH'S MENU" in stable.partition("[[CHIEF_GLOBAL_SPLIT]]")[2]
    assert "THIS CHURCH'S MENU" not in tail
    other = chief._build_system_prompt(defaultdict(list, {"business": {**COACH, "settings": {}}}), False)
    assert "THIS CHURCH'S MENU" not in other


def test_the_switch_turns_it_off(monkeypatch):
    monkeypatch.setenv("CHIEF_FINDWAY", "off")
    assert way.menu_block(CHURCH) == ""
    assert way.turn_block(CHURCH, "how do I pay someone back") == ""


# ─── What Chief says it opened ────────────────────────────────────────

def test_a_church_page_is_opened_by_the_menus_name_for_it():
    import asyncio
    out = asyncio.run(chief.handle_navigate(None, CHURCH, {"type": "navigate", "tab": "operate", "sub": "checks"}))
    assert out["result"] == "opened" and out["nav"] == {"tab": "operate", "sub": "checks"}
    assert out["label"] == "Opened Office › Money out › Check requests"
    home = asyncio.run(chief.handle_navigate(None, CHURCH, {"type": "navigate", "tab": "home"}))
    assert home["label"] == "Opened Home"
    web = asyncio.run(chief.handle_navigate(None, CHURCH, {"type": "navigate", "tab": "build", "page": "member-app"}))
    assert web["label"] == "Opened Web › Member app › Member app"


def test_a_business_keeps_the_label_it_had():
    import asyncio
    out = asyncio.run(chief.handle_navigate(None, COACH, {"type": "navigate", "tab": "operate", "sub": "invoices"}))
    assert out["label"] == "Opened OPERATE → invoices"
    assert way.place_of(COACH, "operate", "checks") is None
    assert way.place_of(CHURCH, "operate", "not-on-the-map") is None


def test_the_switch_also_puts_the_old_label_back(monkeypatch):
    import asyncio
    monkeypatch.setenv("CHIEF_FINDWAY", "off")
    out = asyncio.run(chief.handle_navigate(None, CHURCH, {"type": "navigate", "tab": "operate", "sub": "checks"}))
    assert out["label"] == "Opened OPERATE → checks"


# ─── This turn's answers ──────────────────────────────────────────────

def test_paying_a_deacon_back_is_a_check_request():
    block = way.turn_block(CHURCH, "Where do I pay Deacon Ray back for the paint?")
    assert block.startswith("HELP CENTER ANSWERS")
    assert "Pay someone back — Office › Money out › Check requests (open with navigate operate/checks)" in block
    assert "Press Add a request" in block


def test_a_lane_is_never_pointed_at_a_page_it_does_not_have():
    # Check requests are money: the People & care login gets nothing for them…
    assert "Check requests" not in way.turn_block(CHURCH, "Where do I pay Deacon Ray back for the paint?", PEOPLE_LANE)
    # …and still gets the answers for its own pages.
    assert "Add a member or a guest — People › Members" in way.turn_block(CHURCH, "how do I add a new member", PEOPLE_LANE)
    for page in way.pages():
        if page["sees"] == "money":
            assert not way.shown_to(page, PEOPLE_LANE), page["key"]
        assert way.shown_to(page, None), page["key"]


def test_an_answer_that_lives_in_settings_opens_settings():
    block = way.turn_block(CHURCH, "how do i change our plan or see the bill")
    assert "Change our plan or see the bill — Settings › All settings (open with navigate build/settings)" in block


def test_a_login_is_given_on_logins_and_areas_not_in_settings():
    # A church's logins are invited, placed and removed in one place since
    # 2026-11-17: Logins & areas, the Office logins tab.
    block = way.turn_block(CHURCH, "how do i give someone a login")
    assert "Give someone a login — Settings › Logins & areas (open with navigate operate/areas)" in block
    assert "Invite a login" in block
    assert "then Team" not in block


def test_a_page_asked_about_by_name_gets_its_sentence():
    block = way.turn_block(CHURCH, "where can I see who is drifting")
    assert "The page People › New and in need › Who's drifting (grow/retention)" in block


@pytest.mark.parametrize("message", [
    "hello how are you",
    "what did we take in last Sunday",          # a question about the church's numbers, not the menu
    "thanks, can you text the deacons about Friday",
    "show me the kids check in",                # opening a page by name is the menu block's job
    "",
])
def test_a_message_that_is_not_a_where_or_a_how_adds_nothing(message):
    assert way.turn_block(CHURCH, message) == ""


def test_a_business_that_is_not_a_church_gets_nothing():
    assert way.turn_block(COACH, "how do I pay someone back") == ""


# ─── The matcher is the app's (findway/churchMap.ts, tests/church-map-check.ts) ──

ASKED = [
    ("how do i add a new member", "add-a-member-or-a-guest"),
    ("refund", "refund-an-online-gift"),
    ("change our plan", "change-our-plan-or-see-the-bill"),
    ("someone needs a login", "give-someone-a-login"),
    ("text everyone", "send-a-text-to-the-whole-church"),
    ("print a baptism certificate", "print-a-certificate"),
    ("kids check in", "check-a-child-in"),
    ("book the fellowship hall", "book-a-room"),
    ("go live", "go-live-on-sunday"),
    ("add a song", "add-a-song-to-the-library"),
    ("record the offering", "record-sundays-offering"),
    ("send statements", "send-year-end-giving-statements"),
    ("mark a check paid", "mark-a-check-as-paid"),
    ("where is the annual report", "make-the-annual-report"),
    ("pay someone back", "pay-someone-back"),
    ("Where do I pay Deacon Ray back", "pay-someone-back"),
    # An event's volunteers and its flyer (2026-11-21, on for every church).
    ("ask the teams for volunteers for our event", "ask-the-serving-teams-for-volunteers-for-an-event"),
    ("add a flyer to the event", "add-a-flyer-to-an-event"),
    ("event flyer", "add-a-flyer-to-an-event"),
    ("how full is my event", "see-how-full-an-event-is"),
    ("kids role", "mark-an-event-role-as-working-with-kids"),
    ("chaperones", "add-special-volunteers-to-an-event"),
    ("answer an event request", "answer-an-events-request-for-volunteers"),
    ("change the numbers for an event", "change-how-many-an-event-date-needs"),
]


@pytest.mark.parametrize("question,answer", ASKED)
def test_the_same_question_finds_the_same_answer_as_the_app(question, answer):
    found = way.match_answers(question, None, 1)
    assert found and found[0][0]["id"] == answer


@pytest.mark.parametrize("question", ["zzqx", "a", "how do i", "order pizza for the youth"])
def test_nonsense_and_filler_find_nothing(question):
    assert way.match_answers(question) == []


def test_words_are_read_the_way_the_app_reads_them():
    assert way.key_words("How do I pay Deacon Ray back?") == ["pay", "deacon", "ray", "back"]
    assert way.key_words("Sunday’s offering, members and texting") == ["sunday", "offer", "member", "text"]
