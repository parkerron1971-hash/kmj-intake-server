"""The Welcome Path's shared core: the switch, the doors, a guest's follow-up."""
import guest_path as gp


def test_mode_unset_is_owner(monkeypatch):
    monkeypatch.delenv("GUEST_PATH", raising=False)
    assert gp.mode() == "owner"


def test_mode_reads_the_switch(monkeypatch):
    for value, want in (("on", "on"), ("OFF", "off"), (" owner ", "owner"), ("maybe", "off")):
        monkeypatch.setenv("GUEST_PATH", value)
        assert gp.mode() == want


def test_off_is_off_for_everyone(monkeypatch):
    monkeypatch.setenv("GUEST_PATH", "off")
    assert gp.switched_on("00000000-0000-0000-0000-000000000001") is False


def test_on_is_on_for_everyone(monkeypatch):
    monkeypatch.setenv("GUEST_PATH", "on")
    assert gp.switched_on("00000000-0000-0000-0000-000000000001") is True


def test_owner_is_the_platform_church_only(monkeypatch):
    import member_asks
    monkeypatch.setenv("GUEST_PATH", "owner")
    monkeypatch.setattr(member_asks, "platform_church", lambda b: b == "mine")
    assert gp.switched_on("mine") is True
    assert gp.switched_on("theirs") is False


def test_owner_read_that_fails_is_a_no(monkeypatch):
    import member_asks

    def boom(_b):
        raise RuntimeError("down")
    monkeypatch.setenv("GUEST_PATH", "owner")
    monkeypatch.setattr(member_asks, "platform_church", boom)
    assert gp.switched_on("mine") is False


def test_guest_follow_ups_by_card():
    for key in ("text:new_here", "app:new_here", "checkin:first", "web:connect_card"):
        assert gp.is_guest_follow_up({"card_key": key, "path_kind": "connect"})
    assert gp.is_guest_follow_up({"card_key": "form:abc", "path_kind": "visit"})
    assert gp.is_guest_follow_up({"card_key": "form:abc", "path_kind": "connect"})
    assert not gp.is_guest_follow_up({"card_key": "form:abc", "path_kind": "baptism"})
    assert not gp.is_guest_follow_up({"card_key": "form:abc", "path_kind": "serve"})
    assert not gp.is_guest_follow_up({"card_key": "something"})
    assert not gp.is_guest_follow_up(None)


def test_guest_meta_and_door_words():
    assert gp.guest_meta({"metadata": {"new_here": {"door": "kids"}}}) == {"door": "kids"}
    assert gp.guest_meta({"metadata": {"new_here": "nope"}}) == {}
    assert gp.guest_meta(None) == {}
    assert gp.door_words("kids") == "Kids desk"
    assert gp.door_words("nowhere") == ""
