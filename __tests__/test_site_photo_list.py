"""The photo list (2026-10-01, the concept-layer plan, step 8): what the
page still needs photographed becomes ONE practitioner task, refreshed in
place, never duplicated, and never filed when nothing is missing."""
import sb_clients
import site_photo_list as pl

PAGE = """<body>
<div class="sx-drop" data-sx-slot="hero_portrait">You at the chair, mid-cut, warm light</div>
<div class="sx-drop sx-filled" data-sx-slot="shop_front"><img src="https://x/front.jpg" alt=""></div>
<div class="sx-drop" data-sx-slot="chairs">Both chairs from the door, shop light</div>
<div class="sx-drop" data-sx-slot="dup">You at the chair, mid-cut, warm light</div>
</body>"""


def test_only_empty_slots_are_listed_once():
    shots = pl.shot_list(PAGE)
    assert shots == [("hero_portrait", "You at the chair, mid-cut, warm light"),
                     ("chairs", "Both chairs from the door, shop light")]
    assert pl.shot_list("<p>no slots</p>") == []


def test_the_concept_photo_list_rides_along():
    extra = pl.sheet_shots({"photo_list": "both chairs from the door; a fade from behind the chair | the price board"})
    assert extra == ["both chairs from the door", "a fade from behind the chair", "the price board"]
    body = pl.description(pl.shot_list(PAGE), extra)
    assert "1. You at the chair" in body and "2. Both chairs" in body
    assert "a fade from behind the chair" in body
    assert body.count("both chairs from the door") + body.count("Both chairs from the door") == 1


def test_file_task_creates_then_updates_never_duplicates(monkeypatch):
    calls = {"post": [], "patch": []}
    existing = []

    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: list(existing))
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda path, row, **k: calls["post"].append(row) or [dict(row, id="t1")])
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda path, patch, **k: calls["patch"].append((path, patch)) or [patch])
    assert pl.file_task("biz-1", PAGE) == "created"
    row = calls["post"][0]
    assert row["title"] == pl.TASK_TITLE and row["status"] == "todo"
    assert "You at the chair" in row["description"]

    existing.append({"id": "t1", "description": "old list"})
    assert pl.file_task("biz-1", PAGE) == "updated"
    assert len(calls["post"]) == 1, "never a second task"
    assert calls["patch"][0][0] == "/tasks?id=eq.t1"


def test_nothing_missing_files_nothing(monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no task")))
    assert pl.file_task("biz-1", '<div class="sx-drop sx-filled" data-sx-slot="a"><img></div>') is None


def test_the_composer_files_the_list_from_the_served_page(monkeypatch):
    import site_composer
    seen = {}
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [{"html_content": PAGE}])
    monkeypatch.setattr(pl, "file_task",
                        lambda bid, html, sheet=None: seen.update(bid=bid, html=html, sheet=sheet) or "created")
    ctx = {"design_spec_text": "0. THE CONCEPT\nINTENSITY: signature\n"
                               "PHOTO LIST: the price board on the wall\n1. OVERVIEW\nx"}
    assert site_composer.file_photo_list("biz-1", ctx) == "created"
    assert seen["bid"] == "biz-1" and "sx-drop" in seen["html"]
    assert seen["sheet"]["photo_list"] == "the price board on the wall"


def test_the_builder_teaches_one_photo_treatment():
    import builder_v2
    assert "ONE PHOTO TREATMENT" in builder_v2._SYSTEM
    assert "brand mark is never treated" in builder_v2._SYSTEM
