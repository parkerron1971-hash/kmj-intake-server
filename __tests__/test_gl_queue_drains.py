"""The GL queue drains, against a database that behaves like PostgREST.

From the 2026-06-10 deploy to 2026-10-01 the ledger never posted again, for
any business: 252 queue rows sat unclaimed. The claim filter carried a raw
'+00:00' timestamp. PostgREST reads an unencoded '+' as a space and rejects
the filter (22007), and sb_clients turns that into None rather than raising.
So the claim matched nothing, the fallback never ran, and every drain
reported zero. The old fake accepted the raw '+', which is why its claim
test stayed green. This fake refuses it, exactly as production does.
"""
from __future__ import annotations

import pathlib
import re
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import gl_engine as gl  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402

RAW_PLUS_TS = re.compile(r"\d\d:\d\d(\.\d+)?\+\d\d:\d\d")


class PostgrestLikeSB(FakeSB):
    """Rejects any filter with a raw '+' timestamp the way PostgREST does:
    a 400, which sb_clients hands back as None."""

    def __init__(self):
        super().__init__()
        self.paths: list = []

    def _bad(self, path):
        self.paths.append(path)
        return bool(RAW_PLUS_TS.search(path.split("?", 1)[-1]))

    def get(self, path):
        return None if self._bad(path) else super().get(path)

    def patch(self, path, body):
        return None if self._bad(path) else super().patch(path, body)

    def delete(self, path):
        return None if self._bad(path) else super().delete(path)


@pytest.fixture
def fake(monkeypatch):
    fb = PostgrestLikeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    return fb


def _queue_expense(fb):
    fb.rows("businesses").append({"id": "b1", "owner_id": "o1", "is_active": True, "name": "Biz",
                                  "type": "consultant"})
    fb.rows("business_expenses").append({"id": "e1", "business_id": "b1", "amount": 50,
                                         "category": "operating", "subcategory": None,
                                         "vendor": "V", "date": "2026-06-05"})
    fb.rows("gl_sync_queue").append({"id": "q1", "business_id": "b1",
                                     "source_table": "business_expenses", "source_id": "e1",
                                     "processed_at": None, "claimed_at": None,
                                     "enqueued_at": "2026-06-10T00:00:00Z"})


def test_the_drain_posts_against_a_postgrest_like_database(fake):
    _queue_expense(fake)
    out = gl.process_queue("b1")
    assert out["processed"] == 1
    assert fake.rows("gl_sync_queue")[0].get("processed_at")
    assert any(je.get("source_id") == "e1" for je in fake.rows("journal_entries"))


def test_no_timestamp_reaches_a_url_unencoded(fake):
    _queue_expense(fake)
    gl.process_queue("b1")
    offenders = [p for p in fake.paths if RAW_PLUS_TS.search(p.split("?", 1)[-1])]
    assert offenders == []
    assert any("claimed_at.lt." in p and "%2B" in p for p in fake.paths)


def test_a_failed_claim_falls_back_instead_of_reporting_zero(fake, monkeypatch):
    _queue_expense(fake)
    real_patch = fake.patch

    def claim_fails(path, body):
        if "claimed_by" in body:
            return None          # the claim errors; later PATCHes still work
        return real_patch(path, body)
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", claim_fails)
    out = gl.process_queue("b1")
    assert out["processed"] == 1


def test_url_ts_encodes_the_offset():
    from datetime import datetime, timezone
    assert gl._url_ts(datetime(2026, 10, 1, 21, 0, tzinfo=timezone.utc)) == "2026-10-01T21:00:00%2B00:00"
