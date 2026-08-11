"""New-mail alerts — who gets interrupted, and with whose words.

The security test here is the important one. A push notification is the
one surface where attacker-chosen text would appear on a lock screen
under this app's name, and _neutralize_untrusted does not cover it — that
guards the prompt. So the notification body is built ONLY from contact
names the practitioner typed themselves, never from the From header or
the Subject.

Run via:
  python -m __tests__.test_mailbox_alerts
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

import gmail_sync


CONTACTS = [
    {"email": "marcus@client.com", "name": "Marcus Webb"},
    {"email": "sandra@client.com", "name": "Sandra Ellis"},
    {"email": "noname@client.com", "name": ""},
]


def _row(email, **kw):
    row = {
        "business_id": "biz1",
        "from_email": email,
        "from_name": kw.pop("from_name", "Display Name"),
        "subject": kw.pop("subject", "a subject"),
        "metadata": {"source": "mailbox"},
    }
    row.update(kw)
    return row


class _Capture:
    """Stands in for the two write paths so nothing touches the network."""

    def __init__(self, contacts=CONTACTS):
        self.contacts = contacts
        self.notifications = []
        self.pushes = []

    def sb_get(self, path):
        if path.startswith("/contacts"):
            return self.contacts
        return []

    def sb_post(self, path, row, **kw):
        if path == "/chief_notifications":
            self.notifications.append(row)
        return [row]

    def push(self, business_id, *, title, body, nav="home", tag=None):
        self.pushes.append({"business_id": business_id, "title": title,
                            "body": body, "nav": nav, "tag": tag})
        return 1


def _run_alert(stored, cap):
    import push_notifications
    with patch.object(gmail_sync.sb_clients, "sb_get_as_service", cap.sb_get), \
         patch.object(gmail_sync.sb_clients, "sb_post_as_service", cap.sb_post), \
         patch.object(push_notifications, "send_to_business", cap.push):
        return gmail_sync._alert_new_mail("biz1", stored)


class TestWhoIsWorthInterrupting(unittest.TestCase):
    def test_known_contact_triggers_one_alert(self):
        cap = _Capture()
        res = _run_alert([_row("marcus@client.com")], cap)
        self.assertEqual(res["eligible"], 1)
        self.assertTrue(res["notified"])
        self.assertEqual(len(cap.pushes), 1)
        self.assertIn("Marcus Webb", cap.pushes[0]["body"])

    def test_stranger_never_buzzes_anyone(self):
        """A newsletter must not reach the phone. It is stored and shown
        in the Hub; that is the whole bargain."""
        cap = _Capture()
        res = _run_alert([_row("newsletter@bulk.com")], cap)
        self.assertEqual(res["eligible"], 0)
        self.assertFalse(res["notified"])
        self.assertEqual(cap.pushes, [])
        self.assertEqual(cap.notifications, [])

    def test_mixed_batch_counts_only_the_eligible(self):
        cap = _Capture()
        res = _run_alert([_row("marcus@client.com"),
                          _row("spam@bulk.com"),
                          _row("sandra@client.com")], cap)
        self.assertEqual(res["eligible"], 2)
        self.assertEqual(len(cap.pushes), 1, "one bundled push, not one per message")

    def test_no_contacts_means_no_alerts(self):
        cap = _Capture(contacts=[])
        res = _run_alert([_row("anyone@anywhere.com")], cap)
        self.assertEqual(res["eligible"], 0)
        self.assertEqual(cap.pushes, [])

    def test_nothing_stored_is_silent(self):
        cap = _Capture()
        res = _run_alert([], cap)
        self.assertFalse(res["notified"])
        self.assertEqual(cap.pushes, [])


class TestNoSenderControlledText(unittest.TestCase):
    """THE SECURITY TEST. Nothing a sender chose may reach a lock screen."""

    def test_subject_never_appears_in_any_alert(self):
        cap = _Capture()
        _run_alert([_row("marcus@client.com",
                         subject="URGENT: your account is suspended, click here")], cap)
        blob = str(cap.pushes) + str(cap.notifications)
        self.assertNotIn("suspended", blob)
        self.assertNotIn("click here", blob)

    def test_from_display_name_never_appears(self):
        """Even for a KNOWN contact the From header is attacker-chosen —
        anyone can set their display name. The name shown is ours."""
        cap = _Capture()
        _run_alert([_row("marcus@client.com",
                         from_name="Solutionist Security <verify now>")], cap)
        blob = str(cap.pushes) + str(cap.notifications)
        self.assertNotIn("verify now", blob)
        self.assertNotIn("Solutionist Security", blob)
        self.assertIn("Marcus Webb", blob)

    def test_notification_opens_the_email_screen_not_home(self):
        """nav is split on ":" into tab and sub. A bare "email" matches no
        tab and silently lands on home — a notification that opens the
        wrong screen is a dead end wearing a working button's clothes."""
        cap = _Capture()
        _run_alert([_row("marcus@client.com")], cap)
        self.assertEqual(cap.pushes[0]["nav"], "operate:email")

    def test_eligible_contact_without_a_name_falls_back_to_a_count(self):
        """No trusted name available means no name at all — never the
        email address, which is also sender-controlled."""
        cap = _Capture()
        _run_alert([_row("noname@client.com")], cap)
        body = cap.pushes[0]["body"]
        self.assertNotIn("noname@client.com", body)
        self.assertIn("1 new email", body)


