"""The sample church: NOTHING is ever sent (sample_church.py, BE-3, 2026-11-15).

One end-to-end test. A fake database holds a sample church with everything
due at once (overdue follow-ups, a birthday today, a scheduled post, an
unsent devotional, a drifting member, an event tomorrow, a new guest, a
running campaign, a due Chief move, a draft about to expire …) and every
switch on. Then EVERY scheduled job the server runs (kmj_intake_automation's
add_job list, pinned below so a new job must be classified) is run once,
with:
  · Supabase answered from the fake (any host, at the httpx layer, so the
    direct-httpx modules read it too);
  · every provider replaced by a recorder (Twilio, Resend, push, member
    push, every llm_call entry, social posting), and any other network
    connection recorded and refused at the socket.

Then: no provider was called, no network left the building, and no row was
INSERTED for the sample (a sweep may only close its own due row: a
scheduled move marked failed, a chain stopped, an event stamped handled).

The control runs the very same jobs over the very same rows with the
church NOT a sample, and must see sends: otherwise the fixture is too thin
to prove anything and this test says so.
"""
from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import pathlib
import re
import socket
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import httpx  # noqa: E402
import pytest  # noqa: E402

import sample_church as sc  # noqa: E402
from test_i2_gl_sync import FakeSB, _parse  # noqa: E402

ROOT = _here.parent

