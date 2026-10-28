"""A church's words on the server match its menu (FE #1375, 2026-10-27).

Chief reads vertical_terminology to word its replies. The app's church
list maps client, lead, prospect and offering; without the same rows
here Chief still told a pastor about "clients" and "leads".
"""
import vertical_terminology as vt


def test_church_people_are_members_and_guests():
    t = vt.terms_for("ministry")
    assert (t["client"], t["clients"]) == ("Member", "Members")
    assert (t["lead"], t["leads"]) == ("Guest", "Guests")
    assert (t["prospect"], t["prospects"]) == ("Guest", "Guests")


def test_church_catalog_is_its_store():
    t = vt.terms_for("ministry")
    assert (t["offering"], t["offerings"]) == ("Item", "Store")


def test_other_businesses_keep_their_words():
    # terms_for holds a vertical's overrides; the rest fall back to BASE.
    for v in ("barber", "consultant", "coach", "nonprofit"):
        t = vt.terms_for(v)
        assert t.get("client", "Client") == "Client", v
        assert t.get("lead", "Lead") == "Lead", v
