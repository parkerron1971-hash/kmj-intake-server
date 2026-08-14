# THE LEAD ARC — capture, enrich, watch

**Opened:** 2026-08-13 · **Repos:** `kmj-intake-server` (trunk `main`),
`solutionist-studio` (trunk `module-system`)

## The finding

The system has **four public lead doors**. Almost every piece of lead
intelligence is bolted to one of them — the embeddable intake form,
which is the door a practitioner is *least* likely to use, because the
Solutionist-composed site ships its own contact form on a different
door entirely.

| door | dedupe | `source` | scored | in-app alert | spine event |
|---|---|---|---|---|---|
| `POST /intake/submit` (embed) | **none** | `intake_form` | yes | no | `form_submit` (legacy) |
| `POST /sites/{id}/contact-submit` | email + phone | `website_contact_form` | no | no (email only) | `contact_form_submitted` |
| `POST /public/concierge/{slug}/lead` | email | `site_concierge` | no | yes | `concierge_lead_captured` |
| booking widget | email (exact) | `booking_widget` | no | yes | — |

RSVP (`events_rsvp_router`) and giving (`giving_router`) open two more
doors that also write `status='lead'`.

`contacts.lead_score` is written in exactly one place in the whole
backend — `intake_endpoint.py:536`. Everything gated on it therefore
only ever sees intake-form leads:

- `notification_engine.py:509` — hot-lead urgent alert
  (`event_type=eq.form_submit` **and** `lead_score >= 70`)
- `contract_agent.py:406` — the proposal agent (`lead_score=gte.60`)
- `ContactsList.tsx:103` — the "Hot Leads" smart list (`>= 80`)
- `chief_of_staff.py:13040` — Chief's briefing (a *fourth* threshold,
  on `health_score > 70`, itself only ever set as `lead_score + 10`)

Four definitions of "hot", one feeder.

## The arc

Six PRs. Each is independently shippable and independently useful.
One PR per change; never stacked.

---

### PR 1 — Every door scores the lead  ✅ **SHIPPED #574**

The score becomes a property of *being a lead*, not a property of
having arrived through one particular form.

- New `lead_scoring.py`: one scorer, called by every capture path.
  - A **deterministic rubric** runs synchronously and always — so
    `lead_score` is never null and the downstream readers work with
    zero AI spend.
  - An **optional Haiku refinement** runs in the background, behind
    `spend_guard`, and only when there is free text worth reading.
    It never blocks the visitor's form submit.
- The rubric is **vertical-neutral**. Today's intake prompt enumerates
  `warm_welcome (church/ministry visitor)` and
  `discovery_invite (coaching/consulting prospect)` — a lookup table
  for two of seven verticals. A barber, attorney or contractor has no
  bucket. Replaced with named, weighted signals that mean the same
  thing in every trade (reason from a rubric, not a lookup table).
- Readers widened to match: the hot-lead trigger reads every inquiry
  event type, and Chief's briefing reads `lead_score` (falling back to
  `health_score` for legacy rows).

Booking is deliberately **not** wired to the hot-lead alert — someone
who already picked a time is not a lead to chase today.

### PR 2 — The alarms actually ring  ✅ **SHIPPED #575**

`notification_engine`'s `check_urgent` / `morning_brief` /
`midday_ping` / `evening_summary` are imported as a **router only**
(`kmj_intake_automation.py:34`). None of the 22 scheduled jobs is a
notification tick, and nothing in `src/` calls the endpoints. Meanwhile
`NotificationCenter.tsx` ships user toggles for all four.

Switches for alarms that do not fire.

- Put the ticks on the worker scheduler (`PROCESS_ROLE=worker`), with
  `next_run_time` set explicitly — an APScheduler interval job's first
  run is `now + interval` and resets on every deploy.
- Teach `push_notifications.morning_brief_tick` to count leads. Today
  it reports sessions, overdue invoices and drafts, and never mentions
  a lead.
- **Rehearse the alarm before shipping it.** A monitor that has never
  been seen to fire is indistinguishable from a broken one.

**Found while rehearsing it:** several of these windows were built with
`isoformat()`, which ends `+00:00`, and `+` decodes to a SPACE in a
query string. `_gather_morning_data`'s sessions-today filter, the
mid-day cutoff, the dedup lookups and the urgent cutoff were all
matching nothing and returning 200 with an empty list — a broken query
that reads exactly like a quiet day. The evening gather had been fixed
by hand and the others had not. All of them now go through one `_z()`
helper, with a sweep test over every window this module opens.

Also here: the three briefs called the model unconditionally, so an
empty day still bought a Sonnet call to be told the runway was clear.
On a schedule across every active business that is the bulk of the
spend, all of it on nothing. `has_anything_to_report()` gates it.

### PR 3 — Two defects  ✅ **SHIPPED #576**

- **Cross-tenant write.** `intake_endpoint.py:382` fetches the form by
  id alone, then writes the contact under the caller-supplied
  `req.business_id`; the two are never compared. `form_id` is public —
  it sits in the embed snippet on the practitioner's own site — so a
  submission can be written into any business. Reject when
  `form_config["business_id"] != req.business_id`.
