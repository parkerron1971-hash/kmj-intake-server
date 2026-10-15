"""Samples in the owner's preview of the member app (Kevin, 2026-10-14:
show the layout even before the church has added anything), and "I'd
like to join a group" for a church with no groups yet."""
from datetime import date

import member_app_samples as samples
import member_portal as mp
import member_portal_church as mpc
import member_portal_sermons as mps

ME = {"id": "c1", "name": "Ana Rivers", "email": "ana@example.com"}


def _biz():
    return {"id": "b1", "name": "First Light", "settings": {"brand_kit": {"colors": {"primary": "#0B2146"}}}}


def test_samples_fill_only_the_owners_preview_and_only_what_is_empty():
    assert samples.fill([], "occasions", preview=False) == []
    assert samples.fill(None, "occasions", preview=True) is None              # a failed read stays failed
    real = [{"entry_id": "e1", "title": "Ours"}]
    assert samples.fill(real, "occasions", preview=True) is real               # the church's own wins
    assert all(samples.is_sample(o) for o in samples.fill([], "occasions", preview=True))
    assert samples.fill({"mine": [], "open": []}, "groups", preview=True)["open"]
    assert samples.fill({"mine": [{"id": "g"}], "open": []}, "groups", preview=True)["mine"] == [{"id": "g"}]
    assert samples.fill({"sermons": [], "series": []}, "library", preview=True)["sermons"]


def test_sample_ids_open_like_real_ones():
    ids = [o["entry_id"] for o in samples.occasions()] + [g["id"] for g in samples.groups()["open"]] + \
          [s["id"] for s in samples.library()["sermons"]]
    assert all(mp.UUID_RE.match(i) for i in ids) and len(set(ids)) == len(ids)


def test_home_in_preview_shows_every_block_tagged_with_where_to_add_it():
    occ = samples.occasions(date(2026, 10, 14))
    assert occ[0]["title"] == "Sunday Worship" and occ[0]["date"] == "2026-10-18"
    page = mp.render_home(_biz(), None, me=ME, occasions=occ, groups=samples.groups(), library=samples.library(),
                          give_url="", reading=__import__("member_portal_reading").home_card(samples.plan_today(), set()))
    body = page[page.index("<body>"):]
    assert body.count('class="mb-sample"') >= 4
    for where in ("events", "sermons", "week", "plan"):
        assert samples.WHERE[where].replace("'", "&#x27;") in body


def test_a_members_page_never_carries_the_sample_tag():
    page = mp.render_home(_biz(), None, me=ME, occasions=[], groups={"mine": [], "open": []},
                          library={"sermons": [], "series": []}, give_url="")
    assert "mb-sample" not in page.split("</style>")[-1] and "mb-hint" not in page.split("</style>")[-1]


def test_sample_sermons_and_groups_pages_say_so():
    lib = samples.library()
    page = mps.render_library(_biz(), None, ME, lib)
    assert 'class="mb-sample"' in page and "Post a sermon in Grow, Reach, Sermons" in page
    one = mps.render_sermon(_biz(), None, ME, lib, lib["sermons"][0]["id"])
    assert "A sample message." in one
    from starlette.requests import Request
    req = Request({"type": "http", "query_string": b"", "headers": [], "path": "/my/groups"})
    groups = mpc.render_groups(_biz(), None, req, samples.groups(), who=ME)
    assert "Add groups in Operate, People, Groups" in groups and "Newcomers Class" in groups


def test_a_church_with_no_groups_offers_to_pass_on_interest():
    from starlette.requests import Request
    req = Request({"type": "http", "query_string": b"done=group_interest", "headers": [], "path": "/my/groups"})
    page = mpc.render_groups(_biz(), None, req, {"mine": [], "open": []}, who=ME)
    assert 'action="/my/groups/interest"' in page and "I&#x27;d like to join a group" in page.replace("'", "&#x27;")
    assert "can reach out when one starts" in page


def test_group_interest_lands_in_prayer_and_care_once(monkeypatch):
    rows = []
    monkeypatch.setattr(mpc.sb_clients, "sb_get_as_service",
                        lambda path: [r for r in rows if r["contact_id"] == "c1"] if "group_interest" in path else [])
    monkeypatch.setattr(mpc.sb_clients, "sb_post_as_service", lambda path, body: rows.append(body) or [body])
    assert mpc.save_group_interest("b1", ME) is True
    assert mpc.save_group_interest("b1", ME) is True
    assert len(rows) == 1 and rows[0]["submission"]["kind"] == "group_interest" and rows[0]["status"] == "new"
    monkeypatch.setattr(mpc.sb_clients, "sb_get_as_service", lambda path: None)
    monkeypatch.setattr(mpc.sb_clients, "sb_post_as_service", lambda path, body: None)
    assert mpc.save_group_interest("b1", {"id": "c2", "name": "X"}) is False


def test_the_interest_route_is_mounted_before_the_catch_all():
    import kmj_intake_automation as app_mod
    paths = [getattr(r, "path", "") for r in app_mod.app.routes]
    assert "/my/groups/interest" in paths
    catch = next(i for i, p in enumerate(paths) if "{full_path" in p or p.endswith("{path:path}"))
    assert paths.index("/my/groups/interest") < catch