# Every add_job in kmj_intake_automation.py: job id -> "module:function".
# The classification (covered by is_active / skip added / not business-
# scoped) is in worklog/2026-11-15-sample-church-be3.md.
TICKS = {
    "scheduler_lease_renew": "scheduler_lock:renew_tick",
    "dev_alert_digest_tick": "dev_alerts:dev_alert_digest_tick",
    "dev_relay_purge": "dev_relay:dev_relay_purge",
    "workflow_drain": "workflow_engine:drain_tick",
    "autopilot_sweep": "chief_of_staff:autopilot_sweep_tick",
    "chief_keep_warm": "chief_keep_warm:tick",
    "gl_drain": "gl_engine:drain_tick",
    "stripe_usage_report": "usage_metering:stripe_report_tick",
    "rules_overdue_tick": "rules_engine:overdue_tick",
    "push_morning_brief": "push_notifications:morning_brief_tick",
    "gl_divergence": "gl_engine:divergence_tick",
    "gmail_sync": "gmail_sync:sync_tick",
    "hermes_tick": "hermes_agent:hermes_tick",
    "support_drafts": "support_drafts:drafts_tick",
    "chief_quality": "chief_quality:quality_tick",
    "customer_health": "customer_health:health_tick",
    "unfinished_work": "unfinished_work:watch_tick",
    "scope_keeper": "ops_desk:keeper_tick",
    "money_auditor": "money_auditor:audit_tick",
    "church_texts": "church_texts:bill_tick",
    "msg_retention": "member_portal_messaging:retention_tick",
    "rail_practice_retention": "chief_rail:prune_tick",
    "member_push_sweep": "member_push:sweep_tick",
    "stream_relay_sweep": "stream_relay_router:sweep_stale",
    "trial_expiry": "trial_expiry:expire_tick",
    "email_domain_monitor": "email_domain_monitor:monitor_tick",
    "sms_reminder_sweep": "sms_alerts:reminder_sweep",
    "sms_number_release_sweep": "sms_numbers_router:release_sweep",
    "notif_urgent_check": "notification_engine:check_urgent_for_all",
    "notif_morning_brief": "notification_engine:generate_morning_brief_for_all",
    "notif_setup_brief": "notification_engine:setup_brief_local_morning_tick",
    "notif_midday_ping": "notification_engine:generate_midday_ping_for_all",
    "notif_evening_summary": "notification_engine:generate_evening_summary_for_all",
    "notif_unanswered_leads": "notification_engine:unanswered_lead_sweep",
    "church_follow_up_sweep": "church_follow_up:sweep",
    "church_checkin_sweep": "church_checkin:sweep",
    "church_shepherd_sweep": "church_shepherd_signals:sweep",
    "church_leader_tasks_sweep": "church_leader_tasks:sweep_tick",
    "church_office_tasks_sweep": "church_office_tasks:sweep_tick",
    "church_team_rollup": "church_team_week:rollup_tick",
    "church_assignments_sweep": "church_assignments:sweep_tick",
    "church_handovers_sweep": "church_handovers:sweep_tick",
    "church_mail_alert_sweep": "church_mail_alerts:sweep",
    "church_mail_trash_sweep": "church_mail_alerts:trash_sweep",
    "academy_work_sweep": "academy_work:sweep_tick",
    "group_email_followup": "group_email:sweep_tick",
    "group_post_later": "group_post_later:sweep_tick",
    "group_study_drafts": "group_study:sweep_tick",
    "event_signups_sweep": "church_event_signups:sweep_tick",
    "celebrations_today": "celebrations:sweep_tick",
    "news_alerts": "news_alerts:sweep_tick",
    "news_reach": "news_reach:sweep_tick",
    "ministry_reminders": "worship_ministries:sweep_tick",
    "serving_alerts": "sunday_serving_alerts:sweep_tick",
    "academy_class_reminders": "academy_reminders:sweep_tick",
    "academy_class_nights": "academy_class_nights:sweep_tick",
    "lead_response_reconcile": "lead_response:reconcile_tick",
    "reorder_sweep": "reorder_engine:low_stock_reorder_sweep",
    "chief_insights": "chief_insights:insights_tick",
    "feed2_distill": "vertical_distill:tick",
    "vertical_seed": "vertical_knowledge:seed_tick",
    "vertical_curate": "vertical_playbook:curate_tick",
    "booking_session_sync": "booking_widget_router:booking_session_sync_tick",
    "square_booking_sync": "square_booking_sync:sync_due_tick",
    "calendar_feed_sync": "outside_calendar:sync_due_tick",
    "platform_marketing_due": "platform_marketing:due_tick",
    "platform_marketing_metrics": "platform_marketing_campaigns:metrics_tick",
    "platform_marketing_status": "platform_marketing:reconcile_tick",
    "platform_marketing_engine": "marketing_engine:engine_tick",
    "business_marketing_due": "business_marketing_dispatch:due_tick",
    "business_marketing_delivery": "business_marketing_dispatch:delivery_tick",
    "business_marketing_suggest": "business_marketing_planner:marketing_tick",
    "business_marketing_requests": "business_marketing_planner:manual_tick",
    "business_marketing_designs": "business_marketing_planner:marketing_design_tick",
    "business_marketing_openings_watch": "business_marketing_planner:openings_watch_tick",
    "chief_scheduled": "chief_scheduler:due_tick",
    "media_library": "media_library:tick",
    "clip_finder": "clip_finder:tick",
    "clip_finder_sweep": "clip_finder:sweep_tick",
    "clip_covers": "clip_covers:cover_tick",
    "video_studio": "video_studio_worker:tick",
    "chief_jobs_recover": "chief_jobs:recover_tick",
    "chief_agent": "chief_agent:agent_tick",
    "chief_assignments": "chief_assignments:assignments_tick",
    "chief_cases": "chief_cases:cases_tick",
    "proposal_life": "proposal_life:proposals_tick",
    "outcome_ledger": "outcome_ledger:outcomes_tick",
    "brain_pass": "chief_brain_pass:nightly_tick",
    "chief_week": "chief_week:weekly_tick",
    "standing_release": "standing_permissions:release_tick",
    "rate_windows_purge": "rate_limit:purge_shared",
    "campaigns_tick": "campaigns_router:campaigns_tick",
    "journeys_tick": "outreach_journeys:journeys_tick",
    "referral_tick": "refer_a_friend:rewards_tick",
    "texting_registration_sweep": "texting_registration:sweep_tick",
    "platform_watchdog": "platform_watchdog:watchdog_tick",
    "trusted_proposals": "rules_router:trusted_sweep_tick",
    "balance_sweep": "balance_sweep:sweep_tick",
    "ledger_anchor_sweep": "anchor_scheduler:sweep_tick",
    "ledger_anchor_upgrade": "anchor_scheduler:upgrade_tick",
    "lifecycle_emails": "lifecycle_emails:sweep_tick",
    "welcome_retry": "lifecycle_emails:welcome_retry_tick",
    "signup_reminders": "lifecycle_emails:signup_reminders_tick",
    "week_beats": "lifecycle_emails:week_beats_tick",
    "devotional_daily_texts": "devotional_daily:sweep_tick",
    "devotional_daily_morning": "devotional_daily:morning_tick",
    "sample_church_cleanup": "sample_church:cleanup_tick",
}
# Not run here, with the reason. Neither touches a business.
NOT_RUN = {
    "followup_check": "kmj_intake_automation's in-memory project list (no tenant data)",
}