- **Rate limiter keyed on the proxy.** `public_site.py:2071` and
  `site_concierge.py:234/748/887` use `request.client.host`.
  `rate_limit.py` already documents that this is not the visitor behind
  Railway — that is why `trusted_client_ip()` exists and why
  `intake_endpoint` uses it. As written every visitor to every
  published site likely shares one bucket, so the 6th contact-form
  submission platform-wide in a minute gets a 429. Measure it first,
  then switch all four call sites.
- Dead honeypot: `intake_endpoint.py:367` checks `_hp` / `website_url`
  / `company_url` / `fax`; `IntakeFormBuilder.getEmbedCode()` renders
  only the configured fields, so no honeypot input is ever emitted and
  the guard cannot trip. **Worse than dead — actively dropping leads.**
  `IntakeFormBuilder.tsx:542` derives a field's `name` from its label
  (`lowercase`, `[^a-z0-9]+` → `_`, strip edge `_`), so "Fax" → `fax`,
  "Website URL" → `website_url`, "Company URL" → `company_url` — three
  of the four honeypot names. Any form carrying one of those fields
  discarded 100% of its submissions and answered 200 to every one.
  Names are collision-proof by construction now (`sol-hp`, `_hp`), and
  the trip logs at WARNING with the form id. Shipped as **PR 3b** here
  plus a frontend PR that emits the field.

**Found fixing the limiter:** `site_concierge._visitor_key` hashed the
same `request.client.host` into its per-VISITOR identity, which feeds
the daily message cap. Keyed on the proxy, two strangers running the
same browser shared one identity and one person's conversation ate
another's allowance. Same one-line cause, worse consequence than the
rate limit.

### PR 4 — The first-response clock  ✅ **SHIPPED #578**

There is no `responded_at`, no SLA field, no first-response metric
anywhere in either repo. The nearest thing is `growth_engine.py:1105`,
which flags a stale lead at **30 days old plus 14 days silent** — a
monthly insight, not an alarm. Nothing catches a lead unanswered for a
day.

- Migration: `contacts.first_response_at` + two partial indexes.
  **APPLIED 2026-08-14** (`APPLY-2026_08_14_first_response_clock.sql`).
- **DERIVED, not stamped.** There are at least six outbound paths and
  one of them is the frontend, which PATCHes `agent_queue` to `sent`
  straight from `ContactDetail.tsx`. Six call sites is six chances to
  miss one, and a missed one reads as a lead nobody ever answered — a
  false alarm, which is the fastest way to teach someone to ignore a
  real one. All six already leave a durable record; `lead_response.py`
  reads those on a 15-minute tick.
- Alert at N hours unanswered — **PR 5, SHIPPED**: one alert per
  business per DAY (not one per lead), inside waking hours only,
  threshold `settings.notifications.lead_response_hours`, default 4.
- Median first-response on the funnel — the **frontend PR**.

### PR 6 — Attribution  ← **in flight**

A lead currently carries name, email, phone, status, source, and the
raw submission blob. It carries no idea where it came from.

- `WebsiteTraffic.tsx:188` reads
  `ev.data?.utm_source || ev.data?.referrer_host || ev.data?.referrer
  || 'direct'`. **Nothing writes any of the three.** "Top source" is
  therefore hardcoded to `direct` for every form, forever — a UI that
  states a fact it cannot know.
- `contacts.source_detail` **DID NOT EXIST IN THE DATABASE AT ALL**,
  and three frontend files use it. PostgREST rejects an unknown column
  outright (`booking_widget_router.py:1082` documents the same class:
  PGRST204 → 500), so both analytics reads 400 — which is why every
  form shows avg lead score `—` and conversion `—` — and
  `OperationsDashboard.tsx:994`'s **quick-add-a-lead button has never
  worked**, because it posts that column and gets a 400.
  Added 2026-08-14 with `contacts.attribution`.
- `how_heard` ships on the form templates and is read by nothing.
- Published customer sites have **no page-view tracking at all**.
  `site_analytics.py` covers mysolutionist.app only and is gated to
  `PLATFORM_OWNER_EMAIL`, so there is no visitor→lead conversion rate
  to compute.

**SHIPPED**: captured SERVER-SIDE off the `Referer` header at all four
doors, because the contact form is emitted by four different renderers
plus whatever the builder's LLM writes — a design needing every client
to cooperate is partially deployed forever. Referrers reduced to a
HOST, query strings dropped except a campaign whitelist
(`utm_*`/`gclid`/`fbclid`/`ref`), because a query string on somebody
else's page can hold an email address or a session token.

Still open, and a separate arc rather than a PR: **page-view tracking
for published customer sites.** `site_analytics.py` covers
mysolutionist.app only, `site_events` has no `business_id`, and the
read is gated to `PLATFORM_OWNER_EMAIL` — so there is no visitor→lead
conversion rate to compute for a practitioner. `how_heard` is also
still read by nothing.

### PR 7 — One dedupe rule

Four doors, four different answers to *is this the same person*:
no dedupe at all (intake), email-ilike-or-phone (site form),
email-ilike (concierge), email-eq (booking). `contacts` has no unique
index on `(business_id, lower(email))` —
`booking_widget_router.py:1062` already flags the resulting race.

One `resolve_contact()` used by every door, plus the index.

## Also true, not scheduled

- `/intake/submit` requires only a name; email and phone are both
  optional. It can create a lead with no way to reach them.
- SMS consent is captured on booking and the site contact form. The
  intake door captures none — and it is the door that then drafts the
  visitor an email. No email/marketing consent is captured anywhere.
