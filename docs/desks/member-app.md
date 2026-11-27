# Desk: member-app

## 1. What it owns

The church members' phone app at `<church site>/my` (a church's own domain or
`<slug>.mysolutionist.app`). A member signs in with a 6-digit code (no
password), then uses five tabs: Home · Watch · Connect · Bible · Give, plus a
top bar with Messages, the alerts bell and their profile. Inside: the feed and
posts, moments, prayer, events, groups and group chats, messages that read like
texts, the Bible and reading plans, devotionals, classes, My serving, kids
(parents and leaders), Meet the pastor, "I'm new here", Ask the church, the
member directory, and their own giving and statements. The current look is
"Lumen" (serif headings, the church colour as the accent, light or dark per
member). The office side of the app's set-up (Settings → Member page: colour,
pictures, fonts, icon, tabs, notifications) is also this desk.

It is server-rendered HTML from the backend, NOT the React app. There is no
JWT here: the member is a contact, not a Supabase user.

## 2. Where the code is

Backend (`kmj-intake-server`):
- `member_portal.py`: the core. Sign-in codes, the `__Host-` session cookie,
  `_church_for_request` (host → church), `_session_for`, `_same_origin`,
  `_shell` / `_lumen_frame`, the owner config routes
  `/member-portal/{business_id}` (GET/PATCH, `_require_owner`). GET `/my/*` is
  served from `public_site.py`'s subdomain catch-all; the POST routers are
  mounted in `kmj_intake_automation.py` BEFORE `public_site_router`.
- `member_portal_*.py`: one module per area (threads, groups, news, share,
  serving, checks, board, write, classes, lead, leading, assign, dates, safety,
  checkin, live, group_live, messaging, gifts, reading, devotionals, bible,
  celebrations, church, sermons, preview, lumen).
- `member_lumen.py`: the Lumen switch (`visible`, `here`). `member_lumen_*.py`:
  the Lumen pages (home, feed, watch, connect, bible, plans, give, moments,
  motion, stories, share, look, fonts, ui). `member_lumen_ui.py` holds the
  sheet; `member_app_ui.py` holds the shared CSS, `sheet()`, `palette`, `nav`.
- `member_app_*.py`: install (manifest + `sw.js`), icon, signin, photos,
  pictures, samples. Other `member_*.py`: posts, moments, pastor, push, alerts,
  cache, stopwatch, mini (mini player), directory, asks, im_new, instant_send,
  join, spaces / spaces_kids, plan_prefs, bible_marks, messaging_rules.
- Shared with others: `msg_screen.py` (screens member posts and messages with
  a paid model call), `member_messaging_rules.py` (who may message whom, pure
  rules), `news_approvers.py`, `news_share.py`, `church_news.py`.
- Tables: `contacts` (the member, plus `metadata` keys such as `member_look`,
  `member_saved`, `member_birthdate`, `new_here`), `member_login_codes`,
  `member_push_prefs` / `_sends` / `_held` / `_subscriptions`, `msg_members`,
  `member_plan_starts`, `member_anniversaries`, `church_posts`,
  `church_moments` / `church_moment_marks`, `church_thread_notes`.
  Migrations: `supabase/APPLY-*member*`, `*church-moments*`, `*church-threads*`.
- Settings: `businesses.settings.member_portal` (enabled, epoch, base, tiles,
  fonts, theme accent, member_posts, pastor_note).

Frontend (`solutionist-studio`), the office set-up only:
- `src/core/components/MemberPortalPanel.tsx`, `Member*Section.tsx`
  (AppColour, Fonts, Icon, Notifications, Pictures, Spaces, Tabs),
  `memberColour.ts`, `memberFonts.ts`, `memberTabs.ts`, `memberTabsRollout.ts`.
- Office pages about members: `src/core/components/church/MemberAsksOffice.tsx`,
  `MemberDirectoryOffice.tsx`, `NewsPanel.tsx`, `NewsShared.tsx`.

## 3. Rules that must not break

- Every new look or behaviour ships behind a switch, and with the switch off
  the pages are byte-identical to before (that is how every Lumen PR was
  checked). Switches: `MEMBER_LUMEN` (off|preview|owner|on; now on),
  `MEMBER_MINI_PLAYER`, `MEMBER_CACHE`, `MEMBER_APP_FAST`,
  `MEMBER_INSTANT_SEND`, `MEMBER_IM_NEW`, `MEMBER_ALERTS_LIST`,
  `MEMBER_ALERTS_DEFAULTS`. Unknown values read as off; a failed read is a no.
- Features switch on on Thursdays unless the owner says otherwise.
- Sign-in never says whether an address is on the list (same page, same
  timing, one failure message). One person per email. Code limits use
  `rate_limit.allow_strict`, which fails CLOSED, unlike the AI guards.
