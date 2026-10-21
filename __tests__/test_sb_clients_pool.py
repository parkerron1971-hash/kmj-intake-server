"""sb_clients' sync calls share kept-open connections (2026-10-20).

A member-app tab made 5 to 15 database calls, each opening its own
connection (a fresh TCP + TLS handshake from us-west2 to us-east-2): 0.9 to
1.8 s a tab. These tests hold the shared pool to its promises:

  * every sync call (read, write, delete) goes over the same pool
  * closing the Client wrapped around a call leaves the pool open
  * a read that meets a connection the database just closed goes once more;
    a write never does (it may have landed)
  * a forked worker makes its own pool (sockets never cross processes)

Run via:
  python -m pytest __tests__/test_sb_clients_pool.py
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

import httpx

import sb_clients

ENV = {
    "SUPABASE_URL": "https://test.supabase.co",
    "SUPABASE_ANON": "anon-test",
    "SUPABASE_SERVICE_ROLE_KEY": "service-role-test",
}


def _resp(text="[]", status=200):
    r = MagicMock()
    r.status_code = status
    r.text = text
    return r


class SharedPoolTests(unittest.TestCase):

    def setUp(self):
        sb_clients._POOL = None
        sb_clients._POOL_PID = 0

    def test_every_sync_call_uses_the_same_pool(self):
        with patch("sb_clients.httpx.Client") as client_cls, patch.dict(os.environ, ENV, clear=False):
            client_cls.return_value.__enter__.return_value.request.return_value = _resp()
            sb_clients.sb_get_as_service("/businesses")
            sb_clients.sb_patch_as_service("/businesses?id=eq.b1", {"name": "x"})
            sb_clients.sb_delete_as_service("/businesses?id=eq.b1")
        pools = [c.kwargs["transport"] for c in client_cls.call_args_list]
        self.assertEqual(len(pools), 3)
        self.assertTrue(all(p is pools[0] for p in pools))
        self.assertIsInstance(pools[0], httpx.HTTPTransport)
        self.assertEqual(client_cls.call_args_list[0].kwargs["timeout"], sb_clients.HTTP_TIMEOUT)

    def test_closing_a_client_leaves_the_pool_open(self):
        pool = sb_clients._pool()
        with patch.object(pool._pool, "close") as close, patch.object(pool._pool, "__exit__") as exit_:
            with httpx.Client(transport=pool):
                pass
            httpx.Client(transport=pool).close()
        close.assert_not_called()
        exit_.assert_not_called()
        self.assertIs(sb_clients._pool(), pool)

    def test_a_read_goes_once_more_when_the_connection_was_just_closed(self):
        with patch("sb_clients.httpx.Client") as client_cls, patch.dict(os.environ, ENV, clear=False):
            req = client_cls.return_value.__enter__.return_value.request
            req.side_effect = [httpx.RemoteProtocolError("Server disconnected"), _resp('[{"id":"b1"}]')]
            self.assertEqual(sb_clients.sb_get_as_service("/businesses"), [{"id": "b1"}])
        self.assertEqual(req.call_count, 2)

    def test_a_read_that_fails_twice_is_none(self):
        with patch("sb_clients.httpx.Client") as client_cls, patch.dict(os.environ, ENV, clear=False):
            req = client_cls.return_value.__enter__.return_value.request
            req.side_effect = httpx.RemoteProtocolError("Server disconnected")
            self.assertIsNone(sb_clients.sb_get_as_service("/businesses"))
        self.assertEqual(req.call_count, 2)

    def test_a_write_is_never_sent_twice(self):
        for call in (lambda: sb_clients.sb_patch_as_service("/businesses?id=eq.b1", {"name": "x"}),
                     lambda: sb_clients.sb_post_as_service("/businesses", {"name": "x"})):
            with patch("sb_clients.httpx.Client") as client_cls, patch.dict(os.environ, ENV, clear=False):
                req = client_cls.return_value.__enter__.return_value.request
                req.side_effect = [httpx.RemoteProtocolError("Server disconnected"), _resp()]
                self.assertIsNone(call())
            self.assertEqual(req.call_count, 1)

    def test_other_transport_errors_are_not_retried(self):
        with patch("sb_clients.httpx.Client") as client_cls, patch.dict(os.environ, ENV, clear=False):
            req = client_cls.return_value.__enter__.return_value.request
            req.side_effect = [httpx.ReadTimeout("slow"), _resp()]
            self.assertIsNone(sb_clients.sb_get_as_service("/businesses"))
        self.assertEqual(req.call_count, 1)

    def test_a_forked_worker_makes_its_own_pool(self):
        parent = sb_clients._pool()
        with patch("sb_clients.os.getpid", return_value=os.getpid() + 1):
            child = sb_clients._pool()
            self.assertIs(sb_clients._pool(), child)
        self.assertIsNot(child, parent)


if __name__ == "__main__":
    unittest.main()
