# Get Love City off Subsplash: plan and handoff

**Goal (Kevin, 2026-10-14):** "getting off subsplash is the goal." Love City Church cancels Subsplash with nothing lost, running entirely on the Solutionist System.

**Who this is for:** the agent taking over. Kevin will manage it from his phone.

**Visual version:** "Beyond Subsplash," https://claude.ai/artifact/QaiVkaJEBynKE3YB7SBMbq. It is private to Kevin and has a Listen bar.

**Researched against:** backend `main` 61248292 and frontend `module-system` e5b9b07, on 2026-10-14. Re-check anything marked as a gap before building it, because other agents ship daily.

---

## 0. Progress (first session, 2026-10-14)

**Step 0 facts (Kevin, from the Dev Desk):**
- The contract renews at the start of the year. It auto-renews and is billed month to month.
- Love City uses "pretty much all" Subsplash products.
- 20–30 people give every month. The Subsplash read below shows they give by hand each time; none has a recurring gift.
- No podcast feed, so the feed move is dropped.

**Read from Love City's Subsplash dashboard (2026-10-14, signed in as the church, read only; Kevin's go-ahead from the Dev Desk):**
- **Contract renews December 30, 2026** (Settings → Subscription). Subsplash's help page says to cancel through the Client Success Manager "at least 30 days prior to the renewal date", so the **written notice must land by Nov 30, 2026**. Plan to send it mid-November.
- **Cost:** "Giving + Subsplash One 250" at $263.89 a month, charged on the last day of each month, plus Pulpit AI Standard at $53.10 a month, billed separately. About $317 a month, or $3,800 a year.
- **Giving, Jan 1 – Oct 14, 2026:** 733 gifts, $35,882.59 gross, 119 givers.

  | Method | Gifts | Gross | Fees |
  |---|---|---|---|
  | Card | 287 | $16,731.23 | $551.65 (3.3%) |
  | ACH | 3 | $124.24 | $1.24 |
  | Cash | 151 | $5,407.56 | $0 |
  | Check | 35 | $3,262.00 | $0 |
  | Other (PayPal, Zelle, Cash App) | 224 | $8,912.70 | $0 |
  | Remainder (non-deductible kinds) | 33 | about $1,445 | |

  Over half of the money is entered by hand. Staff record cash, check and app gifts in Subsplash, some under a "Loose cash" donor. Online processing is only about $1,800 a month.
- **Fees Love City actually pays: 2.99% + 30¢ per Visa/Mastercard gift**, checked against real gifts (a $103.39 gift paid $3.39), and 1% on ACH. That is Subsplash's **non-exclusive** tier (support article 9101519). The 2.30% tier needs an Exclusive Partnership agreement, so Love City has no exclusivity clause holding its giving. Nearly every card giver ticks "cover the fee" (18 of the last 19), so givers, not the church, pay most of the $552.
- **Recurring: 0 active.** Only 11 recurring gifts have ever existed, all canceled, the last in March 2026. **Nobody has a gift to re-create**, so the move campaign becomes "give here now". Statements also need the hand-entered gifts, so the importer must carry every method, not just card.
- **Last 30 days:** 20 gifts from 13 givers, $964.20.
- **Funds:** Tithes, Offering, Building Fund.
- **People:** 590, plus 31 possible duplicates flagged by Subsplash. The people list has an Export button.
- **Media:** 469 items in 54 series, 886 GB of 977 GB used (807 GB video, 79 GB audio). Hosting that much video ourselves is not the plan; sermons come from YouTube or Facebook links (D4).
- **The Subsplash app:** 1,108 downloads, 35,228 launches and 119,345 page views, all time. Members will lose a store app that gets real use, so the installable member page (step 3) needs an announcement plan.
- **Not yet downloaded:** the people and 2026 gifts exports. Downloading members' data to the laptop is Kevin's yes. He was asked on 2026-10-14.

**Found:** Love City's Solutionist workspace is empty. It has no Stripe connected, giving is off, 0 people, no texting number and no member page turned on. Steps 2 and 7 wait on that setup.

**Helcim as a church-only second processor (Kevin asked, 2026-10-14). Advice: no, not now.**
- **Price:** Helcim is interchange plus 0.50% + 25¢ online. Its Recurring add-on is +0.4%, and ACH is 0.5% + 25¢ capped at $6. On Love City's roughly $1,800 a month of card gifts that saves about $5 a month over Stripe's standard 2.9% + 30¢. Stripe's nonprofit rate (about 2.2% + 30¢, for 80%+ donation volume and tax-exempt documents) saves more.
- **Build:** `payments_core.py` already has the per-business adapter seam (`provider_for`), so it's possible. A Helcim adapter would still need all of this, about 2–3 weeks to reach parity, plus a second processor to run for good:
  - partner-token signup and the `connectedAccount` webhook that delivers each church's API token, with encrypted token storage
  - HelcimPay.js on `/give`
  - our own weekly/biweekly scheduling
  - a poller, because only `cardTransaction` webhooks are documented (no subscription, ACH settlement or return events)
  - a replacement for `/my/gifts`
  - refunds
  - processor-aware fee math (`covered_fee_cents` hardcodes 2.9% + 30¢)
- **Risks:**
  - no sandbox for partner signup
  - no per-transaction platform fee, only an undisclosed revenue share
  - the acceptable use policy bars "unregistered charities", which is ambiguous for churches
  - reviews mention held funds and sudden closures
