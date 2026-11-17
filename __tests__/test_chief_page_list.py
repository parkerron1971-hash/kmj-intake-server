"""Chief can open the pages a church's menu has.

2026-11-16: the app's page list (solutionist-studio
src/core/data/systemDestinations.json) had grown 30 pages this copy never
got, so `navigate` answered "That page is not available" for My week, This
Sunday, Reports, Pledges, the Member directory and the rest, while the
server's own notifications sent people to several of them. This file pins
those pages, and the Money controls page added the same day, so the copy
cannot fall behind them again without a red test.
"""
import asyncio

import pytest

import chief_of_staff as chief
import system_destinations

OPERATE = (
    "areas", "board", "checks", "directory", "giving-page", "help", "help-center", "leaders-note",
    "money-controls", "monthly-report", "my-week", "pledges", "recurring-gifts", "register",
    "rentals", "reports", "serve-order", "serve-schedule", "serve-teams", "serving", "spaces",
    "statements", "stations", "sunday-home", "team", "volunteer-schedule", "volunteer-teams",
    "worship-announcements", "worship-setup",
)
BUILD = (
    "devotionals", "events-page", "reading-plan",
)
PAGES = [("operate", p) for p in OPERATE] + [("build", p) for p in BUILD]


@pytest.mark.parametrize("tab,page", PAGES)
def test_a_church_page_is_a_page_chief_can_open(tab, page):
    assert system_destinations.destination(tab, page) == {"tab": tab, "sub": page}


def test_navigate_opens_money_controls():
    out = asyncio.run(chief.handle_navigate(
        None, {"id": "b"}, {"type": "navigate", "tab": "operate", "sub": "money-controls"}))
    assert out["result"] == "opened"
    assert out["nav"] == {"tab": "operate", "sub": "money-controls"}
    assert out["label"]


def test_the_pages_the_server_itself_sends_people_to_are_on_the_list():
    for page in ("my-week", "areas", "checks", "spaces", "pledges"):
        assert page in system_destinations.CONTRACT["routes"]["operate"], page


def test_a_made_up_page_is_still_refused():
    with pytest.raises(ValueError):
        system_destinations.destination("operate", "not-a-page")
    out = asyncio.run(chief.handle_navigate(
        None, {"id": "b"}, {"type": "navigate", "tab": "operate", "sub": "not-a-page"}))
    assert out.get("failed")
