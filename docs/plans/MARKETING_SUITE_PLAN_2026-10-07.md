# Marketing suite for every business — build plan (2026-10-07)

Kevin approved the design https://claude.ai/artifact/4xHUMP7EhR4dTJ1LSQyK9t on
2026-10-07 ("This will work. let's build this."). One suite (the Mission
Control desk, made multi-tenant); the plan decides how much of the work Chief
does. This plan came from a read-only pass over origin/main and
origin/module-system the same day. About 24 PRs (16 backend, 8 frontend).

## The ladder

| Level | Plans | What Chief does |
| --- | --- | --- |
| Suggest | Starter, Solo, Booked | Posts what you ask (flyers + Facebook/Instagram are promised to every plan) plus ONE suggested post a week to approve, and an upgrade nudge. |
| Week | Professional | The Thursday 7 AM loop: the business's own numbers, one named problem, five posts with flyers, approve the week in one tap, results shape next week. |
| Openings | Boss (barbers/salons) | Barber-sized week from the chair calendar: open slots become posts, the owner's work photos, 3 a week, Instagram first, a post is pulled if its slot books first. No Video Clips. |
| Autopilot | Solutionist (practice) | Clips with covers folded into the week, every network, standing permissions for chosen kinds, Chief's log. |

Same on every level: nothing posts without the owner's OK unless a standing
permission covers that kind; Chief never posts on its own initiative; one
posting path (Post for Me, the business's own connected accounts); every post
has a tracked link.

## Three findings that shape everything

1. **Plan gates are permissive.** `feature_gates.has_feature()` passes every
   business unless `BILLING_ENFORCE=on`, and the frontend `useEntitlements().has()`
   is permissive too. Anything that spends money unasked must check the real
   plan: `feature in plan_features(plan_of(row))` (new `plan_includes`).
2. **The platform spend breaker is shared.** `DAILY_SPEND_CAP_USD` (default
   $50) covers the whole platform; ~100 businesses × ~$0.50 on Thursday would
   trip it and block paid AI for everyone until UTC midnight. The fan-out must
   be jittered, capped per tick and check headroom per business.
3. **Background posting needs `image_studio.build_actor`.** On the worker there
   is no JWT; `storage_headers()`/`original()` 401 unless `build_actor` is bound
   to `{business_id, user_id: owner}` (as `marketing_design.acting_for` does).
   Applies to `images.delivery_jpeg`, `clip_posting.post_clip_for`,
   `chief_flyer_composer.compose` and Creative Director designs.

## Decisions (D1–D7)

- **D1 Data model:** new `marketing_*` tenant tables; leave `platform_marketing_*`
  untouched until step 5 (single-row config, `week_of` UNIQUE, one row per
  Buffer channel). New tables are one row per idea with `targets jsonb`
  (matches `social_publications`). Migration `supabase/APPLY-2026-10-xx-marketing-suite.sql`:
  `marketing_desks` (business_id PK, plan_enabled, paused, connection_ids,
  post_hour 6..21, audience, landing_url, work_photo_ids, updated_at),
  `marketing_runs` (business_id, week_of, kind suggestion|week|openings,
  trigger, status, attempts, signals/diagnosis/plays/slots/dropped/design jsonb,
  post_ids, error, UNIQUE(business_id, week_of)), `marketing_posts` (source
  suggestion|plan|owner|chief|clip|opening, caption, publish_text, landing_url,
  tracked_url, link_code, media jsonb, targets jsonb, opening jsonb,
  design_status, content_hash, approved_hash/by/at/via owner|standing,
  revision, status draft|approved|dispatching|submitted|published|
  partly_published|failed|uncertain|cancelled|pulled, run_at, expires_at,
  publication_id, external_urls, error, claimed_at, checked_at),
  `marketing_link_clicks`, `marketing_post_events`. RLS: owner + member SELECT
  only (copy the social_* migrations), service-role writes, no USING(true),
  cross-table checks only via SECURITY DEFINER helpers. RPCs (service_role
  only): `marketing_claim_run`, `marketing_approve` (all-or-nothing, same
  business, draft, same revision/hash, future run_at, not designing),
  `marketing_claim_due` (stale dispatching→uncertain, expired→failed, SKIP
  LOCKED, desk not paused), `marketing_follow`. Add the tables to
  `account_lifecycle.BUSINESS_CHILD_TABLES` (history tables in `_IMPORT_SKIP`).
- **D2 Engine per business:** a profile layer (audience, system prompt,
  problems/plays, landing, facts, signals, diagnosis, caption checks); today's
  `marketing_engine` constants become the "platform" profile at step 5.
  `marketing_signals.py`: site_events by business_id, contacts, bookings in
  module_entries, open capacity via `agent_site.slots_for`, new offerings, site
  news, last post, play scores — failed reads are None, never 0. Facts from
  `creative_director.business_facts`; caption numbers/prices only from facts.
  TZ chain: availability.timezone → practitioner_profiles.timezone →
  PLATFORM_DEFAULT_TZ. Flyers: suggestion = free composer flyer; week =
  Creative Director under build_actor (uses the 20/day cap); Boss = composer over
  the owner's photo. Thursday fan-out: worker only, `scheduler_lock.gate`,
  hourly, candidates have a connected account + pilot gate + desk enabled +
  `plan_includes` + access_state full|grace + not policy-paused + env
  `MARKETING_DESK`; due Thursday 7:00 local + jitter hash(id)%120 min;
  `MARKETING_MAX_PER_TICK`; spend headroom checks (defer all at ≥60% of cap);
  per-business try/except; metered via `llm_call.apost(task=..., business_id=...)`.
- **D3 Posting:** one path, `social_publish_router.send_post`. The desk keeps its
  own claim-and-send (`marketing_claim_due` every minute); at send time re-check
  hash, pause, pilot gate, targets; bind build_actor; image/text →
  `delivery_jpeg` → `_check` → `send_post(publication_id=uuid5(post, rev))`;
  clip → `post_clip_for`. Errors mirror the platform `dispatch` (pre-hand-off →
  approved, refused → failed, post-hand-off → uncertain + `/not-sent`).
  Approval binding as the desk's content_hash (targets included). Delivery
  watch every 5 minutes via `social._refresh` (no webhook) → published /
  partly_published / failed / uncertain after 2 h; one push + Today item per
  problem (`push_notifications.send_to_user(..., nav='grow:marketing')`,
  `chief_notifications` like `standing_permissions._tell`).
- **D4 Gates:** `marketing_suggestion` (starter → all; Solo/Booked inherit),
  `marketing_week` (professional; Boss via AUDIENCE_PLAN_FEATURES),
  `marketing_autopilot` (practice); clips also need `ai_clips`. Boss's
  barber-sized week is a SHAPE of marketing_week chosen by business type
  (personal_services with a calendar). New `plan_includes(row, feature)`
  ignoring BILLING_ENFORCE (comps count). All three keys in
  UNANNOUNCED_FEATURES and `marketing_pages._NOT_A_ROW` until launch.
  `GET /marketing/{biz}/engine` returns `level` + `upgrade`; the frontend uses
  that, not `useEntitlements().has()`.
- **D5 Boss:** open chairs from `agent_site.slots_for(bundle_for(biz), offering,
  start, end)`; most-booked offering (60 days) else shortest; contiguous open
  slots → windows; pick 3; post the day before/morning ≥2 h ahead; booking URL;
  Instagram default; the owner's newest work photo with words laid over by the
  composer. Pull: `opening` stores offering/starts/ends/open_count; recheck
  before send and every 15 min for the next 48 h; pulled → Today item, never
  needs a yes. Captions say "Open chairs Thursday 2–5" without a number until
  `concurrent_capacity` is verified.
- **D6 Solutionist:** eligible clips (ready, approved with matching fingerprint,
  kept, not yet posted, covers ready) become `source='clip'` slots sent through
  `post_clip_for`. Standing permissions reuse `standing_permissions` with kinds
  `post_clip` and `marketing_post`, gated by `plan_includes(marketing_autopilot)`
  and `client_facing_autonomy`; granted kinds approved with `approved_via='standing'`;
  push + Today item; ask-after-3 / retire-after-3 from `marketing_posts` history;
  Chief's log via `chief_activity` + `audit_log`.
- **D7 Frontend:** a new `marketing` leaf first in Grow → Reach, replacing
  Content Plan / "Posts"; Outreach stays. Reuse MC's `MarketingThisWeek`,
  `MarketingReview`, `MarketingDeskParts`, `lib/marketingWeek.ts`,
  `marketingApi.ts` types (they take a `request` prop); generalize the
  Buffer-tied props. Practitioner Chief via the `solutionist-chief` event.
  Phone first: one column, thumb-sized Approve/Change/Skip, sticky "Approve the
  week (5)", New post bottom sheet, agenda calendar.

## PR sequence (no stacking; backend before frontend where paired)

Backend (kmj-intake-server, `main`):
- **B1** Chief posts a picture to your accounts (`post_image`, `image_posting.py`,
  `chief_social_actions.py`), class C, unattended refused. No migration.
- **B2** Plan gates, dormant and unannounced (+ `plan_includes`).
- **B3** Storage: migration + `business_marketing_store.py` + PGlite tests.
- **B4** Desk API for one business (`/marketing/{business_id}`: engine, ideas,
  next-slot, approve, slot edit/cancel, post-now, not-sent, settings) +
  `business_marketing_desk.py`. Depends on B3 applied.
- **B5** Sending through Post for Me + delivery watch (`business_marketing_dispatch.py`,
  jobs `business_marketing_due` 1 min, `business_marketing_delivery` 5 min,
  env `MARKETING_DESK_PUBLISHING`, default off). Depends on B4.
- **B6** Tracked links on the business's own site + results. Depends on B4.
- **B7** Numbers, facts, profile, read-only preview endpoint. Depends on B3.
- **B8** Weekly suggestion for every level + the hourly fan-out. Depends on B2, B5, B6, B7.
- **B9** Weekly plan (Professional; Boss via B11). Depends on B8.
- **B10** Chief works the desk (read, new post, edit, skip, replan; post-now class C; no approve verb). Depends on B9.
- **B11** Boss: openings, pulled posts, work photos. Depends on B9.
- **B12** Clips folded into the week. Depends on B9.
- **B13** Autopilot: standing permissions for marketing. Depends on B12, B2.
- **B14** Launch the copy (pricing rows, features page, FAQ, docs). Depends on the levels opened.
- **B15** Step 5: Solutionist's own desk on the suite (`MC_MARKETING_SUITE` flag; drain Buffer). Depends on B9, B10, B6.
- **B16** Retire the Meta path (`publish_post`, Content Plan publish, Image Studio publish). Depends on B5, F8.

Frontend (solutionist-studio, `module-system`):
- **F1** Extract and generalize the desk components into `src/features/marketing-desk/` (no behaviour change).
- **F2** Grow → Marketing desk shell (This week, Calendar, Settings; New post; Ask Chief; nav). Depends on F1, B5.
- **F3** Results tab. Depends on B6, F2.
- **F4** Weekly suggestion card, upgrade nudge, Professional week. Depends on B9 (B8), F2.
- **F5** Boss view. Depends on B11, F4.
- **F6** Solutionist view. Depends on B12, B13, F4.
- **F7** Mission Control on the suite. Depends on B15, F1.
- **F8** Retire Content Plan's Meta publishing. Depends on F2.

## Kevin, by hand

1. Confirm `social_connections` / `social_publications` are live (`SELECT to_regclass('public.social_publications')`); apply B3's migration after merge.
2. Env: `POST_FOR_ME_API_KEY`, `POST_FOR_ME_PILOT_BUSINESSES` (`*` or the pilot ids); new `MARKETING_DESK_PUBLISHING`, `MARKETING_DESK`, `MARKETING_MAX_PER_TICK`; raise `DAILY_SPEND_CAP_USD` before widening; a `PROCESS_ROLE=worker` service runs (verified 2026-10-06).
3. Post for Me dashboard: enabled networks (LinkedIn is off there).
4. Comp test businesses to each plan; first real posts to a test account.
5. Step 5: connect Solutionist's own accounts in Post for Me, pause Buffer, drain, flip, `BUFFER_PUBLISHING=off`.
6. Decisions: plan flyers included vs 30 credits each; hashtags in business captions; TikTok/YouTube ungated (recommended); free composer flyer for the Starter suggestion (recommended); v1 tells the owner by push + Today (no owner-text helper found).

## Not verified

Social migrations live in production and the pilot value; `chief_notifications.type`
values; host/custom-domain resolution in `public_site` for `/go/`;
`compute_slots` `concurrent_capacity` and `module_entries` offering fields; a
store for barbers' work photos (none found → `work_photo_ids`); a reviews
table (none found); Post for Me rate limits and lookup by `external_id`; the
platform business's plan and how a no-card trial resolves in `plan_of`.
