# __tests__/test_member_messaging_rules.py
#
# Who may message whom (member_messaging_rules.py) — Kevin's settled
# rules, 2026-10-02. Every rule here is a safety rule; each test names it.

import pathlib
import sys
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import member_messaging_rules as r

TODAY = date(2026, 10, 2)


def person(pid, born, enabled=True, role="member"):
    return {"id": pid, "birthdate": born, "enabled": enabled, "role": role}


ADULT, ADULT2 = person("a1", "1985-04-01"), person("a2", "1990-07-15")
TEEN, TEEN2 = person("t1", "2011-06-01"), person("t2", "2010-01-20")
PARENT = person("p1", "1980-02-02")
GUARD = {"t1": {"p1"}}


def d(s, rcp, share=True, blocked=frozenset()):
    return r.direct(s, rcp, guardians_of=GUARD, blocked=set(blocked), share_group=share, today=TODAY)


def test_age_and_teen():
    assert r.age("2008-10-02", TODAY) == 18 and r.age("2008-10-03", TODAY) == 17
    assert r.is_teen(TEEN, TODAY) and not r.is_teen(ADULT, TODAY)
    assert r.age(None, TODAY) is None and r.age("not a date", TODAY) is None and r.age("2030-01-01", TODAY) is None


def test_messaging_needs_both_a_birthdate_and_the_churchs_switch():
    assert r.can_message(ADULT, TODAY)
    assert not r.can_message(person("x", None), TODAY) and r.why_not(person("x", None), TODAY) == "no_birthdate"
    assert not r.can_message(person("x", "1980-01-01", enabled=False), TODAY)
    assert r.why_not(person("x", "1980-01-01", enabled=False), TODAY) == "not_enabled"


def test_adults_who_share_a_group_message_directly_others_send_a_request():
    assert d(ADULT, ADULT2, share=True) == (True, "direct")
    assert d(ADULT, ADULT2, share=False) == (True, "request")


def test_no_private_messages_between_a_teen_and_another_adult():
    assert d(ADULT, TEEN) == (False, "teen_adult")
    assert d(TEEN, ADULT) == (False, "teen_adult")
    assert d(ADULT, TEEN, share=False) == (False, "teen_adult")


def test_a_teen_and_their_own_parent_can_message():
    assert d(PARENT, TEEN) == (True, "direct") and d(TEEN, PARENT) == (True, "direct")
    assert d(PARENT, TEEN, share=False) == (True, "direct")
    assert d(PARENT, TEEN2) == (False, "teen_adult")             # not THEIR parent


def test_teens_can_message_other_teens():
    assert d(TEEN, TEEN2, share=True) == (True, "direct")
    assert d(TEEN, TEEN2, share=False) == (True, "request")


def test_someone_who_cant_message_cant_be_reached_and_a_block_is_never_revealed():
    off = person("o1", "1980-01-01", enabled=False)
    assert d(ADULT, off) == (False, "recipient_off")
    assert d(off, ADULT) == (False, "sender_off")
    assert d(ADULT, ADULT2, blocked={("a2", "a1")}) == (False, "recipient_off")   # looks like "can't message"
    assert d(ADULT2, ADULT, blocked={("a2", "a1")}) == (False, "recipient_off")
    assert d(ADULT, ADULT) == (False, "self")


def test_a_group_chat_with_a_teen_needs_two_approved_adult_leaders():
    lead = person("l1", "1975-01-01", role="leader")
    lead2 = person("l2", "1978-01-01", role="leader")
    off_lead = person("l3", "1979-01-01", enabled=False, role="leader")
    assert r.group_chat([ADULT, ADULT2], TODAY) == (True, "")
    assert r.group_chat([lead, TEEN, ADULT], TODAY) == (False, "two_adults")
    assert r.group_chat([lead, off_lead, TEEN], TODAY) == (False, "two_adults")   # must be able to message
    teen_lead = person("l4", "2009-01-01", role="leader")
    assert r.group_chat([lead, teen_lead, TEEN], TODAY) == (False, "two_adults")  # a teen leader isn't an adult
    assert r.group_chat([lead, lead2, TEEN], TODAY) == (True, "")


def test_a_linked_parent_reads_their_teens_chats_while_they_are_a_teen():
    assert r.may_read_as_parent("p1", TEEN, GUARD, TODAY)
    assert not r.may_read_as_parent("a1", TEEN, GUARD, TODAY)
    grown = person("t1", "2008-01-01")
    assert not r.may_read_as_parent("p1", grown, GUARD, TODAY)
