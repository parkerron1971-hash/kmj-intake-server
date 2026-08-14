"""
test_chief_plan_content.py — handle_plan_content tells the truth about
what it saved.

Two failures this file exists to stop, both seen in live data:

  1. SUCCESS OVER A LOST WRITE. `_sb` does not raise when PostgREST
     rejects a write — sb_clients._async_request logs the status and
     returns None. The handler's try/except around the PATCH could
     therefore never fire, so a refused save still reported
     "📱 Planned linkedin post ..." to the practitioner as done. The
     handler must look at the row, not at the absence of an exception.

  2. DUPLICATE POSTS. Planning the same post twice appended a twin.
     Kevin's calendar carried two "The Power of Pausing Before You
     Respond" on LinkedIn for 2026-05-27, from two turns seven minutes
     apart. Same title + platform + date is the same post — and the
     second pass is usually the one carrying the drafted body, so the
     merge must keep the draft rather than skip or blank it.

Plus the house contract: result + label on every path, failures via
"failed": True.
"""
import asyncio

import chief_of_staff as cos


def _biz():
    return {"id": "biz-1", "owner_id": "user-1", "name": "Test Biz",
            "type": "coach", "settings": {}}


class _FakeDB:
    """Stands in for PostgREST. `write_ok=False` reproduces a rejected
    write the only way _sb reports one: by returning None."""

    def __init__(self, settings=None, write_ok=True):
        self.settings = settings if settings is not None else {}
        self.write_ok = write_ok
        self.patches = 0

    async def sb(self, client, method, path, body=None):
        if method == "GET":
            return [{"id": "biz-1", "settings": self.settings}]
        if method == "PATCH":
            self.patches += 1
            if not self.write_ok:
                return None
            self.settings = body["settings"]
            return [{"id": "biz-1", "settings": self.settings}]
        return None


def _install(monkeypatch, db):
    monkeypatch.setattr(cos, "_sb", db.sb)


def _plan(action):
    return asyncio.run(cos.handle_plan_content(None, _biz(), action))


def _planned(db):
    return (db.settings.get("content_calendar") or {}).get("planned_posts") or []


_POST = {
    "type": "plan_content",
    "title": "Why AI Can't Replace What Actually Changes a Business",
    "platform": "linkedin",
    "scheduled_date": "2026-08-17",
    "status": "draft",
}


# ─────────────────────────────────────────────────────────────────────
# 1. A rejected write is never reported as a save
# ─────────────────────────────────────────────────────────────────────

def test_a_rejected_write_is_reported_as_a_failure(monkeypatch):
    db = _FakeDB(write_ok=False)
    _install(monkeypatch, db)
    r = _plan(dict(_POST))
    assert db.patches == 1, "the handler must actually attempt the write"
    assert cos._action_failed(r), (
        "PostgREST refused the write and _sb returned None — reporting "
        "'Planned linkedin post' here is the bug this test exists for"
    )
    assert r.get("label"), "the house contract: every path carries a label"


def test_a_write_that_lands_is_reported_as_a_save(monkeypatch):
    db = _FakeDB()
    _install(monkeypatch, db)
    r = _plan(dict(_POST))
    assert not cos._action_failed(r)
    assert r.get("result") and r.get("label")
    assert "2026-08-17" in r["label"]
    posts = _planned(db)
    assert len(posts) == 1
    assert posts[0]["title"] == _POST["title"]
    assert posts[0]["id"] == r["post_id"], "post_id must name the row written"


def test_the_refetch_event_rides_along_so_the_page_updates(monkeypatch):
    # The write landing is only half of it — the UI has to be told. The
    # listener for this event lives on BusinessProvider (frontend).
    db = _FakeDB()
    _install(monkeypatch, db)
    r = _plan(dict(_POST))
    assert r["frontend_event"]["name"] == "solutionist-business-refetch"
    assert r["frontend_event"]["detail"]["post_id"] == r["post_id"]


# ─────────────────────────────────────────────────────────────────────
# 2. The same post planned twice does not become two posts
# ─────────────────────────────────────────────────────────────────────

def test_planning_the_same_post_twice_does_not_duplicate_it(monkeypatch):
    db = _FakeDB()
    _install(monkeypatch, db)
    first = _plan(dict(_POST))
    second = _plan(dict(_POST))
    assert len(_planned(db)) == 1, (
        "a replayed turn appended a twin — Kevin's calendar carried two "
        "of five posts this way"
    )
    assert second["post_id"] == first["post_id"], "it must be the same row"
    assert not cos._action_failed(second)


def test_the_second_pass_supplies_the_draft_body(monkeypatch):
    # "Plan it" then "now write it" — the merge must keep the draft.
    db = _FakeDB()
    _install(monkeypatch, db)
    _plan(dict(_POST))
    body = ("Everyone's talking about AI taking over consulting. " * 4).strip()
    r = _plan({**_POST, "body": body})
    posts = _planned(db)
    assert len(posts) == 1
    assert posts[0]["body"] == body
    assert "Updated" in r["label"], "the label should not claim a new post"


def test_a_replan_without_a_body_does_not_blank_the_draft(monkeypatch):
    db = _FakeDB()
    _install(monkeypatch, db)
    body = ("The pause is where wisdom lives. " * 4).strip()
    _plan({**_POST, "body": body})
    _plan(dict(_POST))          # same post, no body this time
    posts = _planned(db)
    assert len(posts) == 1
    assert posts[0]["body"] == body, "the existing draft must survive"


def test_a_different_date_or_platform_is_a_different_post(monkeypatch):
    db = _FakeDB()
    _install(monkeypatch, db)
    _plan(dict(_POST))
    _plan({**_POST, "scheduled_date": "2026-08-18"})
    _plan({**_POST, "platform": "facebook"})
    assert len(_planned(db)) == 3, (
        "dedupe keys on title+platform+date — same title on another day "
        "or another network is a real second post"
    )


def test_existing_posts_are_left_alone(monkeypatch):
    db = _FakeDB(settings={"content_calendar": {"planned_posts": [
        {"id": "post-old", "title": "The Difference Between Rest and Quitting",
         "platform": "linkedin", "scheduled_date": "2026-05-30",
         "status": "draft"},
    ], "pillars": [{"id": "pillar-1", "name": "Spiritual Inspiration"}]}})
    _install(monkeypatch, db)
    _plan(dict(_POST))
    posts = _planned(db)
    assert len(posts) == 2
    assert any(p["id"] == "post-old" for p in posts)
    # The wholesale-replace hazard: sibling keys must survive the write.
    assert db.settings["content_calendar"]["pillars"][0]["id"] == "pillar-1"


# ─────────────────────────────────────────────────────────────────────
# 3. Validation still holds
# ─────────────────────────────────────────────────────────────────────

def test_a_missing_title_is_refused_without_writing(monkeypatch):
    db = _FakeDB()
    _install(monkeypatch, db)
    r = _plan({"type": "plan_content", "platform": "linkedin"})
    assert cos._action_failed(r)
    assert r.get("label")
    assert db.patches == 0, "a rejected action must not write"


def test_a_pillar_named_in_words_resolves_to_its_id(monkeypatch):
    db = _FakeDB(settings={"content_calendar": {"pillars": [
        {"id": "pillar-1779559488287", "name": "Spiritual Inspiration"},
    ]}})
    _install(monkeypatch, db)
    r = _plan({**_POST, "pillar_name": "spiritual"})
    assert _planned(db)[0]["pillar_id"] == "pillar-1779559488287"
    assert "Spiritual Inspiration" in r["label"]