- **Better levers:**
  - Love City applies for Stripe's nonprofit rate.
  - Nudge bank giving: $1.20 vs $4.65 on a $150 gift.
  - Revisit Helcim if church volume reaches $100k+ a month.

**How Subsplash does giving (Kevin asked about a "treasury account").** Subsplash's Transfers page says: "Subsplash partners with Stripe Payments Company for money transmission and account services with funds held at Fifth Third Bank." Subsplash runs every church on Stripe under its own name and holds the gifts. That is why a church never sees Stripe, and why Subsplash carries the compliance load. Solutionist gives the same on-screen experience with #1428–#1430, but the church owns its own Stripe account and gets paid straight to its bank. Stripe Treasury was advised against: platform KYC, liability for losses, and Stripe-approved marketing.

**Shipped (backend PRs; frontend in brackets):**

| Step | What | PRs |
|---|---|---|
| 1 | First-time guests nobody has reached: `church_reads`, `GET /church/first-time-guests`, ministry layout provider; Home's care list puts them first | #1413 [FE #1216] |
| 1 | Care inbox acts: reviewed/closed, prayed, private notes (`ministry_care_notes`) | #1414 |
| 1 | A prayer request can be handed to a teammate, who sees only that one (Kevin: "others should be able to see prayer request") | #1417 [FE #1217] |
| 1 | Chief reads the church: `church_people` (first_time / groups / attendance / care counts, care owner-or-manager only) | #1416 |
| 1 | Marketing FAQ no longer says churches aren't the right fit | #1415 |
| 1 | Site forms → Care: Codex's #1409. Follow-up review posted on the PR (one must-fix: plain-form name/email/phone stored up to 100k chars) | #1409 (not mine) |
| 2 | Gift webhooks only record gifts from the church's own Stripe account | #1418 |
| 2 | Weekly / every-2-weeks giving and "cover the processing fee" | #1419 |
| 2 | Text GIVE (also GIVING, TITHE, DONATE, OFFERING) to the church's own number → its give page | #1420 |
| 2 | A give link fills the page in (`?amount=&frequency=&fund=&cover_fee=1`), for each recurring giver's move link | #1425 |
| 2 | Email every giver their year-end statement (`giving_statement_sends`, finance seats, explicit confirm) | #1421 [FE branch `statements-email-ui`, opens after #1421 deploys] |
| 2 | Givers change, pause or stop their own recurring gift and update the card (`/my/gifts`) | #1424 |
| 2 | Givers pay on the church's give page itself: embedded Checkout on the church's account, with a redirect fallback (Kevin: "can we embed stripe so people don't have to leave the system?") | #1428 |
| 2 | Apple Pay / Google Pay inside that form: Payment Method Domains registered on the church's account when giving is turned on, plus Apple's association file on every site | #1429 |
| 2 | A church signs up for Stripe inside Solutionist: Operate → Payments → "Set up Stripe here" creates its own full Stripe account (Standard-equivalent, no platform liability) and Stripe's form runs in the app | #1430 [FE #1220] |
| 3 | The member page installs like an app: manifest, icons, service worker (no push), install card | #1422 |
| 6 | Bible reading plans: 4 computed plans, Home card, `/my/reading`, staff choose in Settings | #1423 [FE #1218] |

**Migrations applied 2026-10-14** (all in `docs/MIGRATIONS.md`): care-inbox-actions, care-assign, giving-statement-sends, reading-progress. The church tables from 9/29–10/02 were verified live and recorded.

**Waiting on Kevin:**
1. Love City's Stripe. Online giving and statements need one connected. A church with no Stripe account now sets one up in Operate → Payments → "Set up Stripe here", signed in as the church. That needs the church's EIN, bank and a leader's ID, so the church does it, not an agent. Then turn giving on in Operate → Giving, which also registers the wallet domains. `STRIPE_PUBLISHABLE_KEY` was already set in Railway (live), so the embedded form and the in-app signup work as soon as an account exists.
2. Yes to downloading two Subsplash exports to the laptop: the people list (590) and the 2026 gifts (733). They feed the D3 importer, which isn't built yet because the export format is unseen. The recurring givers list is empty, so it isn't needed.
3. Open decision 1 (member notifications) gates push in step 3.
4. A texting number of Love City's own (a paid line) for text GIVE and member texts.