def test_every_scheduled_job_is_classified():
    src = (ROOT / "kmj_intake_automation.py").read_text(encoding="utf-8")
    start = src.index("scheduler.add_job(scheduler_lock.renew_tick")
    block = src[start:src.index("_staggered = stagger_long_interval_first_runs")]
    calls = block.count("scheduler.add_job(")
    ids = set(re.findall(r"""\bid\s*=\s*['"]([A-Za-z0-9_]+)['"]""", block))
    assert calls == len(ids), "every add_job names its id once"
    missing = ids - set(TICKS) - set(NOT_RUN)
    assert not missing, f"classify these new jobs for the sample church (BE-3): {sorted(missing)}"
    assert not (set(TICKS) | set(NOT_RUN)) - ids, "a pinned job is no longer scheduled"


# ─── The fake world ───────────────────────────────────────────────────

SAMPLE = "5a3b1e00-0000-4000-8000-00000000a001"
HOME = "5a3b1e00-0000-4000-8000-00000000b002"
OWNER = "5a3b1e00-0000-4000-8000-00000000d004"
PEOPLE = [("Ruth", "+13125550101", "ruth@grace.example"),
          ("Boaz", "+13125550102", "boaz@grace.example"),
          ("Naomi", "+13125550103", "naomi@grace.example")]


class World(FakeSB):
    """FakeSB with PATCH returning the rows it changed (claims read it), any
    rpc answered with nothing, and every insert and patch logged."""

    def __init__(self):
        super().__init__()
        self.inserts = []
        self.patches = []

    def post(self, path, body, prefer="rep"):
        table = path.split("?", 1)[0].lstrip("/")
        if table.startswith("rpc/"):
            return []
        out = []
        for row in (body if isinstance(body, list) else [body]):
            self.inserts.append((table, dict(row)))
            out += super().post(path, row, prefer)
        return out

    def patch(self, path, body):
        table, cons = _parse(path)
        hit = self._match(table, cons)
        for r in hit:
            r.update(body)
        self.patches.append((table, [r.get("business_id") or r.get("id") for r in hit], dict(body)))
        return [dict(r) for r in hit]


