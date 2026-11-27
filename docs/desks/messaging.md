# Desk: messaging

## 1. What it owns

How words leave and arrive, in plain words:

- **Texting** — the Text room: conversations, the guest card, announcements
  (now or scheduled, to everyone or a group), saved replies, "Draft with Chief",
  a business's own number, "New here" guest texts, the church's texting hours,
  quiet hours and alert limit, and texting under the church's own name
  (Twilio registration). STOP/HELP and consent.
- **Email** — Email Setup (sending domain, DNS records, test send, health),
  every branded email a business sends, inbound replies, the Email room, and
  **church mail**: a box per leader or role at the church's own domain
  (prayer@, office@…), with copies, replies, signatures, archive and alerts.
- **App notifications** — staff push (Chief's morning brief, urgent pings), the
  member app's phone alerts (three layers of yes), the bell's "Your alerts"
  list, church notes that read like texts in the member's Messages, News alerts.
- **Lifecycle email** — welcome, trial and plan emails from the platform.

## 2. Where the code is

Backend (`kmj-intake-server`):

| Area | Files | Routes |
|---|---|---|
| SMS core | `sms_service.py` (normalising, `compose_outbound_body`, STOP check, `sender_for`, `sms_messages`), `twilio_sms.py` (the one Twilio send, inbound + status webhooks, `reconcile_sent`), `sms_routing.py` (binding first, keyword second, threads, opt-in, announcements), `sms_numbers_router.py` (a business's own line), `sms_usage.py` (one `api_usage` row per text), `sms_alerts.py` (`said_yes_to_texts`) | `/sms/*`, `/webhooks/twilio/sms`, `/webhooks/twilio/status`, `/api/sms/opt-in` |
| Text room | `text_room.py` (guest, prayer, replies, person, draft), `new_here.py`, `guest_replies.py`, `texting_hours.py`, `news_reach.py` (app first, then text) | `/sms/*`, `/texting-hours/*` |
| Own-name texting | `texting_registration.py` (rows, owner routes, `/texting-terms` + `/texting-privacy` pages, `/texts` sign-up), `texting_isv.py` (Twilio ISV calls, sub-account per business), `docs/plans/ISV_TEXTING_PLAN_2026-10-11.md` | `/texting/*` |
| Church text bill | `church_texts.py` (count + heads-up; the bill itself is money's) | |
| Email out/in | `email_sender.py` (`/email/send`, `/email/inbound`, `/email/webhook`, unsubscribe), `email_layout.py`, `email_domain_dns.py`, `email_domains_router.py`, `email_domain_monitor.py` (hourly drift), `mailbox_policy.py` (what Chief may read), `lifecycle_emails.py`, `lifecycle_delivery.py`, `group_email.py`, `booking_confirmation_emails.py` | `/email/*`, `/email-domain/*` |
| Church mail | `church_mail.py` (sorting inbound by church, boxes, relay), `church_mail_room.py`, `church_mail_alerts.py`, `chief_church_mail.py` | `/church-mail/*` |
| Retired | `gmail_sync.py`, `google_oauth.py` — Gmail connect retired 2026-11-14 (no new connects, sync stopped) | |
| Push | `push_notifications.py` (staff, `push_subscriptions`), `notification_engine.py` (brief/ping/urgent, `/agents/notifications/*`), `member_push.py` (member phones, `/my/push/*`, `/my/notifications`, `/member-portal/{id}/announce`), `member_alerts.py` (the bell), `news_alerts.py`, `group_chat_notify.py` | `/push/*` |
| Member messages | `church_threads.py` (office API `/church-threads/{biz}...`), `member_portal_threads.py` + `member_portal_messaging.py` (member pages; shared with member-app), `member_messaging_rules.py` (who may message whom, the ONE place), `msg_screen.py` (every member message screened), `messaging_router.py` (`/messaging/settings`, safety officers, reports) | |
| Guards | `webhook_guard.py` (missing secret = dropped), `untrusted_text.py` (inbound words are data) | |
| Chief verbs | `chief_sms_actions.py`, `chief_church_mail.py`, `chief_email_setup_actions.py` | |

Main tables: `sms_messages`, `sms_bindings`, `sms_keywords`, `sms_numbers`,
`sms_opt_outs`, `sms_consents`, `texting_registrations`,
`chief_scheduled_actions` (type `sms_announcement`), `church_mailboxes`,
`church_mail`, `church_mail_people`, `push_subscriptions`,
`member_push_subscriptions`, `member_push_prefs`, `member_push_sends`,
`member_push_held`, `church_thread_notes`, `church_thread_reads`, `msg_threads`,
`msg_messages`, `msg_participants`, `msg_members`, `msg_reports`,
`chief_notifications`, `platform_emails` (Mission Control inbox), `api_usage`.

Frontend (`solutionist-studio`):
`src/core/components/SmsHub.tsx` + `texting/` (TextThread, AnnouncementSheet,
NewHereRoom, AppMessagesRoom, TextingHoursSheet, TextingSettings,
`churchThreads.ts`), `TextingRegistration.tsx`, `email-room/` (EmailRoom,
church mail panels, `churchMail.ts`, `mailAlerts.ts`), `email-setup/`,
`notifications/`, `NotificationCenter.tsx`, `PushToggle.tsx`,
`MemberNotificationsSection.tsx`; libs `src/core/lib/textCount.ts` (mirrors the
server's body composer), `churchAlerts.ts`, `officeAlerts.ts`; Mission Control
inbox `src/modules/platform/pages/InboxPanel.tsx`.

## 3. Rules that must not break

- **Inbound webhooks fail closed.** Twilio (`X-Twilio-Signature`,
  `TWILIO_AUTH_TOKEN`), Resend (svix signature, `RESEND_WEBHOOK_SECRET`, 5-minute
  replay window). A missing secret drops the event unless the provider is named
  in `WEBHOOK_ALLOW_UNSIGNED` — never set that casually.
- **Inbound text and email are untrusted.** Their bodies reach Chief's prompt;
  they pass through `untrusted_text`, and a tainted turn holds class-C sends.
  Never let an inbound body become an instruction or an action tag.
- **Every send pins `from_`** through `sms_service.sender_for`. An unpinned send
  can leave from another business's line.
- **STOP is checked before every outbound send**; the opt-out tail is the last
  thing in the body. Consent is recorded in `sms_consents`; never write app
  replies into `sms_messages` — an inbound row there counts as a yes to texts.
- **Texting hours:** automatic texts only inside the church's window, never
  outside the federal calling hours (`texting_hours.py`); quiet hours hold app
  alerts (`member_push.quiet_hour`).
- **One campaign for many companies is refused by carriers** (Twilio 30926):
  churches register under their own name (`TEXTING_REGISTRATION_OPEN`).
  An unregistered number never stops working; the owner is nudged once.
- **A text is never stopped by the allowance.** `church_texts` warns and bills
  the extra; sign-in codes aren't counted. Every text logs one `api_usage` row
  (`sms_usage`); texts stay out of the spend guard and credits.
- **Paid AI drafts** (`/sms/draft`) go through `billing_limits.require_units`,
  `spend_guard` and a rate bucket, and use public facts only.
- **Member alerts need three yeses:** the church's switch per kind, the
  member's own choice, and a device turned on. `member_messaging_rules.py` is
  the only place that decides who may message whom (birthday on record, teen
  rules, two adult leaders in a teen group). A birthday typed in the app never
  opens messaging.
- **Church mail is never misrouted:** a failed read makes `/email/inbound`
  answer 503 so Resend retries; a domain is church mail only if the business owns
  it AND its MX really points at Resend receiving. Prayer mail goes to care
  requests, never copied into inboxes.
- Server writes use the service role; staff marks-read through `POST /sms/read`
  (staff can read `sms_messages`, not update it).
- Wording: no carrier or Twilio jargon on practitioner screens; plain words.

## 4. Traps already hit

- Status callbacks raced the row insert and left texts "stuck"; hourly `twilio_sms.reconcile_sent` repairs them.
- The Twilio API key is send-only; number lifecycle uses the account token (`twilio_sms._twilio_admin_client()`).
- Staff read access to `sms_messages` comes from a DO-loop policy; grepping `on public.sms_messages` misses it. Read `pg_policies`.
- `/sms/conversation` must select `contact_id` and `sent_by`, or the thread marks nothing read.
- Phone numbers in PostgREST filters must be URL-encoded (`+1…`), or number-only threads open empty.
- Old docstrings still say Telnyx; sending is Twilio only.
- Namecheap: switching Mail Settings to Custom MX deletes the MX records it managed — a church's existing mail can vanish. Record `mail_before`, end with a test message and a way back.
- An MX can't sit beside a root CNAME; the root must be an ALIAS (same target).
- Resend drops mail until the receiving MX shows verified; switch a church at a quiet time, after its current addresses have boxes.
- The domain badge said Verified while sends fell back to the platform address; the identity seam reads STORED status, and the hourly monitor catches DNS drift.
- Forge gives new domains a CNAME return path; the DNS checker once read it as TXT.
- The Google mailbox upsert needed `on_conflict` or every reconnect failed (moot now the Gmail connect is retired; reviving it needs Google's yearly review — owner's call).
- Env vars are per Railway service: the worker runs the scheduled jobs; the web process does not.
- Member alert kinds default ON from `member_push.DEFAULT_ON_FROM` (`MEMBER_ALERTS_DEFAULTS` overrides); `__tests__/conftest.py` runs it off for unit tests.
- iPhone web push works only once the app is on the home screen, and permission must be asked from a tap.
- Office replies in church threads push immediately, ignoring quiet hours; a held member message alerts safety officers with no words and has no release action yet.
- The "every adult with a birthday" messaging switch (BE #2084) was still an open PR at writing — check before building on it.
- `whatsNew.ts` merge conflicts are CRLF; normalise before resolving.

## 5. How to check work

- Backend: `pytest -q __tests__/test_<area>.py` — `test_inbound_webhook_signatures.py`, `test_sms_tenant_isolation.py`, `test_sms_metering.py`, `test_sms_numbers_inbound.py`, `test_sms_announcements.py`, `test_sms_mark_read.py`, `test_text_room.py`, `test_texting_hours.py`, `test_texting_registration.py`, `test_texting_isv.py`, `test_church_texts.py`, `test_email_inbound_route.py`, `test_email_setup_rails.py`, `test_email_setup_namecheap.py`, `test_sender_domain_verified.py`, `test_church_mail.py`, `test_church_mail_room.py`, `test_unsubscribe_holds_on_bulk_email.py`, `test_lifecycle_emails.py`, `test_member_push.py`, `test_member_alerts_default.py`, `test_member_quiet_hours.py`, `test_member_messaging_rules.py`, `test_msg_screen.py`, `test_church_threads.py`, `test_news_alerts.py`, `test_notification_act_as_who_tapped.py`.
- Real Postgres (PGlite, CI job `test-db`, `PGLITE_MODULE` set): `node __tests__/quiet_hours_db.mjs`, `news_alerts_db.mjs`, `group_email_db.mjs`, `serving_alerts_db.mjs`, `serve_email_stop_db.mjs`, `node scripts/lifecycle-email-db-check.mjs`.
- Frontend: `npx tsc -p tsconfig.app.json --noEmit`, `npx vite build`; previews
  `tests/texting-preview.html` (with `tests/church-overviews.vite.config.ts`),
  `tests/texting-registration-preview.html`, `tests/email-room-church-preview.html`
  (`tests/email-room-church.vite.config.ts`). Check phone width.
- Live: never text or email real people to test; use the platform owner's own
  test number/address and fake contacts. Twilio's Alerts API proves callbacks
  got a 2xx.

## 6. Edges

- **member-app** — shares `member_push.py`, `member_portal_threads.py`,
  `member_portal_messaging.py` and the alert settings pages; we own delivery and
  rules, they own the member pages' look.
- **church-office** — `new_here`/guest follow-ups hand into `church_follow_up`;
  prayer texts and prayer@ mail become `ministry_care_requests` (care desk is
  theirs); News posts (`church_news`) are theirs, the ringing is ours.
- **money** — `church_texts.py` counts, money bills the extra; giving
  statements use our email rails.
- **websites** — texting terms/privacy and `/texts` pages render on church sites;
  root ALIAS and custom domains (`cloudflare_saas.py`) are theirs.
- **chief** — verb plumbing and the injection boundary in `chief_of_staff.py`;
  our modules supply the reads and sends.
- **system** — `webhook_guard`, the worker/scheduler, migrations, RLS.
  **tickets** hands us "texts not sending" / "email not arriving" with evidence.
