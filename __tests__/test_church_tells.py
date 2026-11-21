"""church_tells: the sweep that tells the next person it's their turn."""
from datetime import datetime, timezone

import pytest

import church_tells as ct

NOW = datetime(2026, 11, 22, 18, 0, tzinfo=timezone.utc)
CHURCH = {"id": "biz-1", "name": "Grace Church", "type": "ministry", "owner_id": "owner", "settings": {}}


@pytest.fixture
def world(monkeypatch):
    """Finders, recipients, tells and stamps all faked; returns what happened."""
    seen = {"told": [], "stamped": [], "items": []}

    def finder(church, now):
        return list(seen["items"])

    monkeypatch.setattr(ct, "FINDERS", ("x:y",))
    monkeypatch.setattr(ct, "_finder", lambda spec: finder)
    monkeypatch.setattr(ct, "_tell", lambda church, uid, items, now: seen["told"].append((uid, [i.key for i in items])) or True)

    def stamp(church, keys, now):
        seen["stamped"].append(sorted(keys))
        church.setdefault("settings", {}).setdefault(ct.KEY, {}).update({k: ct._iso(now) for k in keys})
    monkeypatch.setattr(ct, "_stamp", stamp)
    monkeypatch.setattr(ct, "recipients", lambda church, duty: {"deposit": ["treasurer"], "rooms": ["naiya", "jess"],
                                                                  "broken": None}.get(duty, []))
    return seen


def _church():
    return {**CHURCH, "settings": {}}


def test_switch_modes(monkeypatch):
    monkeypatch.delenv(ct.SWITCH, raising=False)
    assert ct.mode() == "owner"
    monkeypatch.setenv(ct.SWITCH, "ON")
    assert ct.mode() == "on"
    monkeypatch.setenv(ct.SWITCH, "maybe")
    assert ct.mode() == "off"


def test_one_item_one_notice_and_stamped(world):
    world["items"] = [ct.Item(key="count:1", title="Sunday's count is closed", line="Match it.", duty="deposit")]
    church = _church()
    stats = {}
    ct.run_church(church, NOW, stats)
    assert world["told"] == [("treasurer", ["count:1"])]
    assert world["stamped"] == [["count:1"]]
    # The next sweep finds it told and says nothing.
    world["told"].clear()
    ct.run_church(church, NOW, {})
    assert world["told"] == []


def test_several_items_one_notice_a_login(world):
    world["items"] = [ct.Item(key="room:1", title="t", line="a", duty="rooms"),
                      ct.Item(key="room:2", title="t", line="b", duty="rooms")]
    ct.run_church(_church(), NOW, {})
    assert sorted(world["told"]) == [("jess", ["room:1", "room:2"]), ("naiya", ["room:1", "room:2"])]


def test_the_doer_is_never_told(world):
    world["items"] = [ct.Item(key="room:3", title="t", line="a", duty="rooms", actor="naiya")]
    ct.run_church(_church(), NOW, {})
    assert world["told"] == [("jess", ["room:3"])]


def test_doer_as_only_holder_is_kept_as_told(world):
    world["items"] = [ct.Item(key="count:9", title="t", line="a", duty="deposit", actor="treasurer")]
    ct.run_church(_church(), NOW, {})
    assert world["told"] == []
    assert world["stamped"] == [["count:9"]]


def test_unreadable_recipients_wait_for_the_next_sweep(world):
    world["items"] = [ct.Item(key="x:1", title="t", line="a", duty="broken")]
    ct.run_church(_church(), NOW, {})
    assert world["told"] == [] and world["stamped"] == []


def test_explicit_logins(world):
    world["items"] = [ct.Item(key="ans:1", title="t", line="a", to=["asker"])]
    ct.run_church(_church(), NOW, {})
    assert world["told"] == [("asker", ["ans:1"])]


def test_a_failed_tell_is_not_stamped(world, monkeypatch):
    monkeypatch.setattr(ct, "_tell", lambda *a: False)
    world["items"] = [ct.Item(key="count:2", title="t", line="a", duty="deposit")]
    stats = {}
    ct.run_church(_church(), NOW, stats)
    assert world["stamped"] == [] and stats["unsent"] == 1


def test_a_finder_that_fails_never_stops_the_sweep(monkeypatch):
    def boom(church, now):
        raise RuntimeError("x")
    monkeypatch.setattr(ct, "FINDERS", ("a:b",))
    monkeypatch.setattr(ct, "_finder", lambda spec: boom)
    stats = {}
    ct.run_church(_church(), NOW, stats)
    assert stats["failed"] == 1


def test_a_missing_finder_module_is_skipped():
    assert ct._finder("church_tells_not_built_yet:fn") is None


def test_words_group_and_cap():
    items = [ct.Item(key=f"k{i}", title="t", line=f"line {i}") for i in range(8)]
    w = ct._words(CHURCH, items)
    assert w["title"].startswith("8 things for you")
    assert "…and 2 more" in w["text"]
    one = ct._words(CHURCH, items[:1])
    assert one["body"] == "line 0" and one["subject"] == "Grace Church: t"


def test_quiet_hours_hold_the_church(monkeypatch):
    monkeypatch.setattr(ct, "churches", lambda: [_church()])
    monkeypatch.setattr(ct, "_quiet", lambda church, now: True)
    ran = []
    monkeypatch.setattr(ct, "run_church", lambda *a: ran.append(1))
    stats = ct.sweep_tick(NOW)
    assert ran == [] and stats["quiet"] == 1


def test_recipients_managers_then_admins_then_owner(monkeypatch):
    import church_duties as cd
    real = ct.recipients.__wrapped__ if hasattr(ct.recipients, "__wrapped__") else ct.recipients
    monkeypatch.setattr(cd, "manager_holders", lambda biz, duty: ["m1"] if duty == "sermons" else [])
    monkeypatch.setattr(cd, "holders_of", lambda biz, duty: ["owner", "a1"] if duty == "pay" else ["owner"])
    assert real(CHURCH, "sermons") == ["m1"]
    assert real(CHURCH, "pay") == ["a1"]
    assert real(CHURCH, "rooms") == ["owner"]

    def fail(biz, duty):
        raise RuntimeError("503")
    monkeypatch.setattr(cd, "manager_holders", fail)
    assert real(CHURCH, "rooms") is None


def test_stamps_drop_old_ones(monkeypatch):
    import business_settings
    old = "2026-09-01T00:00:00+00:00"
    church = {**CHURCH, "settings": {ct.KEY: {"old:1": old, "new:1": ct._iso(NOW)}}}
    wrote = {}
    monkeypatch.setattr(business_settings, "merge", lambda bid, set=None, **k: wrote.update(set) or {ct.KEY: set[ct.KEY]})
    ct._stamp(church, ["new:2"], NOW)
    assert set(wrote[ct.KEY]) == {"new:1", "new:2"}
    assert church["settings"][ct.KEY]["new:2"]


def test_sample_church_never(monkeypatch):
    import sample_church
    monkeypatch.setenv(ct.SWITCH, "on")
    monkeypatch.setattr(sample_church, "skip", lambda b: True)
    assert ct.open_for(CHURCH) is False
