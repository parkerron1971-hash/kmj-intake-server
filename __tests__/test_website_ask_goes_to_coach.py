"""A WEBSITE ASK GETS THE WEBSITE (2026-11-09, talking to Chief as a test shop).

"I need a website, nothing fancy, I just want people to find me and book" got the
booking page published and an address question that went nowhere. Only a second
push reached the Coach. An owner who didn't know to push would have thought that
was the website.
"""
import pathlib

import chief_of_staff  # noqa: F401  (chief_prompt must load through it: they import each other)
import chief_prompt

SOURCE = pathlib.Path(chief_prompt.__file__).read_text(encoding="utf-8")


def test_a_website_ask_is_not_answered_with_something_smaller():
    block = chief_prompt._build_website_block()
    assert "A WEBSITE ASK GETS THE WEBSITE" in block
    assert "never publish one as your answer" in block
    assert "Bring in the Design Coach in that same turn" in block


def test_small_words_do_not_shrink_the_ask():
    block = chief_prompt._build_website_block()
    assert '"nothing fancy"' in block
    assert "they do not ask for something smaller" in " ".join(block.split())


def test_the_ask_outranks_the_setup_list():
    assert "This outranks SETUP STATUS" in " ".join(chief_prompt._build_website_block().split())


def test_booking_is_offered_and_waits_for_their_yes():
    block = " ".join(chief_prompt._build_website_block().split())
    assert "do it only on their yes" in block
    assert "Only when they ask for the booking page itself or say yes to your offer" in SOURCE


def test_asking_for_the_booking_page_by_name_still_works():
    block = " ".join(chief_prompt._build_website_block().split())
    assert '"put my booking page live"' in block and "so do that one" in block


def test_chief_no_longer_interviews_before_the_coach():
    block = " ".join(chief_prompt._build_website_block().split())
    assert "FACTS FIRST" not in block
    assert "DO NOT INTERVIEW THEM FIRST" in block


def test_chief_hands_over_everything_they_said_about_the_site():
    assert "from every turn of this chat and word for word" in SOURCE
    assert "Never your own descriptions" in SOURCE