def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def build(world: World, *, sample: bool) -> None:
    now = datetime.now(timezone.utc)
    today = now.date()
    soon, past = now + timedelta(days=1), now - timedelta(days=3)
    everything_on = {
        sc.SETTINGS_KEY: {"status": "ready", "created_at": _iso(now)},
        "practitioner_name": "Pastor Sam", "timezone": "America/Chicago",
        "autopilot": {"overall": "full", "per_team": {"comms": "full"}},
        "autonomy": {"agent_enabled": True, "client_facing_autonomy": "enabled",
                     "standing": {"send_email": {"granted_at": _iso(past)}}},
        "member_portal": {"enabled": True, "notifications": {
            "sermons": True, "events": True, "groups": True, "messages": True, "news": True,
            "serving": True}},
        "news": {"celebrate": "all"},
        "messaging": {"enabled": True},
        "sms_alerts": {"confirmations": True, "reminders": True},
        "email_domain": {"status": "verified", "domain": "grace.example"},
        "journeys": {"welcome": {"enabled": True}},
        "feed2": {"contribute": True},
        "notifications": {"morning_brief_enabled": True},
        "churchsavvy": {"planning_email": True},
    }
    world.rows("businesses").extend([
        {"id": SAMPLE, "owner_id": OWNER, "name": sc.NAME, "type": "church",
         "is_sample": sample, "sample_of": HOME if sample else None, "is_active": not sample,
         "settings": everything_on, "created_at": _iso(past), "subscription_status": None},
        {"id": HOME, "owner_id": OWNER, "name": "Home", "type": "church", "is_sample": False,
         "sample_of": None, "is_active": True, "settings": {}, "created_at": _iso(past)},
    ])
    b = {"business_id": SAMPLE}
    for i, (name, phone, email) in enumerate(PEOPLE):
        world.rows("contacts").append({**b, "id": f"c{i}", "name": name, "first_name": name,
                                       "phone": phone, "email": email, "status": "member",
                                       "sms_opt_in": True, "created_at": _iso(past),
                                       "birthday": f"1980-{today.month:02d}-{today.day:02d}"})
    t = world.rows
    t("church_follow_ups").append({**b, "id": "f1", "contact_id": "c0", "status": "open",
                                   "leader_contact_id": "c1", "leader_told_at": None, "step": 0,
                                   "due_at": _iso(past), "created_at": _iso(past)})
    t("ministry_care_requests").append({**b, "id": "m1", "leader_contact_id": "c1", "leader_prayed_at": None,
                                        "leader_late_level": 0, "leader_told_at": None, "leader_due_at": _iso(past)})
    t("church_leader_roles").append({**b, "id": "lr1", "contact_id": "c1", "role": "elder", "status": "active",
                                     "term_ends_at": _iso(past), "term_told_at": None})
    t("member_celebrations").append({**b, "contact_id": "c0", "birthday": True})
    t("attendance").append({**b, "id": "a1", "contact_id": "c2", "first_time": True,
                            "checked_in_at": _iso(now - timedelta(hours=1)), "entry_id": "e1"})
    t("group_posts").append({**b, "id": "gp1", "group_id": "g1", "title": "Tonight", "body": "Come",
                             "publish_at": _iso(now - timedelta(minutes=5)), "told_at": None, "removed_at": None,
                             "missed_checked_at": None, "created_at": _iso(now - timedelta(hours=30)),
                             "posted_by": "c1", "pinned": False})
    t("church_posts").append({**b, "id": "cp1", "kind": "news", "title": "Big news", "body": "x",
                              "status": "posted", "important": True, "alerted_at": None, "reached_at": None,
                              "removed_at": None, "created_at": _iso(now - timedelta(minutes=10)),
                              "publish_at": _iso(now - timedelta(minutes=10))})
    t("devotional_texts").append({**b, "id": "dt1", "contact_id": "c0", "phone": PEOPLE[0][1],
                                  "stopped_at": None, "last_sent_on": None})
    t("church_shepherds").append({**b, "contact_id": "c1", "member_id": "c2"})
    t("church_event_registrations").append({**b, "entry_id": "e1", "status": "held",
                                            "hold_expires_at": _iso(past), "contact_id": "c2"})
    t("module_entries").append({**b, "id": "e1", "data": {"title": "Picnic", "starts_at": _iso(soon)}})
    t("sessions").append({**b, "id": "s1", "contact_id": "c0", "status": "scheduled",
                          "scheduled_for": _iso(soon), "created_at": _iso(past)})
    t("chief_scheduled_actions").append({**b, "id": "sa1", "status": "queued", "run_at": _iso(past),
                                         "action": {"type": "send_sms", "to": PEOPLE[0][1], "message": "hi"}})
    t("campaigns").append({**b, "id": "cmp1", "status": "running", "channel": "email",
                           "steps": [{"subject": "Hi", "body": "Hello"}], "audience": {"all": True}})
    t("agent_queue").append({**b, "id": "q1", "channel": "action", "status": "draft", "subject": "Send",
                             "expires_at": _iso(past), "reminded_at": None, "created_at": _iso(past),
                             "scheduled_for": _iso(past), "body": "{}"})
    t("events").append({**b, "id": "ev1", "event_type": "contact_form_submitted", "agent_handled_at": None,
                        "created_at": _iso(now)})
    t("chief_keep_warm").append({**b, "touched_at": _iso(now - timedelta(minutes=30)), "stopped_at": None,
                                 "window_ends_at": _iso(soon), "pings": 0})
    t("workflow_runs").append({**b, "id": "wr1", "status": "pending", "created_at": _iso(past), "steps": []})
    t("marketing_posts").append({**b, "id": "mp1", "status": "approved", "scheduled_for": _iso(past),
                                 "design_status": "designing", "source": "plan"})
    t("sermons").append({**b, "id": "se1", "published": True, "preached_on": today.isoformat(),
                         "title": "Grace", "scripture": "John 1", "summary": "x"})
    t("worship_ministries").append({**b, "id": "wm1", "remind": True, "archived_at": None,
                                    "leader_email": PEOPLE[1][2], "name": "Choir"})
    t("chief_conversations").append({**b, "id": "cv1", "started_at": _iso(now - timedelta(hours=2))})
    t("chief_memories").append({**b, "id": "mem1", "content": "x", "embedding": None, "is_active": True})
    t("church_mail").append({**b, "id": "cm1", "alerted_at": None, "alert_at": _iso(now - timedelta(minutes=1)),
                             "direction": "in"})
    t("tasks").append({**b, "id": "tk1", "assigned_to": OWNER, "assigned_contact_id": "c1", "status": "open",
                       "due_date": past.date().isoformat()})
    t("referral_rewards").append({**b, "id": "rr1", "sent_at": None, "contact_id": "c0"})
    t("push_subscriptions").append({**b, "user_id": OWNER, "endpoint": "https://push.example/1",
                                    "subscription": {}})
    t("member_push_subscriptions").append({**b, "contact_id": "c0", "endpoint": "https://push.example/2"})
    t("ledger_chain_state").append({**b, "last_sequence": 9})
    t("texting_registrations").append({**b, "status": "submitted", "updated_at": _iso(past)})
    t("chief_cases").append({**b, "id": "case1", "status": "open", "check_on": past.date().isoformat()})
    t("chief_assignments").append({**b, "id": "as1", "status": "active", "next_check_at": None})
    t("custom_modules").append({**b, "id": "cmod1", "archetype": "booking_calendar", "is_active": True})
    t("google_mailboxes").append({**b, "id": "gm1", "status": "connected"})
    t("practitioner_rules").append({**b, "id": "pr1", "enabled": True, "trigger_type": "invoice_overdue"})
    t("church_checkin_settings").append({**b, "enabled": True})
    t("academy_live_sessions").append({**b, "id": "al1", "status": "scheduled",
                                       "starts_at": _iso(now + timedelta(hours=2))})
    t("chief_moves").append({**b, "queue_id": "q1", "outcome": "undone", "made_at": _iso(now)})