**Still to build:**
- the giving-history importer (D3, after a sample export). It carries every method (card, ACH, cash, check, other) and the funds, so statements are whole.
- the "give here now" campaign to the 119 givers of 2026, with no recurring gifts to re-create. It sends from the church's own email and number, using #1425 links, and tracks who gave on the new page. Every send is Kevin's yes.
- nothing new for hand entry: staff record cash, check and other gifts through the existing `POST /giving/{business_id}/records` (methods cash/check/bank_transfer/other). Over half of Love City's giving arrives that way, so show the church this on day one.
- sermon import (Love City's YouTube or Facebook, not scraping Subsplash) and audio upload (D4)
- push (after decision 1)
- prayer from live chat into Care (step 5)
- swap the four `LINKS` in `sites/love-city-church/build.py` once giving is live

**Found along the way, not fixed:** booking, order, invoice and product checkouts trust `metadata` without checking the Connect account, the same gap #1418 closed for gifts. It needs its own careful PR.

---

## 1. Read this first

**What Love City uses Subsplash for.** Love City pays for several Subsplash products:
- **The website.** The old site runs on SnapPages, which is Subsplash's website builder.
- **The member app.** "LCC" is in the app stores, with tabs Home, Messages, Bible, Give and On Demand.
- **Giving.** The new site still embeds Subsplash Give.
- **The sermon library.** "Love Nation TV" on Subsplash media.

Cancelling means replacing all of these.

**The website move is already in flight as KAI's milestone M-1.** Don't duplicate it; build on it.
- PR #1408 (hand-built site, 10 pages) is merged.
- PR #1411 (photos) is merged.
- PR #1409 (church forms back end, by Codex) is open.
- PR #1410 (old SnapPages URLs redirect) is open.
- The domain cut-over runbook is at `C:\Users\kmccl\AppData\Roaming\solution-space\kai\reviews\M-1-step8-domain-runbook.md`. That path is on Kevin's laptop.
- History lives in the backend repo's memory notes `love-city-site-arc` and `custom-domain-cutover-facts`.

**Kevin's settled church decisions** are recorded in the KAI memory vault: `C:\Users\kmccl\.claude\projects\C--Users-kmccl-solutionist-studio-solutionist-studio\memory\project_church_experience_plan.md`. Section 6 below summarizes them. Don't re-ask them.

**Working with Kevin from his phone:**
- Report outcomes in a few plain sentences.
- Ask one question at a time, with your recommendation first.
- Lead with one concrete example rather than a ranked list.
- Kevin approves merging on green. Follow the look-before-merge checks in section 7.

---

## 2. Definition of done

Love City can cancel when every line below is true:

| # | Done when | Status 2026-10-14 |
|---|---|---|
| D1 | lovecityc.com is served by Solutionist (M-1). | In flight: #1409, #1410, then the domain cut-over |
| D2 | All online giving runs through Love City's own Stripe via Solutionist. The site's give links point to `/give`. Every recurring giver has moved. | Partly: one-time and monthly giving work; parity gaps in step 2 |
| D3 | Giving history from Subsplash is imported, so 2026 year-end statements are whole. | Not started |
| D4 | The sermon archive is on Solutionist, new sermons are published here, and the site's sermon links point to `/sermons`. | Partly: library exists; no import, audio upload or podcast feed |
| D5 | Members use the Solutionist member app (`/my`), installed on their phones, with notifications. The LCC store app is retired. | Not yet: no install, no push |
| D6 | Prayer, groups, events, live and a Bible reading plan all work in our app. | Partly: groups, events and live are ready; prayer is partly done; no reading plans |
| D7 | Everything is exported from Subsplash and the cancellation is sent in writing before the renewal date. | Not started; needs the facts in step 0 |

`sites/love-city-church/build.py` `LINKS` still holds `SUBSPLASH_GIVE`, `SUBSPLASH_GIVE_PAGE`, `SUBSPLASH_LATEST` and `SERMON_LIBRARY`, all pointing at subsplash.com. Swapping them is part of D2 and D4.

---

## 3. The plan, in order

### Step 0: Facts only Kevin has (ask him first)

These block steps 2, 4 and 7:
1. **Love City's Subsplash renewal date and contract.** Their Terms v4.0 (2026-07-27) say:
   - Contracts run 1–2 years and renew yearly.
   - Cancellation must be in writing at least 30 days before renewal.
   - Leaving early requires a call with their success manager and costs up to 3× the monthly fee.
   - Data can be downloaded for 30 days after termination.

   The renewal date sets the deadline.
2. **Which Subsplash products Love City pays for.** App, website, giving, media, groups, podcast? Kevin's dashboard is at dashboard.subsplash.com → billing.
3. **How many recurring givers there are, and roughly how much a month.**
4. **Whether Love City has a podcast listed in Apple or Spotify** fed by Subsplash. If it does, the feed has to be moved without losing subscribers.

### Step 1: Fix what's broken, and let Chief see the church

These are small, and every later step uses them.
- **The first-time guest panel is always empty.**
  - `workspace_layouts/ministry.json:84`: the panel "Came once, nobody has called" filters `contacts.status = "first_time"`. Nothing ever sets that value. Verified: no code writes it.
  - Fix: drive the panel from `attendance.first_time` plus "no contact since".
- **The Care inbox only reads.**
  - `intake_endpoint.py:766` serves `GET /intake/private-care/{biz}` and nothing else, so `ministry_care_requests.status` never moves off "new".
  - Add a status change (new → reviewed → closed), assignment, a "prayed" mark and private pastor notes. Owner or manager only, written as the service (see `rls-swallows-server-writes`).
- **Site prayer and connect forms bypass Care.** Love City's `forms.js` posts to `/sites/{biz}/contact-submit`. Coordinate with Codex's #1409 (church forms back end, prayer kept private) rather than building a second path.
- **The marketing FAQ says we aren't ready for churches.** `marketing_pages.py`, under "Does it work for churches and ministries?", says: "If you need full church membership tools, we're not the right fit yet." Rewrite it.
- **Chief can't see church records.**
  - Chief reads `sermons` and the giving statement verbs only. It reads no `attendance`, `groups`/`group_members`/`group_meetings`, `households`/`children`/`child_checkins`, `ministry_care_requests`, `live_sessions`/`live_presence`, or messaging tables.
  - Add read-only context or tools so Chief can answer "who came for the first time", "who's drifting from their group" and "how many were online".
  - Children's and care data are sensitive: owner or manager only, with no child details in drafts.

### Step 2: Giving parity

Today, gifts are a direct charge on Love City's own Stripe Standard Connect account with no platform fee. The pieces:
- `giving_router.py`
- `stripe_connect_router.py`, whose webhook already handles `checkout.session.async_payment_succeeded`
- gifts stored as `invoices` rows with `is_gift` and `gift_fund`
- `giving_statements.py`
- the member's `/my/me` and `/my/statement`

What to add:
- **Givers manage their own recurring gift** in `/my`: change the amount or card, pause, cancel. A Stripe Billing Portal session on the connected account is the shortest path.
- **Frequency:** weekly, every two weeks and monthly (monthly is the only option today).
- **A "cover the fee" box** that adds the estimated Stripe fee to the gift.
- **Bank transfer (ACH)**, offered deliberately. Stripe charges 0.8% capped at $5; Subsplash charges 1% with no cap. Confirm receipts wait for the async success event.
- **Text GIVE to the church's own number.**
  - `sms_routing.route_inbound` already routes a text sent to a business's own number, and has keyword binding.
  - Reply with the `/give` link. Never use a shared number.
- **Email year-end statements in bulk**, before January 31. Statements are plain text today; consider a per-giver PDF.
- **Import giving history** from Subsplash's export into `invoices` (`is_gift`), audited in `ministry_gift_history`, so statements cover the whole year. This is also D3.
- **Moving recurring givers.** Card details can't be assumed to transfer from Subsplash's processor. Plan a church-signed email and text inviting each recurring giver to set the gift up again, with a per-giver link. Track who has moved.

### Step 3: An app members can install, with notifications

> **Needs Kevin's yes on member notifications first.** As of 10/04 he had approved sign-in codes only. Notifications to members were recorded as "a separate, unapproved question."

- Add a web app manifest, icons from the church's brand, and a service worker scoped to `/my`. Right now `member_app_ui.py` has only a `theme-color` meta tag.
- Add web push for members.
  - The existing `push_notifications.py` and `push_subscriptions` serve staff only, keyed on `user_id`, so members need their own subscription table keyed on contact plus business.
  - On iPhone, push works only once the app has been added to the home screen.
- First notifications: live now, new sermon, group message (`member_portal_messaging.py:23` says "No notifications yet"), and event reminder.
- Add an "Install the app" prompt on `/my` Home, with iPhone instructions.
- Store apps (Capacitor) under the church's own developer accounts come later, in wave 3.

### Step 4: Sermons move home

Today, `sermons` and `sermon_series` hold links only: YouTube, Vimeo, Facebook, Loom, or an audio URL. The pieces are `sermons_public.py` and FE `church/SermonsPanel.tsx`.
- **Import Love City's Subsplash media library** (titles, dates, video and audio links, series). Their titles are raw service names like "Love City Experience//11:00am//09.27.26", so clean them into speaker, date and series. Read Subsplash's export or public media pages; don't scrape what we're not allowed to.
- **Audio upload and storage**, plus **series artwork upload**. Posters are generated today.
- **A podcast RSS feed** per church. If Love City has a Subsplash podcast (step 0), plan the move with a redirect from the old feed, if Subsplash supports one, or the `itunes:new-feed-url` tag.
- **Keep video on YouTube or Facebook.** Hosting video ourselves adds cost with no reason; the branded player stays a planned paid add-on.
- After this, swap `SUBSPLASH_LATEST` and `SERMON_LIBRARY` in `sites/love-city-church/build.py`.

### Step 5: Prayer and Care

Builds on step 1 and #1409:
- Every prayer source lands in Care: member app, site form, live chat prayer, and crisis messages.
- Staff can mark a request, assign it, record "prayed", and keep notes.
- An optional prayer wall waits on Kevin (open decision 3).

### Step 6: Bible reading plans

This was already next on the church plan (Bible part 2). The current pieces are `bible_text.py` (KJV and WEB) and `member_portal_bible.py`.
- The team picks a plan and a start date.
- "Today's reading" appears on `/my` Home.
- Progress needs a table; today only a cookie holds the reader's place.
- The Subsplash LCC app's dated reading plan was one of its best parts in the 9/30 walkthrough.

### Step 7: The switch

1. Export everything from Subsplash: people, giving history, recurring giver list, media and forms.
2. Import the giving history (step 2).
3. Send the recurring-giver move campaign. Track it until everyone has moved, or Kevin calls it.
4. Swap all four Subsplash links in `build.py` and redeploy the site.
5. Announce the new app to members: a sign-in link and install instructions, by email and text from Love City's own number.
6. Send the cancellation in writing at least 30 days before renewal.
7. Confirm the export downloaded before the 30-day window closes.

Every send in this step is Kevin's yes. Nothing goes to members without it.

### After the switch: wave 2

- **The sermon week pack.** Transcript, recap email, group guide, and 5 days of devotionals that become the reading plan. Clips (`clip_finder.py`) and covers (`clip_covers.py`) already exist. This is the answer to Pulpit AI, which costs $39–129 a month.
- **The pastor's Monday brief.** First-time families nobody has called, who's drifting from groups, giving against last year, open Care requests, volunteer gaps.
- **Volunteer scheduling.** Ask, accept or decline, dates people can't serve, a reminder the day before, and Chief suggesting who to ask.
- **Events.** Paid registration through the church's Stripe, a waitlist, repeating events, reminders, and add-to-calendar (.ics).
- **People.** A membership path (Visitor → Regular → Member, with dates), first visit and visit count, custom fields and notes.
- **Messages by group, event or household**, plus a weekly bulletin email that Chief drafts.
- **Kids.** QR pre-check-in from the member app, photos, room limits, paging parents, and grade promotion.

### Wave 3: when paying churches ask

- Store apps: Apple $99 a year and Google $25 once, per church.
- Pledges and campaigns tied to real gifts.
- Tap/NFC tags and a giving kiosk mode on the station.
- Stock gifts and check scanning.
- Fund balances and releasing restricted funds.
- Background-check partners.
- Multi-campus.
- Licensed Bible translations (fees; Kevin's call).
- TV apps.

**Don't copy:**
- Contracts, exit fees or exclusivity deals.
- Running our own streaming CDN.
- A kanban board staff have to babysit.
- Dashboards sold with consultants.
- A shared text-to-give number.
- A licensed video library.

---

## 4. Where we win (the pitch, once Love City is off)

1. **Chief does the follow-up.** Subsplash's Workflows (GA July 2026) is a board staff move by hand.
2. **The sermon week pack is included** and feeds the app's reading plan and group chats.
3. **A Monday brief instead of dashboards.** Trends AI comes with paid consulting.
4. **The church's own number, both ways.**
   - Subsplash texts from a fixed number that adds "(via Subsplash)".
   - Replies to Subsplash texts arrive as email.
   - Its text-to-give runs on the shared number 1-888-364-GIVE.
5. **Safety:**
   - teen messaging rules
   - two safety officers
   - crisis routing (988 plus the pastor)
   - pickup that respects custody notes
6. **Sites at the 2819 level.** Reviewers call Subsplash's SnapPages "the weakest link in the chain."
7. **Terms people trust:**
   - a published price
   - month to month, cancel in the app
   - export any time
   - the church's own Stripe and payout schedule (Subsplash pays weekly, on Wednesdays)
   - app listings under the church's own name

---

## 5. Open decisions for Kevin

1. **Notifications to members:** push, and texts beyond sign-in codes. Step 3 needs this. *Recommendation: yes. Members can turn each kind off, and nothing goes out on the church's behalf without the church's switch.*
2. **Is the sermon week pack included in the church plan, or a paid add-on?** *Recommendation: included.*
3. **A prayer wall?** *Recommendation: members only, first names, and staff approve each one.*
4. **A member directory?** Kevin said no in v1. *Recommendation: opt-in, in wave 2.*
5. **Publish a church price on the website?** *Recommendation: yes, with month to month in big letters.*
6. **2026 year-end statements:** import Subsplash history and send one statement from Solutionist? *Recommendation: yes.*

Already decided 2026-10-14: getting off Subsplash is the goal. Others on the team should be able to see prayer requests (built as: the owner hands a request to a teammate, who then sees that one).

---

## 6. Settled church decisions (summary; source is the KAI vault file named in section 1)

**The church edition and design**
- Churches get a "Solutionist for Churches" edition on the same system, not a separate platform.
- Design is "Bulletin" plus faces. The member app uses the Broadcast look, tinted dark from each church's brand.
- Use church words throughout: Members, Giving, Serving, Care.
- Phone parity in the same pass.

**Member app and sign-in**
- Sign-in is passwordless: a 6-digit code by email or text.
- One person per email.
- Sign-in messages were approved 10/04, and the sign-in switch shipped.
- No member directory in v1.
- Tabs: Home · Sermons · Bible · Groups · Live; Me is the avatar; Give is always one tap away.

**Messaging**
- Teens need a birthdate on file plus the church's switch.
- Teens can DM only their linked parents and other teens.
- Parents can read all of their teen's chats.
- A group chat that includes a teen needs two approved adults.
- Messages are kept for one year by default; the church can change that.
- Messages are AI-screened.
- At least two safety officers are required.

**Live and group video**
- Live: embed YouTube or Facebook (video only) with our chat. Prayer goes privately to Care. "I'm here" counts as online attendance.
- Group live runs on LiveKit, granted per leader. Youth groups need two adults. Staff can drop in.

**Kids**
- Pickup security uses both a texted code and printed tags.
- Stations: PIN staff mode and a family self kiosk.
- Children are not contacts.

**Bible:** KJV and WEB now. Reading plans come next. Licensed translations later (Kevin's call).

---

## 7. Working rules for this repo and the frontend

- **Repos:**
  - Backend: `C:\Users\kmccl\kmj-intake-server`, trunk `main`. Merging deploys to Railway.
  - Frontend: `C:\Users\kmccl\solutionist-studio\solutionist-studio`, trunk `module-system`.
  - Read both CLAUDE.md files.
- **PRs:**
  - One PR per change; never stack them.
  - Backend first, then frontend after the deploy.
  - Work in a worktree branched from the trunk. Never `git stash`; other sessions share the stash.
- **Migrations:** ship as `supabase/APPLY-YYYY-MM-DD-*.sql` and get added to `docs/MIGRATIONS.md`. The church tables from 9/29–10/02 are applied in production but missing from that ledger; add them when you touch it.
- **Server writes** use the service role (`sb_clients.sb_*_as_service`). Every write endpoint needs `require_user` plus an owner check.
- **Before every merge:**
  - no Railway deploy in flight;
  - nothing landed on main in the last 15 minutes;
  - no other agent's ready PR is waiting;
  - no paid build running.
  - Kevin's standing approval: merge on green.
- **Live evals bill production's Anthropic key.** State the cost before running one.
- **Practitioner-facing copy** never mentions GitHub, Claude Code or builders.

---

## Appendix A: Subsplash teardown (research notes, 2026-10-14)

**Sources and caveats**
- Read directly: subsplash.com tabs, /pricing, /compare, Terms v4.0, the Exclusive Guarantee, about 25 support.subsplash.com articles, the changelog (subsplash.canny.io), Roper's 2025 filings, pulpitai.com/pricing and Trustpilot.
- G2, Capterra and Reddit blocked direct reading, so their quotes come from search snippets.
- Items marked *unconfirmed* could not be verified.

**Company**
- Roper Technologies bought Subsplash for about **$800M**, agreed 2025-07-21.
- The seller was K1.
- Founder and CEO Tim Turner stayed.
- It claims 20k+ churches, 300+ staff, about 100M app downloads and 24M donors.
- Earlier acquisitions: SnapPages (websites, 2018), Custom Church Apps (2019), StreamSpot (streaming, 2020) and **Pulpit AI** (December 2024).
- The church-management software appears to be built in-house; its old version is now labeled "Legacy."

**Navigation (the products menu)**
- Subsplash One, Apps, Giving, Media, Websites, Church management, Groups & Messaging, Events, Workflows, Live streaming, Pulpit AI, Trends AI, Tap.
- Use cases: church plants, growing (100–500), large (500–1,500), mega (2,000+), ministries, enterprise.
- Several product pages still showed lorem ipsum on 2026-10-14.

### Products

**Subsplash One**
- A quote-only bundle claimed to replace 6–10 tools.
- Add-ons: Pulpit AI, Trends AI, car apps, Giving Pro (check scanning and daily deposits), Tap, API, Rock RMS, multi-campus.

**Apps**
- Platforms: custom iOS, Android and tablet apps; Apple TV, Roku, Fire TV and Google TV; CarPlay and Android Auto. Subsplash submits them to the stores.
- Media: an ad-free player with AirPlay and Chromecast, offline play, "continue playing" and recommendations.
- Giving in the app: saved payment methods and pledge progress.
- Push: scheduled, multi-group, and automatic for live.
- Also: fill-in sermon notes, volunteer accept/decline, and phone-number sign-in (November 2025).
- Bible: an audio Bible, reading plans (built-in and custom), and scripture tagging that shows sermons next to a passage.
- A premium content library: The Chosen, BibleProject, Ligonier and others (price *unconfirmed*).

**Giving**
- Payment methods: card, ACH with instant bank verification, Apple Pay, Google Pay.
- Text-to-give is free and runs on the shared number 1-888-364-GIVE with keywords; setup takes 3–5 days.
- Kiosk giving is only a browser link that logs out after 30 seconds; there's no card reader.
- Guest giving without an account.
- Recurring gifts weekly, every two weeks or monthly. They pause after 3 failures (September 2026).
- Funds and sub-funds, split gifts, campaigns and pledges, donor-covered fees.
- Stock and crypto via Engiven, free since November 2025.
- DAF, QCD and in-kind gifts.
- Cash and check entry, and bulk check scanning (Giving Pro).
- Household tax statements, bulk import of history, and help migrating donors.
- **Payouts are weekly, on Wednesdays**; daily payouts need Giving Pro.
- **There's no real QuickBooks connection**; the help article says to reconcile by hand.
- Runs on Stripe (Subsplash Wallet LLC).

**Media**
- Upload once and publish to the app, the site, the podcast (Apple, Spotify) and TV.
- Unlimited hosting.
- Tags for speaker, topic and scripture.
- Embeds, unlisted items, analytics, and timestamped share links (September 2026).
- They also pitch it on avoiding YouTube takedowns.

**Live streaming**
- Built on StreamSpot.
- SRT or RTMP from any encoder.
- Simulcast to YouTube and Facebook, and simulated live.
- Chat, giving prompts and countdowns.
- Automatic archive, analytics and stream-health checks.

**Websites**
- Built on SnapPages: drag-and-drop editing, templates, custom CSS, a blog, forms, a group finder and giving embeds.
- Landing pages for Tap and QR codes, and automatic SEO.
- No AI builder.

**Church management**
- People and households, created automatically from gifts, forms and logins.
- Custom fields, CSV import and a duplicate finder.
- An AI People Assistant (2026, Subsplash One only).
- Forms with logic.
- **Notes on people only shipped 2026-09-30.**
- Volunteer teams, rosters and availability.
- Service plans with SongSelect.
- Child check-in: an iPad kiosk, AirPrint labels, PINs, allergy notes, QR pre-check-in and grade promotion.
- Mass email.
- **SMS goes out from a fixed number that can't be changed, with "(via Subsplash)" appended, and replies arrive as email.**
- Not found: background checks, auto-scheduling, blockout dates, room ratios.

**Groups & Messaging**
- A group finder; groups that are open, private or request-to-join; member caps.
- Chat and DMs with photos, GIFs, files, reactions and polls.
- A prayer tab and scripture sharing.
- Leader announcements, multi-group push, and attendance (December 2025).
- Moderation: word and image filters, block and report, and leaders can read chats.

**Events**
- Free or paid tickets, discount codes and custom questions.
- **Partial payments with automatic reminders.**
- Walk-up registration, repeating events, add to calendar, and emails to registrants.
- No ACH for event payments.
- Waitlists *unconfirmed*.

**Workflows** (GA 2026-07-14, Subsplash One only)
- Kanban cards linked to people; forms create cards.
- An owner, due date and checklist on each card.
- Templates: visitor, volunteer, membership, new donor.
- An AI workflow generator.
- One email per step.
- No SMS steps and no real branching.

**Pulpit AI**
- Takes video, audio, a PDF or slides.
- Produces 20+ outputs: captioned clips, transcript, summary, quotes, small-group guide, devotionals, recap email, blog post, social captions, and "chat with your sermon."
- Standalone price: **$39 (5 uploads), $59 (10) or $129 (25) a month.**

**Trends AI**
- Dashboards over giving, people, groups, events and media, with 25+ chart types.
- An AI chart builder.
- Sold with "Premium" or "Standard Consulting."

**Tap**
- NFC discs at **$3 standard or $5 custom**, launched June 2025.
- Can be reprogrammed to give, connect, register or pray.
- US only.

### Pricing and fees

**Plans** are quote-only:
- Third-party estimates run about $99–283 a month.
- About $499 setup for apps.
- A Trustpilot reviewer saw $55 a month in 2019 rise to $282.99.

**Giving fees** (support art. 9101519):

| Payment | Giving Only / non-exclusive | Exclusive partnership |
|---|---|---|
| Visa and Mastercard | 2.99% + $0.30 | 2.30% + $0.30 |
| Amex and premium cards | 3.50% + $0.30 | 3.50% + $0.30 |
| ACH | 1.00% | 1.00% |
| Events and merch | 3.50% + $0.30 | 3.50% + $0.30 |

- "Exclusive" means Subsplash is the only online giving processor everywhere, for a 2-year term.
- GrowCurve rebates go as low as 1.9% card and 0.5% ACH, at volume thresholds they don't publish.

**Other costs:**
- Pro Support (live chat, phone, screen share): $89 a month.
- Standard support is tickets plus an AI assistant.

**Terms v4.0 (2026-07-27):**
- The term is 1–2 years and renews yearly.
- Cancel in writing at least 30 days before renewal.
- **Leaving early requires a call with your success manager, plus a fee of the lesser of 3× the monthly fee or the remaining balance.**
- No refunds and no downgrades mid-term.
- **30 days to download data after termination.**
- **Only Subsplash publishes the app**, and it can pull the app for non-payment.
- Subsplash gets a perpetual, irrevocable, royalty-free license to church content and may train AI on anonymized data.
- Texas law and Dallas arbitration.

### Complaints

- **Ratings:** Trustpilot 4.5 from 346 reviews (7% one-star); Capterra about 4.5; G2 4.0–4.2 from only 20–32 reviews.
- **Cancellation and lock-in:** "you can't just cancel your account you have to have a full-on meeting with them"; "charge you nearly $500 just to stop their services"; one church paid $400 to exit after a month.
- **Support:** "hides behind a wall of AI chat and meeting scheduling tools"; "every support request took a week or more."
- **Small churches:** "Not concerned about the needs of smaller churches"; "Misleading, Costly, and Poor Experience for Small Churches."
- **Over-promising:** one app was 4 months late while billing continued; one church's giving "never successfully migrated."
- **Websites:** "the weakest link in the chain"; "functional but uninspiring."
- **ChMS:** "still maturing and less capable than dedicated competitors."

### Integrations

- Rock RMS (deep).
- Planning Center (one-way giving sync, "being rebuilt").
- CCB (legacy), Breeze and MortarStone.
- Zapier (triggers only, API tier).
- SongSelect and Engiven.
- The public API and SSO are enterprise-only.

---

## Appendix B: What we have today (inventory, 2026-10-14)

Paths are backend unless marked FE. FE paths sit under `src/core/components/`.

**Member app** (`/my`)
- Files:
  - `member_portal.py` and `member_app_ui.py`: the Broadcast look, tinted from the church's brand.
  - `member_portal_church.py`: events, prayer, details, groups.
  - `_sermons`, `_bible`, `_live`, `_group_live`, `_messaging`, `_preview`.
- Sign-in:
  - A 6-digit code is stored as an HMAC, expires in 10 minutes and allows 5 tries.
  - The session cookie `__Host-` lasts 180 days.
  - Table `member_login_codes`.
- Owner controls: `GET/PATCH /member-portal/{biz}`, preview, and Chief's `set_member_app`.
- **Gaps:** no manifest or service worker, no push, no announcements, no family view for parents, no directory.

**Sites**
- Built-in pages: `/give`, `/events` (`events_rsvp_router.py`), `/sermons` (`sermons_public.py`) and `/my`.
- `site_doors.py` adds the church links to the nav.
- `site_vertical_features.py` defines the "gathering" family that tells the builder what a church page needs.
- Love City is hand-built in `sites/love-city-church/`.
- The forms builder is `intake_forms` (field types: text, email, phone, textarea, select, checkbox).
- FE `PrintMaterials.tsx` makes connect cards with QR codes.
- **Gaps:** no public `/live` on generated sites, no group finder, no prayer page, no date, file, signature or payment fields, no bulletin.

**Giving**
- Settings: `GET/PATCH /giving/{biz}`, with up to 12 funds and preset amounts.
- Checkout: `POST /public/giving/{slug}/checkout`, $1 to $25k, once or monthly, on Standard Connect with no platform fee.
- Every change is audited in `ministry_gift_history`; RLS limits access to owner, admin and accountant (`ministry_finance_access`).
- Receipts carry IRS Pub 1771 wording.
- Manual entries: `/giving/{biz}/records`.
- Statements: `/my/statement`, Chief's `giving_statement` / `giving_statements_run`, and `/reports/donors`.
- `payment_agent.py` drafts decline alerts.
- **Gaps:** see step 2. Also no batch entry, no giver analytics, and no reconciliation against payouts.

**Media**
- Tables `sermons` (title, preached_on, speaker, scripture, summary, questions, video_url, audio_url, published) and `sermon_series`.
- FE `church/SermonsPanel.tsx` writes them through PostgREST.
- Chief has `publish_sermon` (it can publish or unpublish, but not create).
- Clips, covers and flyers: `clip_finder.py`, `clipper_worker/`, `clip_covers.py`, `clip_posting.py`, FE `media/ClipStudio.tsx`.
- **Gaps:** see step 4. Also no transcripts or AI recap.

**Live**
- `live_router.py` (staff) and `member_portal_live.py` (members).
- Tables `live_sessions`, `live_chat`, `live_mutes`, `live_presence`.
- "I'm here" writes `attendance` with method `online`.
- FE `church/LivePanel.tsx`.

**Communication**
- `campaigns_router.py`: audiences are leads, clients, all, or silent-N-days, capped at 500.
- `sms_routing.py`: broadcast up to 500, keywords, and inbound routing on the church's own number.
- Dedicated numbers: `sms_numbers_router.py`. The 10DLC RELIGION vertical: `texting_isv.py`.
- FE `EmailTemplates.tsx` has church templates.
- Member messaging:
  - `member_portal_messaging.py`, `messaging_router.py`, `member_messaging_rules.py`, `msg_screen.py` (Haiku 5.5).
  - Tables `msg_*`.
- Automations are all drafts: `vertical_autopilot` new_attendee, `nurture_agent`, and a welcome draft from connect cards.
- **Gaps:** no member notifications, no newsletters, no targeting by group, event or household, no event reminders.

**People**
- `contacts`: status values lead, active, inactive, churned, vip, relabeled in FE as Visitor, Member, Leader and so on. Also tags, metadata and birthdate.
- Households (`kids_router.py`): tables `households`, `household_adults`, `children`, `household_pickups`, `child_care_notes`.
- `attendance.first_time`.
- **Gaps:** custom fields, a membership pipeline, first-visit date and count, a directory. The benchmark bands are all "not measured."

**Groups**
- Tables `groups`, `group_members` (`can_host_live`), `group_meetings`, `group_meeting_attendance`.
- FE `church/GroupsPanel.tsx`, which shows Connected % and who has missed the last 3 meetings.
- Members use `/my/groups` to join or leave and to chat.
- LiveKit meetings for up to 50 (`member_portal_group_live.py`), with staff drop-in via `group_live_router.py` and FE `church/GroupDropIn.tsx`.
- **Gaps:** public finder, join requests, leader tools in the app, a structured schedule.

**Events**
- Events are `module_entries` in event_roster modules.
- RSVP yes, no or maybe; capacity; roles per occasion (`_roles`); visibility (`_visibility`: public, private, invite).
- `POST /public/events/{slug}/rsvp` and `POST /my/rsvp`.
- **Gaps:** paid tickets, waitlists, repeating events, reminders, .ics.

**Volunteers**
- Roles with a "needed" count, self sign-up, and the brief lists unfilled roles.
- **Gaps:** scheduling, rotations, blockouts, reminders, background checks.

**Kids**
- `kids_checkin.py`: a 4-character family code texted from the church's own number; release to listed pickups only; a custody note means a manager must release.
- `kids_station.py` with table `checkin_stations`: PIN-locked staff mode, and a self kiosk that finds the family by mobile number.
- FE `StationApp.tsx` (at `/station`) and `kidsLabels.ts` (DYMO and Brother labels, with an allergy bar).
- **Gaps:** photos, room ratios, paging, QR pre-check-in, adult self check-in.

**Care:** `ministry_care_requests`, read-only inbox. See step 1.

**Bible:** `bible_text.py` with `bible_data/kjv.tsv.gz` and `web.tsv.gz`, and `member_portal_bible.py`. The reader's place lives in a cookie. FE `src/lib/bible-service.ts` is unused.

**Insights**
- FE `AttendancePanel.tsx` (8-occasion trend), Connected %, `briefing_verticals._community`, `/reports/donors`, `/reports/990-prep`.
- **Gaps:** no backend attendance analytics; benchmarks are uncomputed.

**Chief**
- Church verbs: `giving_statement`, `giving_statements_run` (`chief_giving_actions.py`), and `set_giving`, `set_member_app`, `publish_sermon` (`chief_door_actions.py`).
- There is a ministry prompt lens and church persona labels in `chief_of_staff.py`.
- **Gap:** no reads of church tables.

**Accounting**
- `gl_engine.py` `COA_NONPROFIT_EXTRA`: 3300 restricted net assets and 4200 restricted contributions; any non-General fund posts to 4200.
- `gl_reports_t4.py` (990 prep), FE `Prep990Report.tsx`, and a QuickBooks IIF export.
- **Gaps:** per-fund balances, releasing restricted funds, a statement of activities.

**Edition:**
- No "Solutionist for Churches" page exists yet.
- The `MINISTRY20` coupon exists (`stripe_billing.py`).
- FE `church/churchStructure.tsx` arranges the church workspace.