class TestPhrasing(unittest.TestCase):
    def test_one_named_sender(self):
        self.assertEqual(gmail_sync._describe(["Marcus Webb"], 1),
                         "Marcus Webb emailed you.")

    def test_two_named_senders(self):
        self.assertEqual(gmail_sync._describe(["Marcus", "Sandra"], 2),
                         "Marcus and Sandra emailed you.")

    def test_one_name_several_messages(self):
        self.assertEqual(gmail_sync._describe(["Marcus"], 3),
                         "Marcus and 2 others emailed you.")

    def test_no_names_at_all(self):
        self.assertEqual(gmail_sync._describe([], 4),
                         "4 new emails from your contacts.")

    def test_singular_count_reads_correctly(self):
        self.assertEqual(gmail_sync._describe([], 1),
                         "1 new email from your contacts.")


class TestFailureIsNonFatal(unittest.TestCase):
    def test_a_broken_push_does_not_lose_the_in_app_notification(self):
        cap = _Capture()
        import push_notifications

        def boom(*a, **kw):
            raise RuntimeError("web push down")

        with patch.object(gmail_sync.sb_clients, "sb_get_as_service", cap.sb_get), \
             patch.object(gmail_sync.sb_clients, "sb_post_as_service", cap.sb_post), \
             patch.object(push_notifications, "send_to_business", boom):
            res = gmail_sync._alert_new_mail("biz1", [_row("marcus@client.com")])
        self.assertTrue(res["notified"], "in-app row should survive a push failure")
        self.assertEqual(res["pushed"], 0)

    def test_a_broken_lookup_never_raises_into_the_sync(self):
        def boom(*a, **kw):
            raise RuntimeError("supabase down")

        with patch.object(gmail_sync.sb_clients, "sb_get_as_service", boom):
            res = gmail_sync._alert_new_mail("biz1", [_row("marcus@client.com")])
        self.assertFalse(res["notified"])




class TestFirstPassIsSilent(unittest.TestCase):
    """Connecting a mailbox pulls seven days of backfill. All of it is new
    to us and none of it is news to them — firing a notification about last
    Tuesday's mail the instant someone finishes the consent screen is the
    worst possible first impression of the feature."""

    def _sync(self, watermark):
        import asyncio
        alerts = []

        async def fake_get(client, token, msg_id):
            return {"id": msg_id, "payload": {"headers": [
                {"name": "From", "value": "<marcus@client.com>"}]}}

        with patch.object(gmail_sync, "_refresh_or_revoke", create=True), \
             patch.object(gmail_sync.google_oauth, "_refresh_access_token",
                          new=_async_return({"access_token": "tok"})), \
             patch.object(gmail_sync, "_list_recent_ids", new=_async_return(["m1"])), \
             patch.object(gmail_sync, "_list_history_ids",
                          new=_async_return((["m1"], True))), \
             patch.object(gmail_sync, "_get_message", new=fake_get), \
             patch.object(gmail_sync, "_current_history_id",
                          new=_async_return("999")), \
             patch.object(gmail_sync, "_store",
                          lambda b, g, m: {"business_id": b,
                                           "from_email": "marcus@client.com",
                                           "metadata": {"source": "mailbox"}}), \
             patch.object(gmail_sync.sb_clients, "sb_patch_as_service",
                          lambda *a, **k: [{}]), \
             patch.object(gmail_sync, "_alert_new_mail",
                          lambda b, rows: alerts.append(rows) or {"eligible": len(rows)}):
            asyncio.run(gmail_sync._sync_one(None, {
                "business_id": "biz1", "google_email": "me@firm.com",
                "refresh_token": "rt", "last_history_id": watermark,
                "status": "connected"}))
        return alerts

    def test_no_watermark_does_not_alert(self):
        self.assertEqual(self._sync(""), [], "first pass must be silent")

    def test_subsequent_pass_does_alert(self):
        self.assertEqual(len(self._sync("12345")), 1)


def _async_return(value):
    async def _fn(*a, **kw):
        return value
    return _fn

if __name__ == "__main__":
    unittest.main(verbosity=2)
