"""No live providers, models, actions, or records: listening preparation races."""
import asyncio
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import chief_listening as listening

BIZ = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'
USER = '33333333-3333-4333-8333-333333333333'
SESSION = SimpleNamespace(user=SimpleNamespace(id=USER), token='owner-jwt')


def request(**kw):
    return listening.ListeningRequest(**dict(
        business_id=BIZ, turn_id=str(uuid4()), revision=1,
        text='Do I have appointment availability tomorrow', **kw))


def revised(req, **kw):
    return req.model_copy(update=kw)


class ListeningTests(IsolatedAsyncioTestCase):
    def setUp(self):
        listening._entries.clear()
        listening._started.clear()
        listening._active.clear()

    async def test_authorized_reads_only_and_snapshot_consumed_once(self):
        req = request()
        async def load(client, bid):
            self.assertEqual(bid, BIZ)
            self.assertEqual(listening.sb_clients._user_jwt_ctx.get(), SESSION.token)
            return [{'id': 'offering', 'business_id': BIZ, 'name': 'Consultation'}]
        with patch.object(listening.sb_clients, 'sb_as_user', AsyncMock(
                return_value=[{'id': BIZ, 'owner_id': USER}])) as db, \
             patch.object(listening, '_load_offerings', side_effect=load):
            result = await listening.prepare_listening(req, SESSION)
        self.assertEqual(result['status'], 'prepared')
        self.assertNotIn('offerings', result)
        args = db.call_args.args
        self.assertEqual(args[1], 'GET')
        self.assertEqual(args[2], f'/businesses?id=eq.{BIZ}&owner_id=eq.{USER}&select=id,owner_id&limit=1')
        self.assertEqual(args[3], SESSION.token)
        self.assertIsNone(listening.sb_clients._user_jwt_ctx.get())
        payload = listening.consume(USER, BIZ, str(req.turn_id), 1, req.text + ' at noon?')
        self.assertEqual(payload['business_id'], BIZ)
        self.assertEqual(len(payload['offerings']), 1)
        self.assertIn('captured_at', payload)
        self.assertIsNone(listening.consume(USER, BIZ, str(req.turn_id), 1, req.text))
        with patch.object(listening, '_fetch', AsyncMock()) as fetch:
            self.assertEqual((await listening.prepare_listening(revised(req, revision=2), SESSION))['status'], 'stale')
            fetch.assert_not_called()

    async def test_denied_or_mismatched_owner_never_loads_catalog(self):
        for rows in ([], [{'id': BIZ, 'owner_id': 'other'}], [{'id': OTHER, 'owner_id': USER}]):
            self.setUp()
            with patch.object(listening.sb_clients, 'sb_as_user', AsyncMock(return_value=rows)), \
                 patch.object(listening, '_load_offerings', AsyncMock()) as load:
                with self.assertRaises(HTTPException) as raised:
                    await listening.prepare_listening(request(), SESSION)
                self.assertEqual(raised.exception.status_code, 403)
                load.assert_not_called()
                self.assertEqual(listening._active, set())

    async def test_correction_invalidates_inflight_result_even_when_new_text_ignored(self):
        req = request()
        started, finish = asyncio.Event(), asyncio.Event()
        async def fetch(*_):
            started.set()
            await finish.wait()
            return {'business_id': BIZ, 'offerings': ['old']}
        with patch.object(listening, '_fetch', side_effect=fetch):
            task = asyncio.create_task(listening.prepare_listening(req, SESSION))
            await started.wait()
            result = await listening.prepare_listening(revised(req, revision=2, text='Actually send me a note'), SESSION)
            self.assertEqual(result['status'], 'ignored')
            finish.set()
            self.assertEqual((await task)['status'], 'superseded')
        self.assertIsNone(listening.consume(USER, BIZ, str(req.turn_id), 2, 'Actually send me a note'))

    async def test_cancel_tombstone_rejects_late_higher_revision(self):
        req = request()
        started, finish = asyncio.Event(), asyncio.Event()
        async def fetch(*_):
            started.set()
            await finish.wait()
            return {'offerings': ['old']}
        with patch.object(listening, '_fetch', side_effect=fetch) as mock:
            task = asyncio.create_task(listening.prepare_listening(req, SESSION))
            await started.wait()
            self.assertEqual((await listening.prepare_listening(revised(req, revision=2, cancel=True), SESSION))['status'], 'cancelled')
            self.assertEqual((await listening.prepare_listening(revised(req, revision=3), SESSION))['status'], 'stale')
            finish.set()
            self.assertEqual((await task)['status'], 'superseded')
            self.assertEqual(mock.call_count, 1)
        self.assertIsNone(listening.consume(USER, BIZ, str(req.turn_id), 3, req.text))

    async def test_duplicate_and_older_revision_do_not_refetch(self):
        req = request()
        with patch.object(listening, '_fetch', AsyncMock(return_value={'offerings': []})) as fetch:
            await listening.prepare_listening(req, SESSION)
            for revision in (0, 1):
                result = await listening.prepare_listening(revised(req, revision=revision), SESSION)
                self.assertEqual(result['status'], 'stale')
            self.assertEqual(fetch.call_count, 1)

    async def test_owner_business_turn_and_final_revision_must_match(self):
        req = request()
        with patch.object(listening, '_fetch', AsyncMock(return_value={'offerings': ['catalog']})):
            await listening.prepare_listening(req, SESSION)
        for user, biz, turn in [('other', BIZ, str(req.turn_id)), (USER, OTHER, str(req.turn_id)), (USER, BIZ, str(uuid4()))]:
            self.assertIsNone(listening.consume(user, biz, turn, 1, req.text))
        self.assertIsNone(listening.consume(USER, BIZ, str(req.turn_id), 2, req.text))
        self.assertIsNone(listening.consume(USER, BIZ, str(req.turn_id), 1, req.text))

    async def test_corrected_final_discards_catalog(self):
        req = request()
        with patch.object(listening, '_fetch', AsyncMock(return_value={'offerings': ['catalog']})):
            await listening.prepare_listening(req, SESSION)
        self.assertIsNone(listening.consume(USER, BIZ, str(req.turn_id), 1, 'Cancel that, send me a note'))

    async def test_ready_catalog_survives_extension_inside_throttle_window(self):
        req = request()
        extended = revised(req, revision=2, text=req.text + ' at noon')
        with patch.object(listening, '_fetch', AsyncMock(return_value={'offerings': ['catalog']})) as fetch:
            await listening.prepare_listening(req, SESSION)
            result = await listening.prepare_listening(extended, SESSION)
            self.assertEqual(result['status'], 'prepared')
            self.assertEqual(fetch.call_count, 1)
        self.assertEqual(listening.consume(USER, BIZ, str(req.turn_id), 2, extended.text), {'offerings': ['catalog']})

    async def test_inflight_catalog_completes_into_latest_extending_revision(self):
        req = request()
        extended = revised(req, revision=2, text=req.text + ' at noon')
        started, finish = asyncio.Event(), asyncio.Event()
        async def fetch(*_):
            started.set()
            await finish.wait()
            return {'offerings': ['catalog']}
        with patch.object(listening, '_fetch', side_effect=fetch) as mock:
            task = asyncio.create_task(listening.prepare_listening(req, SESSION))
            await started.wait()
            self.assertEqual((await listening.prepare_listening(extended, SESSION))['status'], 'preparing')
            finish.set()
            await task
            self.assertEqual(mock.call_count, 1)
        self.assertEqual(listening.consume(USER, BIZ, str(req.turn_id), 2, extended.text), {'offerings': ['catalog']})

    async def test_unexpected_database_error_is_optional_and_releases_capacity(self):
        with patch.object(listening, '_fetch', AsyncMock(side_effect=RuntimeError('database unavailable'))):
            self.assertEqual((await listening.prepare_listening(request(), SESSION))['status'], 'unavailable')
        self.assertEqual(listening._active, set())

    async def test_final_before_preparation_completes_prevents_late_cache_restore(self):
        req = request()
        started, finish = asyncio.Event(), asyncio.Event()
        async def fetch(*_):
            started.set()
            await finish.wait()
            return {'offerings': ['catalog']}
        with patch.object(listening, '_fetch', side_effect=fetch):
            task = asyncio.create_task(listening.prepare_listening(req, SESSION))
            await started.wait()
            self.assertIsNone(listening.consume(USER, BIZ, str(req.turn_id), 1, req.text))
            finish.set()
            self.assertEqual((await task)['status'], 'superseded')
        self.assertIsNone(listening.consume(USER, BIZ, str(req.turn_id), 1, req.text))

    async def test_cache_expires_and_is_bounded(self):
        clock = SimpleNamespace(monotonic=lambda: 100.0)
        with patch.object(listening, 'time', clock), patch.object(listening, 'MAX_ENTRIES', 3), \
             patch.object(listening, '_fetch', AsyncMock(return_value={'offerings': []})):
            req = request()
            await listening.prepare_listening(req, SESSION)
            clock.monotonic = lambda: 130.0
            self.assertIsNone(listening.consume(USER, BIZ, str(req.turn_id), 1, req.text))
            for _ in range(5):
                await listening.prepare_listening(revised(request(), text='unrelated'), SESSION)
            self.assertLessEqual(len(listening._entries), 3)

    async def test_per_user_throttle_spans_business_and_turn(self):
        with patch.object(listening, '_fetch', AsyncMock(return_value={'offerings': []})) as fetch:
            await listening.prepare_listening(request(), SESSION)
            result = await listening.prepare_listening(revised(request(), business_id=OTHER), SESSION)
            self.assertEqual(result['status'], 'throttled')
            self.assertEqual(fetch.call_count, 1)

    async def test_active_work_is_bounded_and_request_cancellation_drains(self):
        started, cancelled = asyncio.Event(), asyncio.Event()
        async def fetch(*_):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        with patch.object(listening, '_fetch', side_effect=fetch), patch.object(listening, 'MAX_ACTIVE', 1):
            task = asyncio.create_task(listening.prepare_listening(request(), SESSION))
            await started.wait()
            other_session = SimpleNamespace(user=SimpleNamespace(id='different-user'), token='different-jwt')
            self.assertEqual((await listening.prepare_listening(request(), other_session))['status'], 'throttled')
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(cancelled.is_set())
            self.assertEqual(listening._active, set())

    async def test_deadline_cancels_fetch_without_snapshot(self):
        cancelled = asyncio.Event()
        async def fetch(*_):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        req = request()
        with patch.object(listening, '_fetch', side_effect=fetch), patch.object(listening, 'PREPARE_TIMEOUT_SECONDS', .01):
            self.assertEqual((await listening.prepare_listening(req, SESSION))['status'], 'unavailable')
        self.assertTrue(cancelled.is_set())
        self.assertEqual(listening._active, set())
        self.assertIsNone(listening.consume(USER, BIZ, str(req.turn_id), 1, req.text))


class ListeningRouteTests(TestCase):
    def test_auth_required_and_bounded_request_fields(self):
        app = FastAPI()
        app.include_router(listening.router)
        client = TestClient(app)
        payload = dict(business_id=BIZ, turn_id=str(uuid4()), revision=1, text='appointment')
        self.assertEqual(client.post('/agents/chief/listening', json=payload).status_code, 401)
        app.dependency_overrides[listening.require_user_session] = lambda: SESSION
        for override in ({'text': 'x' * 2001}, {'revision': -1}, {'revision': 1.5},
                         {'turn_id': 'not-a-uuid'}, {'business_id': 'id&owner_id=neq.someone'}):
            self.assertEqual(client.post('/agents/chief/listening', json={**payload, **override}).status_code, 422)