# ─── Recorders ────────────────────────────────────────────────────────

class Wire:
    def __init__(self):
        self.calls = []          # (what, detail)

    def hit(self, what, detail=""):
        self.calls.append((what, str(detail)[:200]))


def _install(monkeypatch, world: World, wire: Wire) -> None:
    import sb_clients
    for k, v in {"SUPABASE_URL": "https://fake.supabase.test", "SUPABASE_SERVICE_ROLE_KEY": "service",
                 "SUPABASE_ANON": "anon", "RESEND_API_KEY": "re_x", "TWILIO_ACCOUNT_SID": "AC1",
                 "TWILIO_AUTH_TOKEN": "t", "TWILIO_MESSAGING_SERVICE_SID": "MG1",
                 "TWILIO_PLATFORM_NUMBER": "+15550001111", "ANTHROPIC_API_KEY": "sk-x",
                 "DEVOTIONAL_DAILY_BUSINESSES": "*", "CHURCH_ASSIGNMENTS": "on",
                 "CHURCH_LEADER_TASKS": "on", "CHURCH_TEAM_ROLLUP": "on", "MARKETING_DESK": "*",
                 "POST_FOR_ME_BUSINESSES": "*", "CUSTOMER_TOKEN_SECRET": "secret-secret-secret-secret",
                 "CHIEF_INSIGHTS": "on", "BILLING_ENFORCE": "off"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(sc, "_columns_ready", lambda: True)
    sc._reset_for_tests()

    def serve(method, url, content):
        u = httpx.URL(str(url))
        path = u.path
        if "/storage/v1/" in path:
            return 200, []
        rest = path.split("/rest/v1", 1)[1]
        q = unquote(u.query.decode() if isinstance(u.query, bytes) else str(u.query))
        full = rest + ("?" + q if q else "")
        body = None
        if content:
            try:
                body = json.loads(content)
            except Exception:
                body = None
        if method in ("GET", "HEAD"):
            return 200, world.get(full)
        if method == "POST":
            return 201, world.post(full, body if body is not None else {})
        if method == "PATCH":
            return 200, world.patch(full, body or {})
        if method == "DELETE":
            world.delete(full)
            return 200, []
        return 200, []

    def answer(request):
        url = str(request.url)
        if request.url.host == "fake.supabase.test" and "/rest/v1/" not in url:
            return httpx.Response(200, json={}, request=request)      # auth admin and friends: nobody
        if "/rest/v1/" in url or "/storage/v1/" in url:
            code, data = serve(request.method, request.url, request.content)
            return httpx.Response(code, json=data, request=request,
                                  headers={"content-range": f"0-0/{len(data) if isinstance(data, list) else 0}"})
        wire.hit("network", f"{request.method} {request.url.host}")
        return httpx.Response(404, json={}, request=request)

    def send(self, request, **kw):
        request.read()
        return answer(request)

    async def asend(self, request, **kw):
        await request.aread()
        return answer(request)

    monkeypatch.setattr(httpx.Client, "send", send)
    monkeypatch.setattr(httpx.AsyncClient, "send", asend)

    real_connect = socket.socket.connect

    def connect(self, addr):
        host = addr[0] if isinstance(addr, tuple) else addr
        if host in ("127.0.0.1", "::1", "localhost"):
            return real_connect(self, addr)       # the event loop's own self-pipe
        wire.hit("socket", addr)
        raise OSError("no network in the sample church test")
    monkeypatch.setattr(socket.socket, "connect", connect)

    # No job waits here: a retry's back-off or a polite pause costs nothing.
    import time as _time
    _asleep = asyncio.sleep
    monkeypatch.setattr(_time, "sleep", lambda s: None)
    monkeypatch.setattr(asyncio, "sleep", lambda d, *a, **k: _asleep(0, *a, **k))

    # sb_clients' own wrappers go through httpx too; these short-cut the
    # common ones (and their redact/strict keywords) straight to the world.
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p, redact=False: world.get(p))
    monkeypatch.setattr(sb_clients, "sb_get_all_as_service", lambda p, **k: world.get(p))
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer="x": world.post(p, b))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda p, b: world.patch(p, b))
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", lambda p: (world.delete(p), True)[1])

    # The providers.
    import twilio_sms
    import email_sender
    import push_notifications
    import llm_call

    monkeypatch.setattr(twilio_sms, "send_sms",
                        lambda to, body, **k: wire.hit("sms", f"{k.get('business_id')} {to}") or "SM1")

    async def resend(**k):
        wire.hit("email", f"{k.get('business_id')} {k.get('to_email')}")
        return {"id": "em1"}
    monkeypatch.setattr(email_sender, "send_via_resend", resend)
    monkeypatch.setattr(push_notifications, "push_enabled", lambda: True)
    monkeypatch.setattr(push_notifications, "_send_one", lambda r, p: wire.hit("push", r) or True)
    try:
        import member_push
        monkeypatch.setattr(member_push, "ready", lambda: True)
    except Exception:  # pragma: no cover
        pass

    def llm(*a, **k):
        wire.hit("llm", k.get("business_id"))
        return httpx.Response(200, json={"content": [{"type": "text", "text": "{}"}], "usage": {}},
                              request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))

    async def allm(*a, **k):
        return llm(*a, **k)
    monkeypatch.setattr(llm_call, "post", llm)
    monkeypatch.setattr(llm_call, "post_with", llm)
    monkeypatch.setattr(llm_call, "post_lane", llm)
    monkeypatch.setattr(llm_call, "apost", allm)
    monkeypatch.setattr(llm_call, "sdk_client", lambda **k: wire.hit("llm", "sdk") or (_ for _ in ()).throw(
        RuntimeError("no sdk in this test")))
    monkeypatch.setattr(llm_call, "astream", lambda *a, **k: wire.hit("llm", "stream") or (_ for _ in ()).throw(
        RuntimeError("no stream in this test")))
    try:
        import social
        for name in ("send_post", "publish"):
            if hasattr(social, name):
                monkeypatch.setattr(social, name, lambda *a, **k: wire.hit("social", a[:1]) or {})
    except Exception:
        pass