- Every POST refuses a cross-site Origin (`_same_origin`); `Origin: null` only
  with `Sec-Fetch-Site: same-origin`. Keep `Referrer-Policy: same-origin`.
- A session for one church never opens another's (keys derived per business).
- Child safety: messaging needs a birthdate on the OFFICE's record plus the
  church's switch; a birthday typed in the app unlocks posting only, under 13
  is refused, and the office's birthdate wins. Teen rules live only in
  `member_messaging_rules.py`. Prayer requests never appear in the feed.
- Posts, comments and messages go through `msg_screen` before anyone else
  sees them; flagged items go to the safety officers.
- A sample church has no reachable member app; only the owner's preview opens
  it, and no code is ever sent.
- Several web replicas: no per-process state that must agree between
  requests. `member_cache` keeps rows 30-60 s and never keeps a failed read.
- Design changes: a mock first and the owner's go-ahead (artifact first).

## 4. Traps already hit

- `Referrer-Policy: no-referrer` made every real form POST send `Origin: null`;
  sign-in was broken for two weeks while TestClient tests passed.
- Lumen CSS must go in `member_lumen_ui.templates()` (feeds `sheet("lumen")`),
  not only in `css()`, or it never reaches the page.
- Headless Chromium never paints after a cross-document view transition: set
  reduced motion in screenshot tests.
- Playwright `page.route` misses POSTs once the `/my` service worker controls
  the page: use `service_workers="block"`.
- `member_app_photos.photos()` caps at 24 alphabetically; look a named photo
  up with `photos.named()`.
- A new business-scoped table fails the export/delete coverage test until it
  is in `account_lifecycle.BUSINESS_CHILD_TABLES` (or excluded).
- A test file setting `SUPABASE_URL` at module level switches on live checks in
  CI; use `monkeypatch.setenv` per test.
- Railway's Python is unpinned (CI is 3.12): no backslashes inside f-string
  braces.
- Tests that read the real clock broke every PR for a day (serving links).
- "Sign everyone out" and switching the app off take up to a minute on other
  server copies; the owner accepted that, don't build instant clearing.
- A church that never picked a base reads as Black, so most members start dark.
- `test_sunday_planning_holds`' byte-for-byte check is skipped in CI's clone;
  run it locally.
- Instant send: a retry during the first send's screen can still save twice.

## 5. How to check work

- `pytest -q __tests__/test_member_*.py __tests__/test_msg_screen.py
  __tests__/test_news_*.py __tests__/test_kids_*.py`; the switch itself is
  `__tests__/test_member_lumen.py`, pages and read counts
  `test_member_lumen_pages.py`, speed `test_member_portal_speed.py` and
  `test_member_stopwatch.py`.
- Migration checks on real Postgres (PGlite), e.g.
  `PGLITE_MODULE=... node __tests__/church_moments_db.mjs`,
  `member_plan_prefs_db.mjs`, `member_safety_officers_db.mjs`.
- Switch-off proof: render the touched pages with the switch off on main and
  on your branch and diff them byte for byte (no committed harness; build one
  over the test fakes). Compare read counts and the `Server-Timing` header
  (`member_stopwatch`).
- Real browser for any form or Origin change: Playwright with service workers
  blocked, light and dark, a phone viewport.
- Live: the owner's "Preview as a member" (`/my/preview`, via
  `member_portal_preview.py`) at the owner's church.
- Frontend set-up pages: `npx vite --config tests/member-page.vite.config.ts`
  then `/tests/member-page-preview.html`; `node scripts/check-member-tabs.mjs`,
  `check-member-asks.mjs`, `check-member-directory.mjs`;
  `npx tsc -p tsconfig.app.json --noEmit` (no new errors), `npx vite build`.

## 6. Edges

- messaging: push delivery, SMS/email, `church_threads.py` (the office side of
  "From your church"). This desk owns `member_push.py`'s member choices and
  the app's pages; messaging owns sending.
- church-office: the data members see (roll, groups, Serve, classes, kids
  check-in, care, news approvals). The office module is theirs; the `/my` page
  for it is ours. `member_portal_serving.py` / `member_serving_approve.py`
  sit on their Serve data.
- money: Give and statements (`member_portal_gifts.py`, `member_lumen_give.py`)
  sit on giving and Stripe; money owns payments and figures.
- live-media: Watch, live and the mini player (`member_portal_live.py`,
  `member_lumen_watch.py`, `member_mini.py`) sit on streams and recordings.
- websites: `public_site.py` routes `/my`; the site's host lookup and custom
  domains are theirs. Never move member POST routers after the catch-all.
- chief: Chief's member-facing actions live in `chief_*` modules; this desk
  owns the pages they link to.