async def _run_one(fn):
    if inspect.iscoroutinefunction(fn):
        return await asyncio.wait_for(fn(), 8)
    res = await asyncio.wait_for(asyncio.to_thread(fn), 8)
    if inspect.isawaitable(res):
        res = await asyncio.wait_for(res, 8)
    return res


TIMINGS: dict = {}


ACTED: dict = {}


def run_every_job(monkeypatch, *, sample: bool, only=None):
    import time as _time
    world, wire = World(), Wire()
    build(world, sample=sample)
    _install(monkeypatch, world, wire)
    ran, broke, missing = [], {}, []
    for job, ref in TICKS.items():
        if only is not None and job not in only:
            continue
        mod, _, attr = ref.partition(":")
        try:
            fn = getattr(importlib.import_module(mod), attr)
        except Exception as e:  # noqa: BLE001
            missing.append(f"{job}: {type(e).__name__}")
            continue
        t0 = _time.monotonic()
        n0 = len(wire.calls) + len(world.inserts)
        try:
            asyncio.run(_run_one(fn))
        except BaseException as e:  # noqa: BLE001 - a sweep failing here sends nothing either
            if isinstance(e, KeyboardInterrupt):
                raise
            broke[job] = f"{type(e).__name__}: {str(e)[:80]}"
        TIMINGS[job] = round(_time.monotonic() - t0, 2)
        ACTED[job] = len(wire.calls) + len(world.inserts) - n0
        ran.append(job)
    return world, wire, ran, broke, missing


def _outbound_inserts(world: World):
    """Inserts that belong to the church: anything carrying its id, or one
    of its people's numbers or addresses."""
    marks = [SAMPLE] + [p[1] for p in PEOPLE] + [p[2] for p in PEOPLE]
    return [(t, r) for t, r in world.inserts if any(m in json.dumps(r, default=str) for m in marks)]


# The platform owner's own jobs read the repo (ops_desk, unfinished_work):
# nothing about any business goes there.
PLATFORM_HOSTS = {"api.github.com"}

# A sweep may close its OWN due row for a sample, so it isn't picked up
# again; it may never write anything new.
_ALLOWED_PATCHES = {"chief_scheduled_actions", "chief_assignments", "chief_keep_warm", "events",
                    "agent_queue", "marketing_posts", "church_mail", "businesses", "clip_runs",
                    "media_clip_runs", "video_jobs"}


def test_nothing_is_ever_sent_spent_or_written_for_a_sample(monkeypatch):
    world, wire, ran, broke, missing = run_every_job(monkeypatch, sample=True)
    assert len(ran) >= len(TICKS) - 3, f"jobs that would not import: {missing}"
    calls = [c for c in wire.calls if not (c[0] == "network" and c[1].split()[-1] in PLATFORM_HOSTS)]
    assert calls == [], f"a sample church reached a provider: {calls[:10]}"
    inserted = _outbound_inserts(world)
    assert inserted == [], f"rows written for a sample: {[(t, sorted(r)[:6]) for t, r in inserted][:10]}"
    touched = {t for t, ids, _ in world.patches if SAMPLE in [str(i) for i in ids]}
    assert touched <= _ALLOWED_PATCHES, f"sample rows changed by a sweep: {sorted(touched - _ALLOWED_PATCHES)}"
    biz = next(r for r in world.rows("businesses") if r["id"] == SAMPLE)
    assert biz["is_sample"] is True


# The jobs that act on the control church's rows (found by running every
# job over it: _debug_control). Run alone, so the control stays quick.
CONTROL_JOBS = ("push_morning_brief", "autopilot_sweep", "notif_morning_brief",
                "church_follow_up_sweep", "news_reach", "chief_scheduled", "chief_agent",
                "chief_assignments", "chief_cases", "proposal_life", "brain_pass", "chief_week")


def test_the_control_church_does_get_sends(monkeypatch):
    """The same rows on a real church: the jobs act on them. Without this
    the test above could pass on a fixture no job ever reads."""
    world, wire, ran, broke, missing = run_every_job(monkeypatch, sample=False, only=CONTROL_JOBS)
    marks = [SAMPLE] + [p[1] for p in PEOPLE] + [p[2] for p in PEOPLE]
    calls = [c for c in wire.calls if any(m in c[1] for m in marks)]
    acted = {job for job in CONTROL_JOBS if ACTED.get(job)}
    assert len(calls) + len(_outbound_inserts(world)) >= 5, (wire.calls, broke)
    assert len(acted) >= 6, f"only {sorted(acted)} acted on the control church: {broke}"


def _debug_control(monkeypatch):  # pragma: no cover - run by hand to see what fires
    world, wire, ran, broke, missing = run_every_job(monkeypatch, sample=False)
    print("CALLS", wire.calls)
    print("INSERTS", [(t, sorted(r)[:5]) for t, r in _outbound_inserts(world)])
    print("SLOW", sorted(((v, k) for k, v in TIMINGS.items()), reverse=True)[:8])
    print("BROKE", broke)
    print("ACTED", {k: v for k, v in ACTED.items() if v})
    print("MISSING", missing)
