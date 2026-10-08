# The Marketing desk: one week, one place, Chief in front

Mission Control → Growth → Marketing. This is Solutionist's own marketing,
and the setup that will later ship to businesses. It was streamlined on
2026-10-02 from the design canvas
https://claude.ai/artifact/R4YcBsj9xwtAgyDFsj19pW, which Kevin approved.

## The weekly loop

1. **Thursday 7:00 AM ET: plan next week** (`marketing_engine`). The engine
   reads the numbers and names one problem with the number that proves it. It
   picks plays from a fixed library and saves five posts as drafts, each with
   a flyer. Monday to Wednesday it plans the rest of the current week only if
   that week was never planned. It never plans overnight.
   - Before this release, `week_window` rolled to next week only once fewer
     than two posting times were left. That made every plan land on Thursday
     at 10:00 by accident, while the desk said "Monday 7:00".
2. **Chief tells the owner** (`marketing_desk`):
   - a push (`tell_owner_about_plan`), sent for scheduled plans only, and only
     once for a week that fails;
   - a Today item ("Chief drafted next week. Five posts wait for your OK");
   - Chief's read on the desk, which the drawer also opens with.
   All of it is computed from rows. No model call is made.
3. **The owner decides on the desk.** They can approve the week or one idea,
   ask Chief to change a post, or skip it. Approval stays the owner's alone:
   Chief has no approve action, and `/approve` still binds exact content hashes.
4. **Posts go out at 11:00 AM**, or the desk speaks up. A failed post, an
   unconfirmed delivery, or publishing that is paused while posts are approved
   reaches Today the same hour. `due_tick` pushes once per tick through
   `tell_owner_about_delivery`.
5. **Results.** Every post has its own `/go/` link, and the next plan leans on
   the plays that did well.

## What changed in the backend

- `marketing_desk.py` (new) handles the desk's read, masthead, "Needs a look",
  the Today items, the Chief digest and the pushes.
  - A **post** here means one idea: the same caption on every channel.
  - **Missed** drafts (time passed, never approved) are never counted as
    waiting; they become a "Reschedule or let go" item.
- `GET /platform/marketing/engine` adds `note`, `masthead`, `attention`,
  `deadline` and `relation`. `planning` is now read from the run row, so every
  replica agrees; before, it was a per-process set.
- New endpoints:
  - `POST /platform/marketing/slot/edit` changes one idea's caption and/or
    time on every channel. All posts are checked before any is saved, and
    each goes back to draft.
  - `POST /platform/marketing/slot/cancel` skips an idea or lets missed
    drafts go.
  - `POST /platform/marketing/posts/{id}/not-sent` is the way out for an
    unconfirmed delivery once the owner has checked Buffer.
- `dispatch`: an error before Buffer is reached (a storage blip, a channel
  lookup) puts the post back to `approved`, and the next tick tries again
  until its window closes. A preflight refusal fails it. Only an error once the
  create is under way is `uncertain`. Before, it escaped, and the row went
  `dispatching` → `uncertain` with no exit. A result that cannot be recorded
  is logged and left for the recovery sweep, never re-sent.
- `/slot/edit` and `/slot/cancel` check every channel's revision and state
  before writing anything. A change in the instant between check and write is
  reported channel by channel.
- New posts go everywhere by default (2026-10-02, after a hand-written post
  went to Instagram alone). `POST /platform/marketing/ideas` saves one caption
  for every connected channel in one insert unless `channel_ids` is given,
  leaves Instagram out (and says so) without a picture, and takes the next open
  slot (`GET /ideas/next-slot`: a weekday at 11:00 AM or 3:00 PM Eastern with no
  post at that time) unless `run_at` is given. Chief's `marketing_new_post`
  calls the same function, so Chief makes a post and says where and when,
  instead of asking first.
- Posting right away, with the owner's yes (2026-10-02). Kevin: "allow for
  permission to be given if they are looking to post right away."
  - On the desk, "Post now" in the new-post editor asks first
    (`POST /ideas` with `post_now`), and "Approve and post now" sends one
    reviewed post (`POST /post-now`, bound to its content hashes). The time
    moves to two minutes out and the owner's approval follows in the same
    step. Before anything is saved or moved, both check that publishing is
    on, that it is not paused, and that Buffer says each channel is live.
  - Chief's `marketing_post_now` is in the `review` group, so it never
    runs on its own. Its card freezes the exact caption and channels (or
    the desk post's words and revisions) when it is proposed. The handler
    runs only from a human-approved card and re-checks the frozen words.
- The seven-caption generator (`POST /platform/marketing/week`) is retired.
  The weekly plan is the one way a week is drafted.
- Today (`platform_today._marketing`) reads the weekly plan's posts. It used
  to count the platform business's content calendar, a different pipeline, so
  the engine's drafts never reached Today.
- Chief:
  - The Mission Control snapshot carries `marketing` (the digest), and
    `DIGEST_PROMPT` tells Chief to include it in "what needs me?".
  - The marketing drawer adds `marketing_edit_slot` (drafts gate),
    `marketing_skip_slot` and `marketing_replan_week` (marketing_stop gate,
    so the owner approves each on a review card).
  - A rewrite may not add a link, a hashtag or a number the post did not
    already carry.

No migration is needed.

## Before this ships to businesses

What is still platform-only:

- **Storage:** `platform_marketing_config` is a single row (`id = true`). The
  `platform_marketing_*` tables have no `business_id`, and the run id is
  keyed by week alone.
- **Credentials:** there is one `BUFFER_API_KEY` from the environment.
- **Brand and domain are hard-coded:**
  - `mysolutionist.app` in `tracked_link`, `short_link`, `follow`, `LANDING`
    and the news URLs;
  - the flyer footer;
  - `AUDIENCE`, `SYSTEM` and `TZ` in the engine.
- **Signals** come from platform-wide sources: `growth_summary`,
  `founder_offer`, `public_claims`, and `site_events` where
  `business_id is null`.
- **Owner gates:** every route uses `require_owner`; pushes go to
  `PLATFORM_OWNER_EMAIL`.

Tenant social publishing today is separate: Meta only, through
`content_calendar` and `post_approval`.

## The desk for every business — API

B4 of `docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md` (2026-10-07). The same
desk, for one business, on the `marketing_*` tables through
`business_marketing_store`. `business_marketing.py` is mounted at
`/marketing/{business_id}`, after `clip_posting` and before the public-site
catch-all. **Nothing in the API sends.** The sender (B5, below) claims
approved posts (`marketing_claim_due`) and re-checks everything at send time.

| Route | Who | What |
| --- | --- | --- |
| `GET /engine` | owner + members | settings, this and next week's posts, Chief's read, attention, `level`, `upgrade`, accounts |
| `GET /ideas/next-slot` | owner | the next open time |
| `POST /ideas` | owner | a new post as a draft (`post_now`: saved and approved, out in two minutes) |
| `POST /approve` | owner | `[{id, revision, content_hash}]`, all or nothing (`marketing_approve`) |
| `POST /slot/edit` | owner | words, time, accounts, picture or link; back to draft |
| `POST /slot/cancel` | owner | skip a post or let missed drafts go |
| `POST /post-now` | owner | a reviewed post goes out in two minutes |
| `POST /posts/{id}/not-sent` | owner | an unconfirmed delivery becomes a failure |
| `PUT /settings` | owner | paused, plan_enabled, accounts, hour (6-21), audience, link, work photos (B11); makes the desk row |
| `GET /results` | owner + members | what came through the post links in the last 30 days, per post and in total (B6) |
| `POST /engine/run` | owner | queue this week's suggested post, weekly plan or open-chairs week; the worker writes it (B8, B9, B11, below) |
| `GET /preview` | owner | what Chief would write about now: numbers, profile, facts, diagnosis, plays; reads only (B8) |

- **Who.** Reads use `business_access('viewer')`. Writes use `require_user`
  plus an owner check: a service-role read of `businesses.owner_id`. A member
  never approves, edits or posts.
- **One row per post.** Its accounts are in `targets`. The post id is a uuid5
  of the business and the caller's idea id, so a retried save is the same
  post.
- **Defaults for a new post.** It goes to the desk's accounts that are still
  connected, or to every connected Post for Me account when the desk names
  none. Instagram is left out without a picture, and TikTok and YouTube
  without a video; `dropped` and `note` say so. Its time is the next weekday
  at the desk's hour or 3:00 PM on the business's own clock, at least an hour
  away and not already taken. The clock is `availability.timezone`, then the
  owner's `practitioner_profiles.timezone`, then `PLATFORM_DEFAULT_TZ`, then
  UTC. A post may still go out up to six hours after its time.
- **The approval.** `content_hash` is `business_marketing_store.digest`. Any
  change bumps `revision`, recomputes the hash and drops the approval.
- **Post now** refuses, before anything is written, unless all of these hold:
  `MARKETING_DESK_PUBLISHING=on` (B5's switch, off by default), the posting
  pilot is on for the business, the desk is not paused, every account is
  still connected, Instagram has a picture, and the caption fits each network.
- **This business's rows only.** Every post, picture, clip and account is
  read with the business id in the filter, so another business's id answers
  exactly like a missing one.
- **Links.** `landing_url` must be https on the business's own host: its
  `mysolutionist.app` subdomain, or its custom domain once verified.
  `publish_text` is the caption with the post's short link (B6, below).
- **Fail closed.** A failed read is a 503 in plain words, never an empty desk.
- **`level`** comes from the real plan (`feature_gates.plan_includes`, which
  ignores `BILLING_ENFORCE`). `upgrade` is the next level's feature and
  `upgrade_plan_for`'s plan.

| Plan | `level` | `upgrade` |
| --- | --- | --- |
| Starter, no plan | suggest | marketing_week → Professional |
| Solo, Booked | suggest | marketing_week → Boss |
| Professional, Boss | week | marketing_autopilot → Solutionist |
| Professional, Boss: a personal_services business with a live booking calendar | openings | marketing_autopilot → Solutionist |
| Solutionist (practice) | autopilot | none |

`business_marketing_desk.py` computes the business desk's words from rows,
with no model call: Chief's read, the masthead, "Needs a look", Today items
and a Chief digest. They are on the business's clock: `marketing_desk`'s
wording helpers now take `tz`, and the platform desk's default is unchanged.
It promises no weekly plan until a planner exists (B8/B9). Nothing calls
`today_items` or `chief_digest` yet.

### Sending and the delivery watch (B5)

`business_marketing_dispatch.py`, two scheduled jobs registered beside the
platform desk's. They run only where scheduled jobs run (`PROCESS_ROLE`
worker or all), on the scheduler leader, and **do nothing until
`MARKETING_DESK_PUBLISHING=on`** (default off; set it on the worker). The
sender also claims nothing while `POST_FOR_ME_API_KEY` is missing or
`POST_FOR_ME_PILOT_BUSINESSES` is empty, so a configuration slip on the
worker never fails anyone's posts.

| Job | Every | What |
| --- | --- | --- |
| `business_marketing_due` | 1 min (`max_instances=1`) | claim up to 5 due approved posts and send each |
| `business_marketing_delivery` | 5 min (`max_instances=1`) | settle each post handed over; tell the owner once per problem |

**One door.** Every post goes through `social_publish_router.send_post`
(daily cap, the record of who approved what, our row id as `external_id`, a
refused hand-off recorded as failed), so it also shows in Build, Social
Media's recent posts. A picture or words go straight there; a clip goes
through `clip_posting.post_clip_for`, which adds its covers.

**Checked again at send time:** the content still hashes to the approval
(`digest == approved_hash == content_hash`) and its window is open; the desk
is not paused; the pilot is on (`post_for_me.allowed_for`); every account is
still connected to this business and is the same account
(`social._targets`, with a fail-closed second read so a failed read is never
"disconnected"); the picture is a ready artwork of this business; a clip is
approved as it is now, at the fingerprint the post was approved with.

**The build actor.** On the worker there is no JWT, so
`image_studio.build_actor` is bound to `{business_id, user_id: owner}` (the
owner read as the service role) for one post only and reset in a `finally`.
Storage then refuses any path outside that business's folder.

**The publication id** is `uuid5(post id, 'rev:<revision>')` (for a clip,
`post_clip_for`'s id from that request id). A retry of the same approved
version is answered by the door from its record, never posted twice; an
edited, re-approved post is a new send.

| What happened | The post becomes |
| --- | --- |
| sent, with the posting service's id on the record | `submitted`, with `publication_id` |
| sent, but the record has no posting-service id (an earlier record that never got one, or a receipt write that failed twice) | `uncertain`, with `publication_id`: never `submitted` unconfirmed |
| nothing left the server (a storage blip, a failed read, the door's cap read) | `approved` again; the next minute retries until the window closes |
| the desk was paused after the claim | `approved` again, quietly: it waits for Resume, as the desk says |
| posting is not switched on for this business (the pilot) | `approved` again, saying so, no push: it goes out if the business is switched back on while its window is open. Held posts stay claimed to the end of the tick, so they never crowd out other businesses |
| a check said no (changed, window closed, account gone, clip changed, the daily cap) | `failed`, in plain words |
| the posting service refused the hand-off (`send_post` 502) | `failed` |
| anything else once the hand-off began | `uncertain` (the owner checks, or the watch settles it) |
| the result could not be written | left `dispatching`; the claim RPC makes it `uncertain` after 10 min |

`send_post` itself now checks that the posting service's id reached the
record (one retry). If it did not, it still answers `(row, True)` with the
same public shape for `/social/publish`, but the row it hands back has no
`provider_post_id`, so a caller that needs a confirmed hand-off can tell.

**The delivery watch** (no webhook) refreshes posts that are `submitted`, and
`uncertain` ones claimed in the last two days, through `social._refresh`
(whose write now runs off the event loop): all accounts took it →
`published`, some → `partly_published`, none → `failed`, with each live
post's link in `external_urls`. A post still in flight two hours after its
claim becomes `uncertain`; a late answer still settles it. The publication
is read fail-closed: a read that fails leaves the post exactly as it is until
the next tick, so a failed read never makes a post `uncertain` or pushes. The
network's own error text stays on the publication; the post says which
accounts did not take it, in plain words.

**Telling the owner.** Each problem (`failed`, `partly_published`,
`uncertain`, including the claim RPC's own "time passed") gets one Today
item (`chief_notifications`, type `reminder`, navigate to Grow → Marketing)
and one push (`nav: grow:marketing`), keyed by post, revision and status in
`action_payload.dedup_key`, so it is said exactly once, and again only if a
fixed post fails again. A success is never pushed, and a failure the owner
made (marking a post not sent) is not announced back. The announcements
already made are read first and those posts left out, then problems are read
newest first, page by page, up to 100 announcements a tick: a post that just
became a problem is always considered, however many older ones there are. If
the announcements cannot be read, nothing is said until they can.

### How Chief reads a business

B7 (2026-10-07): the business's own numbers, facts and profile, read-only.
The weekly suggestion and `GET /preview` (B8, below) read them.

- **Signals** (`marketing_signals.read_signals`): service-role reads of one
  business, each bounded by a date window and a row limit, so a Thursday
  fan-out stays cheap.
  - Site visits: distinct sessions in the last 7 days, against the weekly
    average of the 28 days before (`site_analytics.business_rows`, at most
    5,000 rows, not the 50,000-row traffic report).
  - New contacts in the same windows.
  - Bookings (`module_entries`, `appointment_at` and `created_at`, status
    active): what is booked so far for the next 7 days, against what had been
    booked at the same point (7 days ahead) in each of the 4 weeks before. A
    week ahead is still filling in, so it is never set against past weeks'
    final totals; a past booking without its booking time makes the reading
    unknown.
  - Open chairs, for a personal_services business with a live calendar and
    weekly hours set: open times in the next 7 days for its shortest bookable
    offering (`agent_site.slots_for`). No count of them goes in a caption.
  - Offerings and site news posts from the last 21 days, and whether a plan
    has been about them yet (`marketing_runs.slots[].subject_key`).
  - The last post, from `marketing_posts` and `social_publications` (a desk
    post sent through Post for Me is counted once).
- **None, never 0.** A read that fails, or reaches its row limit, is None and
  is named in `unread`. Zero means it was counted. A rule whose signal is
  None is skipped, so a failed bookings read never says "fill the calendar".
- **The diagnosis** (`business_marketing_engine.diagnose`): first match wins,
  and each names the number that proves it.

  | # | Rule | Problem | When |
  | --- | --- | --- | --- |
  | 1 | bookings_down | fill_the_calendar | booked so far for the next 7 days under 70% of what was booked at the same point (7 days ahead) in each of the 4 weeks before (at least 3 a week) |
  | 2 | empty_week | fill_the_calendar | nothing booked in the next 7 days, open times on 2 or more of them |
  | 3 | something_new | tell_about_new | an offering or news post from the last 21 days no plan has been about |
  | 4 | visits_without_leads | turn_visits_into_leads | 20 or more visits in 7 days, no new contact |
  | 5 | traffic_down | get_found | visits under 70% of the weekly average before (at least 10 a week) |
  | 6 | gone_quiet | stay_visible | nothing posted in 14 days, nothing approved ahead |
  | 7 | barely_seen | get_found | under 10 visits in 7 days, on a site whose counter has counted |
  | 8 | steady | stay_visible | nothing is off |

  The calendar comes first because an empty chair this week cannot be sold
  next week. The rest follow the platform's order.
- **Plays:** `offer_spotlight`, `book_a_time`, `whats_new`, `useful_tip`,
  `meet_us` and `come_back`. None names a person. `pick_plays` uses the
  platform's own `_rank` and `fill_slots`, and every slot links to the
  business's own site (the desk's link, its booking page or its home page).
- **Facts:** `creative_director.business_facts` through `verified_facts`. A
  hidden price stays out, and so do inactive or archived offerings, brand
  colours and web addresses. Every number in a caption must be in the facts.
  A dollar amount must be a stated price, and in a post about one offering it
  must be that offering's price. The only address a caption may name is the
  business's own host (`marketing_engine.check_caption(..., own_hosts=...)`).
  A business caption may carry up to three hashtags (Kevin, 2026-10-07;
  `max_hashtags`, `marketing_profile.HASHTAGS_MAX`); a stray `#` and a fourth
  tag are refused, and a flyer carries none. The platform's default is
  unchanged: Solutionist's own captions take no hashtag and no address.
- **The profile** (`marketing_profile.read_profile`) holds:
  - the audience: the desk's, then the owner's `voice_profile.audience`, then
    a default for the business type;
  - the voice and the desk's clock;
  - the host and the landing page;
  - the shape: `openings` for a chair business with a live calendar, else
    `week`;
  - the caption writer's instructions, where "we" is the business;
  - the flyer footer: the business's name and host, never Solutionist's.

### Tracked links and results (B6)

The platform desk's `/go/` links and results, for every business
(`business_marketing_links.py`, `business_marketing_outcomes.py`, the `/go/`
route in `public_site.py`). No migration: the columns, `marketing_link_clicks`
and `marketing_follow` came with B3.

- **The short link** is `{origin}/go/{code}`. The origin is the business's
  verified custom domain, else `https://{slug}.mysolutionist.app`. The code is
  `business_marketing_store.link_code(post id)`: 8 characters from
  `sha256('marketing-go:' + id)`, so a retry or an edit keeps it, and it never
  equals the platform's code for the same id.
- **Where it goes** (`landing_url`): the post's own link, else the desk's
  (while it is still on the site), else `/book` when anything is bookable
  (booking page published, an active booking calendar and an active service
  or session with a duration), else the site's home when the site is
  published. With none of these, a post has no link: `tracked_url` is empty
  and the caption goes out as written.
- **`tracked_url`** is the landing page with `utm_source=social`,
  `utm_medium=organic_social`, `utm_campaign=marketing_desk` and
  `utm_content=<post id>`. Its host is always one of the business's own
  hosts; anything else is refused when the post is saved.
- **`publish_text`** is the caption with the short link: a mention of the
  landing page is swapped for it, otherwise it is added once
  (`platform_marketing.caption_with_landing_link`, now given the business's
  hosts). Each network's length limit is checked on these words.
- **The approval.** `publish_text` and `landing_url` are inside
  `content_hash`, and `tracked_url` follows from `landing_url` and the id. A
  new link is a new revision, back to draft. An edit rebuilds the link on the
  site as it is now; a post whose link has left the site (a domain no longer
  verified) is refused until its link changes (`''` means the default).
- **The redirect.** `/go/{code}` on a business host (`slug.<base domain>`, or
  a custom domain, with or without `www`, also through `X-Original-Host`)
  resolves the host's business first. `marketing_follow` is asked without
  counting. The visitor is redirected (302, `no-store`, `noindex`) only when
  the post is that business's and its `tracked_url` is https on that
  business's own hosts. Only then, and only for a person, is the click
  counted (`marketing_follow(code, true)`). Link-preview fetchers, bots and
  Do Not Track are redirected and not counted, and a post that never went out
  never counts (the RPC). An unknown code, another business's code, an
  off-site destination or a failed read gets the site's own answer for the
  path: its 404. On the platform's hosts, `/go/` calls
  `platform_marketing.follow` exactly as before.
- **Its own rate bucket.** On a business host, `/go/` is limited per host
  (`go:<slug>` or `go:<domain>`, www sharing the apex) to
  `GO_RATE_LIMIT_PER_MIN` (600 a minute), charged once per hit, a miss
  included. It never charges the site's page-view bucket (the bare slug, 100
  a minute). A post that takes off, or a crawler walking dead codes, cannot
  429 the business's pages or booking, and busy pages cannot 429 its links.
- **Visits carry the post.** The business site's traffic beacon now keeps a
  visit's campaign tags for the tab's session (first touch) and sends them
  with every event as `c`, as the platform's pages do, so `site_events.data`
  holds `utm_content`. Before this, business-site events carried no campaign
  tags at all.
- **`GET /results`** covers the posts that went out (submitted, published,
  partly published) in the last 30 days:
  - clicks from `marketing_link_clicks`;
  - visits as distinct sessions in this business's `site_events` whose
    `data.utm_content` is the post;
  - leads from this business's `contacts` whose `attribution.utm_content` is
    the post.

  It returns `totals`, `posts` (each with `has_link`), `sources` (`loaded`,
  `partial` at a row limit, or `unavailable`), `site.state` (`ready`, `none`
  or `unavailable`) and one `headline` worded "came through", never
  "brought". A source that cannot be read is `null` and named, never 0. A
  post with no link has `null` measures. The posts unreadable is a 503.
- **Leads are a floor.** `lead_attribution.capture` reads campaign tags off
  the form's `Referer`. Business-site forms and the booking widget post
  cross-origin to the API, and browsers send only the origin then, so most
  leads arrive without `utm_content` today. Counting them needs the forms
  and the booking widget to send the session's tags (frontend and
  site-module work, not built).

### The weekly suggestion and the fan-out (B8)

`business_marketing_planner.py` (2026-10-07). A business at the `suggest`
level (its real plan includes `marketing_suggestion` and not
`marketing_week`: Starter, Solo, Booked) gets **one suggested post a week**, a
draft on its desk to approve, change or skip. Professional and Boss (the week
levels) get nothing from B8; their five-post week is B9 (below). **Nothing runs until
`MARKETING_DESK` names the business or is `*`** (default off), and nothing a
suggestion writes is ever sent unless `MARKETING_DESK_PUBLISHING=on` and the
owner approves it on the desk.

**One suggestion** (`run_suggestion(business_id, trigger=)`):

1. Claim the week: `marketing_claim_run`, kind `suggestion`, run id
   `run_id_for(business, week)`. One run per business per week; a week
   already planned is left alone.
2. Read the business's numbers, profile and facts (B7), `diagnose`, and pick
   ONE play and ONE time: the first open weekday slot of that week at the
   desk's hour or 3:00 PM on the business's clock (`next_open_slot`).
3. ONE caption call: `llm_call.apost(task='business_marketing_suggestion',
   business_id=..., units=0)`, the `draft` lane's model, `max_tokens` 1200 at
   low effort (`model_ladder.effort_kwargs`). The caption must pass the
   business checks: numbers and prices only from the facts, links only to its
   own site, at most three hashtags. One that does not is never saved (the
   run fails with the reason; the scheduler retries a failed week at most
   three times, as the claim allows).
4. The **free composer flyer** (`chief_flyer_composer` over
   `marketing_design.flyer_layout`, `cost_usd` 0, never a Creative Director
   render): the business's own colours (`brand_palette` over
   `settings.brand_kit`, darkened until white words read at 7:1), the play's
   eyebrow, and the business's own name and site in the footer, never "THE
   SOLUTIONIST SYSTEM". Made under `image_studio.build_actor` bound to the
   business and its owner (read as the service role), reset in a `finally`.
   A flyer that cannot be made leaves a words-only post; flyer words that
   break a rule cost the picture, not the post.
5. ONE draft in `marketing_posts`: `source='suggestion'`, `run_id`, `play_id`,
   the desk's accounts (or every connected one) fitted by the shared door's
   rules (no plan gates a network: TikTok and YouTube take only videos, so a
   picture post leaves them out, recorded in the run's `design.left_out`;
   Instagram needs a picture), its tracked link (B6) and content hash.
6. The owner is told once: a Today item (`chief_notifications`, type
   `reminder`, "Chief has a post ready for next week", saying what it is
   about and when it goes out once approved) and a push
   (`send_to_user(owner, nav='grow:marketing')`), keyed by the post in
   `action_payload.dedup_key`. Never by text. If what was said cannot be read,
   nothing is said.
7. The run is marked `succeeded`, `skipped` or `failed`, with the reason in
   plain words (the desk shows it). A crashed attempt's saved draft is found
   by `run_id` and kept. Nothing approves or sends.

**The fan-out** (`marketing_tick`, job `business_marketing_suggest`, hourly,
worker only, leader-gated, `max_instances=1`):

- Candidates: a desk with `plan_enabled` (no desk row is made here), at least
  one connected account, the posting pilot on (`post_for_me.allowed_for`), the
  suggest level by `feature_gates.plan_includes` (whatever `BILLING_ENFORCE`
  says), `access_state` full or grace, automations not paused
  (`policy_engine.is_paused`).
- Due, on each business's own clock (the desk's one chain; the owners'
  profiles are read in one go, and a failed read skips those businesses for
  the hour rather than guess UTC):
  - Thursday from 7:00 + a jitter of 0-119 minutes (sha256 of the business
    id, the same on every server; Python's `hash()` is not), through Sunday:
    next week;
  - Monday to Wednesday: this week, only when it was never planned (or its
    plan failed fewer than three times: the claim's own rule, read first so a
    planned week costs nothing);
  - never overnight: nothing before 7:00 + jitter or from 21:00.
- At most `MARKETING_MAX_PER_TICK` businesses a tick (default 10, at most
  100); the rest wait for the next hour.
- Spend: before the tick and before each business, today's platform spend
  must be under 60% of `DAILY_SPEND_CAP_USD` (`spend_guard.platform_share`)
  and the platform under its ceiling, or every remaining business waits; a
  business over its own ceiling is skipped. Each business has its own try and
  its own claim: one failure never stops the batch.

**The owner's own request** (`POST /marketing/{business_id}/engine/run`): the
owner only (`require_user` + the owner check), the suggest level, the switch,
a connected account, the pilot, `rate_limit` (`business_marketing_engine`, 6
an hour) and **one request a day** on the business's clock. The web process
never calls the model, and **a request never loses the suggestion already
waiting**:

- The route claims the week and marks it queued (`design.queued_at`) in ONE
  write (`queue_request`): an insert for a week with no run, else a write
  conditional on the run's status and attempt count (a failed or skipped
  week, one stuck 15 minutes, or a succeeded one whose posts are all still
  drafts). It does not use `marketing_claim_run`, whose manual start-over
  cancels the waiting drafts at claim time. A week that is being written, or
  has an approved or sent post, is busy (409). If the write fails (503),
  nothing has changed: no run, no post and no desk row is touched.
- `manual_tick` (job `business_marketing_requests`, every minute, worker)
  takes each queued run once (a write conditional on `design.started_at`),
  saves the new draft, and **only then** cancels the week's earlier
  suggestion draft, each cancel conditional on the draft still being at the
  revision read. A draft that moved on (approved meanwhile) or a cancel that
  fails is left standing: the owner sees two and can skip one, never none.
- A request that writes nothing (over a spend ceiling, the pilot off, no
  time left that week, a caption that broke a rule, the model down, a save
  that failed, or the earlier one approved meanwhile) leaves the earlier
  suggestion exactly as it was: the run goes back to `succeeded` over it,
  with the reason in its `error` and `design.outcome = kept`. With no earlier
  suggestion it is `skipped` or `failed` as usual.
- Only a request that saved a new post (`design.made`) counts as the day's;
  one that wrote nothing leaves the owner free to ask again.
- A request not started within the claim's 15 minutes is left to the claim's
  own reclaim.

**The preview** (`GET /marketing/{business_id}/preview`, owner only): the
numbers, profile, facts, diagnosis and the plays Chief would pick (one slot
at the suggest level, five at a week level), with the week and whether the
switch is on. No model call, no write, no spend.

**Kevin's decisions (2026-10-07) as built here:** business captions may carry
up to three hashtags (the platform's stay at none); TikTok and YouTube are not
gated by plan (a picture post simply leaves them out); the Starter/Solo/Booked
suggestion uses the free composer flyer, `cost_usd` 0, never a Creative
Director render; owners are told by push plus a Today item, never by text. No
credits are charged for any of it (`units=0`).

**Switches** (`.env.example`): `MARKETING_DESK` (off | comma-separated ids |
`*`; set on the worker and the web), `MARKETING_MAX_PER_TICK` (default 10).
Cost: one Sonnet-class call of about 2,000 tokens in and 200 out, about 1-2
cents a suggestion; the flyer is a local render.

### The weekly plan (B9)

`business_marketing_planner.py` again (2026-10-07). A business at a **week
level** gets Chief's weekly plan: up to five drafts a week, each with a
Creative Director flyer, to approve in one go or one by one. The level is the
desk's own (`business_marketing.level_for`, from the real plan through
`feature_gates.plan_includes`):

| Level | Who | What B9 does |
| --- | --- | --- |
| week | Professional; a Boss business without a live chair calendar | the weekly plan |
| autopilot | Practice (Solutionist) | the same week plus up to two of its own clips (B12, below); the kinds the owner's standing OK covers are approved by Chief (B13, below) |
| openings | Boss: a chair business with a live booking calendar | nothing: it gets the open-chairs week instead (B11, below) |
| suggest | Starter, Solo, Booked | B8's one suggestion, unchanged |

**Nothing runs until `MARKETING_DESK` names the business or is `*`**, and
nothing the plan writes is sent unless `MARKETING_DESK_PUBLISHING=on` and the
owner approves it on the desk.

**One week** (`run_week(business_id, trigger=)`):

1. Claim the week (`marketing_claim_run`, kind `week`, the same run id
   rule). A week already planned answers `exists` and costs nothing.
2. The times: each weekday of that week at the desk's hour, or 3:00 PM when
   the desk's hour already has a post, on the business's clock, at least an
   hour away (`week_times`, like the platform's `week_window`). A week
   planned Monday to Wednesday gets the weekdays it has left.
3. The business's numbers, profile and facts (B7), `diagnose`, then
   `pick_plays` for those slots (`fill_slots`). **The plays lean on what did
   well through the business's own links**:
   `business_marketing_outcomes.play_scores` scores each post that went out
   in the last 120 days with its own link (a lead counts 4, plus the larger
   of clicks and visits) and averages them by play. `marketing_engine._rank`
   lets a play's results move it only once it has 3 samples; with fewer,
   the default order stands. A source that cannot be read gives no scores
   (the default order), never a guess. The run records the scores it used.
4. **One caption call** for every slot (`task=business_marketing_week`,
   the `draft` lane, low effort, `units=0`), each caption held to the same
   business checks as the suggestion (numbers and prices only from the
   facts, links only to its own site, at most three hashtags). A caption
   that breaks a rule costs only its own slot; flyer words that break one
   cost only that post's flyer. Every caption broken: nothing is saved.
5. **All the drafts in one insert**, `source='plan'`, with `run_id`,
   `play_id`, the desk's accounts (or every connected one), the tracked
   link (B6) and the content hash. A post with a flyer on the way is saved
   `design_status='designing'`, with Instagram among its accounts (the
   picture is coming); TikTok and YouTube take only videos, so a picture
   post leaves them out (`design.left_out`).
6. The flyers start (below). The run is `succeeded` with
   `design.tell = 'pending'`; the owner is told once the week has settled.

**The flyers.** One Creative Director design per post
(`creative_director.prepare_for_business` + `image_studio.create`), made
under `image_studio.build_actor` bound to the business and its owner (read
as the service role) and reset in a `finally`. **4:5, 1088x1360** (`high`
quality): the tallest picture Instagram's feed takes (4:5 to 1.91:1) and
shows whole, so every desk picture is Instagram-safe as delivered. Both
sides are multiples of 16, through the same custom-size path the clip
covers' 1088x1920 and 1920x1088 use live; `image_studio` offers 1088x1360
only on the models that take custom sizes (GPT Image 2 keeps its three, and
on it the plan falls back to a 1024x1024 square). The first live plan flyer
is the proof of 1088x1360 on the image model. The brief keeps every word,
the button and the main subject a twentieth of the width in from every edge
(Instagram's profile grid trims a 3:4 crop, 34 pixels off each side). B8's
free composer flyer was already 4:5 (1080x1350). The business's own colours (its facts carry `brand_colors`) and its saved style
and logo apply as in any of its designs. The words are the checked flyer
copy plus the business's name. The request id is
`uuid5(run id, 'flyer:' + post id)`, and a post's id is
`uuid5(run id, '<attempt>:week:<slot>')`: a retried run lands on the same
designs and never pays twice; a replan's new posts get new ones. A post
is never given up on while its design exists: if a start meets the daily
limit or an error but the design's row is there (a retried run, a race),
it stays `designing` and the design tick settles it; if that cannot be
read, it waits for the tick too.

**Included in the plan** (Kevin, 2026-10-07). A plan flyer is never charged
in credits, and is still:

- metered as cost: every planning, render and review call logs its dollars
  through `api_usage_logger` with `units=0`;
- checked against the spend guards before every paid call
  (`creative_director.guard`, business and platform ceilings);
- one of the business's 20 designs a day (`reserve_image_artwork`).

The flag is `director.billing = 'included'`, set by
`creative_director.include_in_plan`, which only the planner calls, on a spec
it built itself. `creative_director.included(spec)` honours it only on a
business design. With it, `run` renders with `charge=False`, planning checks
`guard(credits=False)`, and `image_studio.create` skips
`billing_limits.require_units`. **Nothing a request or Chief sends can set
it**: the Director's contract (`DesignRequest`) forbids extra keys,
`flyer_request` picks named fields, `prepare_for_business` builds the spec
dict itself, the platform door `start()` drops `billing` from an action's
spec, Image Studio's own route takes no director at all, and
`image_artworks` is read-only to signed-in callers (only the server writes
`director`).

**Caps.**

- At most **5 plan flyers per business per week**, replans included (the
  image rows that exist for the run's posts are counted). A replan gets
  what is left; past that its posts go as words only, saying so.
- At most `MARKETING_DESIGNS_AT_ONCE` (default 10, at least 5, at most 50)
  plan flyers in progress across every business. A week starts only when
  its five fit; the fan-out leaves it for a later hour, and an owner's
  request waits up to 10 minutes and then gives up in plain words, keeping
  the week's earlier plan.
- The daily limit: `image_studio.create` now reads the business's images
  started today (UTC, as the RPC counts them) and answers **429** "Daily
  image limit reached. Try again tomorrow." before reserving (the RPC still
  enforces it; its refusal used to surface as "storage unavailable", 503).
  Only a NEW request is refused: a request id that already has a row is
  answered with that row first, and the count leaves out the request's own
  id, so a retry racing the first call gets its row back from the RPC,
  never a 429. This holds for every caller, the owner's own Image Studio
  included.
  A plan post whose flyer gets the 429, or cannot start for any other
  reason, goes as words only **at once**, Instagram left out, instead of
  waiting.

**The flyers land** (`marketing_design_tick`, job
`business_marketing_designs`, every 2 minutes, worker only, leader-gated,
`max_instances=1`, nothing unless `MARKETING_DESK` covers the business):

| The flyer | The post |
| --- | --- |
| finished (`ready`) | `media` = the artwork, a new revision and content hash, `design_status='ready'`, still a **draft**. A design Chief's own check was unsure about (`needs_review`) is attached with a note in `error` asking the owner to look before approving |
| failed | words only: `design_status='failed'`, Instagram left out, a new revision and hash, a plain note in `error` |
| not ready 20 minutes after it started (or after its post was saved, when it never started) | the same, "The flyer wasn't ready in time, so this post goes as words only, and Instagram is left out." |
| still within 20 minutes | waits |

Every write lands only on the draft as it was read (same revision, still
`designing`). When Instagram is the post's only account, it stays and the
note asks for a picture; `/approve` now refuses a post whose accounts need a
picture it does not have, so it is never approved only to fail at send time.
A late design that finishes after its post gave up stays in the Media
Library. A week is never held up: within 20 minutes every post has settled.

**A designing post cannot be approved.** `marketing_approve` refuses it
(the migration), and `POST /approve` now says so first, in the desk's words;
edit, skip and post-now already refused it.

**Telling the owner, once.** When no post of the run is designing, the
design tick sends one Today item (`chief_notifications`, type `reminder`,
navigate to Grow → Marketing) and one push (`nav: grow:marketing`): "Chief
planned next week: 5 posts wait for your OK", with "Each has its flyer." or
how many go as words only, and "Nothing posts until you approve them." Keyed
by the run and its attempt in `action_payload.dedup_key`; the run is then
marked `design.tell = 'done'`. If what was said cannot be read, nothing is
said until it can. Never by text.

**The fan-out** (`marketing_tick`) takes week-level businesses with the same
candidates (now with their level: a calendar that cannot be read leaves the
business out for the hour), due-ness, jitter, per-tick cap and spend rules.
A week costs more, so it is counted conservatively: before each week, today's
platform spend plus what is already on its way (flyers in progress at $0.50
each, and $2.55 for each week this tick started) plus this week's $2.55 must
stay under 60% of `DAILY_SPEND_CAP_USD`, or the week waits for a later hour
while suggestions go on. B8's checks (60% before each business, the platform
ceiling, the business's own ceiling) still come first.

**The owner's own request** (`POST /marketing/{business_id}/engine/run`) at a
week level queues a week (`kind: week`, "Chief is planning your week") the
same way as a suggestion: the owner only, the switch, an account, the pilot,
`rate_limit`, one write that claims and marks it queued, the worker writes
it. Instead of once a day:

- a planned week is **planned again at most twice** (`design.replans`; a
  third ask is 429);
- only while none of its posts is approved or sent (409), and not while a
  flyer of it is still being made (409);
- the new drafts are saved first and only then are the old ones retired,
  each only if still the draft read; a replan that writes nothing keeps the
  week's earlier plan, saying so.

A week can take over the week's suggestion run when a business moved up a
level.

**Cost** (estimates, not yet measured on a live business-week): the caption
call is about 2 cents. A flyer is a planning call and a review on the
`review` lane (about 4-6 cents together) and a 1088x1360 high-quality render
(about $0.20 at the image model's rates), about $0.26; one that takes its
repair render about $0.48. **About $1.35 a business-week, up to about $2.50**
when every flyer takes its repair. The headroom check reserves $2.55.

**Switches** (`.env.example`): `MARKETING_DESK` (covers the plan too),
`MARKETING_MAX_PER_TICK`, `MARKETING_DESIGNS_AT_ONCE` (default 10). No
migration: the run's `design` jsonb carries `flyers`, `tell`, `told_at`,
`replans` and `left_out`.

**Not built here:** Chief's desk actions (B10), clips in the week (B12),
standing permissions (B13), and the frontend (F4). The open-chairs week is
B11, below.
Not yet seen live: a 1088x1360 render from the image model (the custom-size
path is the clip covers'); the first plan flyer on a test business verifies
it.

### The barber-sized week (B11)

Boss (barbershops and salons, $99) gets the weekly plan barber-sized: made
from the chair calendar, not from the numbers (Kevin approved the design on
2026-10-07, D5 of the plan). The level is the desk's own `openings`
(`business_marketing.level_for`: marketing_week on a personal_services
business whose booking page is published and whose booking calendar is
active). The run is `business_marketing_planner.run_openings`, kind
`openings`, on the week's machinery: the same claim, fan-out, jitter,
per-tick cap, spend headroom (counted like a suggestion: one small call, free
pictures), owner's request and save-new-before-retire-old.
`business_marketing_openings.py` is the calendar's half.

**Which offering.** The most-booked active, bookable offering over the last
60 days, counted from `module_entries.data->>offering_id`: the field the
booking widget and Chief's `create_booking` write
(`booking_widget_router._maybe_denormalize_offering`). module_entries has no
`offering_id` column (checked read-only against production on 2026-10-07: 400;
`appointment_at` and `duration_min_at_booking` are columns). With no booking
that names one, the shortest bookable offering, as B7's capacity signal
does; with the bookings unreadable, the shortest too. The run records which
(`signals.calendar.offering_from`: most_booked, shortest, shortest_unread).
Production had no bookings with an appointment in the last 60 days on
2026-10-07, so the most-booked path has not yet met a real calendar.

**The windows.** `agent_site.slots_for` for that offering over the week
(strict: below). Starts on the same local day no further apart than the
calendar's slot step are one window, from its first start to its last start
plus the offering's length; `open_count` is how many starts it holds. These
are start times, not chairs: `compute_slots` keeps a start open while any
chair is free, so no count of chairs is ever known or said.

**Rank and pick.** A window's minutes, doubled on the week's slowest
weekday: minutes x (2 - that weekday's share of the busiest weekday's
bookings over the last 60 days); with no history, minutes alone. Highest
first, ties by the earlier start. Three are picked, at most one a day, each
only if its post can be scheduled.

**When each post goes out**, on the business's clock: the day before at the
desk's hour, else the day before at 3:00 PM, else that morning at 8:00. The
first that is at least an hour from now, not already taken by another post,
and leaves at least 30 minutes to send before the cut-off. The cut-off is
two hours before the window, or the calendar's lead time if longer:
`expires_at = min(run_at + 6 h, start - the gap)`, so a post never goes out
saying a chair is open once it can no longer be booked online. Instants are
compared in UTC, so a daylight-saving change never moves one (tested across
both 2026 changes in Chicago). A replan's earlier drafts do not count as
taken: they are retired once the new ones are saved.

**Where they go.** Instagram first, Facebook too when connected: only those
two, from the desk's accounts (or every connected one). Neither connected:
the week is skipped, saying so. The link is the booking page (`/book` on the
business's own host), with the post's own short link (B6).

**The words.** ONE caption call for the three (`task=business_marketing_openings`,
the `draft` lane, low effort, `units=0`). Each caption is held to the
business checks (numbers and prices only from the facts plus this window's
own day, date and time; links only to its own site; at most three hashtags)
and to these: no count of chairs, seats, spots or times, and no "last one",
"going fast" or "before they're gone" (concurrent_capacity is not verified);
it names its own day and no other; never "today", "tonight" or "tomorrow"
(the post may move). A caption that fails, or a call that does not answer,
gets the plain caption, which always holds ("Open chairs Thursday 2 to 5 pm.
Book your time online and we'll see you then."); `dropped` records why. The
flyer's words are built in code, never by the model: the day and time, "Book
your chair online.", "Book now".

**The picture.** The owner's newest work photos (`marketing_desks.work_photo_ids`,
newest first, cycled over the three posts) full-bleed at 4:5 (1080x1350,
B8's composer path), the words on a panel in the business's own colour over
the lower part, its name and site in the footer; the top of the photo
(at least 42%) stays clear. `cost_usd` 0, made under the build actor bound to
the business and its owner. The photo's own pixels are placed, cropped to
fit: nothing redraws a real haircut, and nothing here ever calls the image
model. No usable work photo (none set, or deleted since): the business's
branded flyer, and the Today item says so ("add work photos on the desk to
show your own work"). A photo that cannot be placed falls back to the flyer;
no picture at all leaves the post words only, Instagram left out.

**Work photos** (`PUT /marketing/{business_id}/settings`, `work_photo_ids`,
owner only): each a ready image of THIS business (another business's id
answers like a missing one, 404; still being made or failed, 409), a photo
uploaded through `/ai/images/upload`, never a picture the image model or the
composer made (`model` or `size` set: 422), at most 12 (422), saved newest
first, duplicates once; `[]` clears them. A failed read is a 503 and changes
nothing.

**Each post stores its `opening`**: `offering_id`, `starts_at`, `ends_at`,
`open_count`, `duration_min`, `day`, `time_zone`, `gap_min`, `when` ("Thursday
2 to 5 pm") and the offering's name. It is not content: it is outside the
content hash, so it never voids an approval.

**The pull.** A post is pulled when its window no longer holds as many open
starts as it was made for (`fewer`), none at all (`full`: "Thursday 2 to 5
pm filled up, so its post was pulled"), or it is within the gap of its
window (`late`, after an owner moved it). Pulling is the safe direction, so
it never needs the owner's yes: status `pulled`, a new revision (an open
desk refreshes), the reason in plain words in `error` and `opening.pulled`.
Two places check:

| Who | When | A failed calendar read |
| --- | --- | --- |
| `openings_watch_tick` (job `business_marketing_openings_watch`, every 15 minutes, worker only, leader-gated, `max_instances=1`, nothing unless `MARKETING_DESK` covers the business) | approved and draft opening posts going out in the next 48 hours (and not expired) | changes nothing |
| the sender (B5's `dispatch`), after the pause and pilot checks | just before the hand-off | holds the post: back to `approved`, "the booking calendar couldn't be checked just before sending...", tried again next minute until its window closes. Never sent on a guess |

A post whose `opening` cannot be read is refused by the sender (failed, in
plain words). Each write lands only on the post as read (same revision and
status; the sender's only on its own claim). The watch then tells the owner
once per pulled post, the sender's pulls included: one Today item
(`chief_notifications`, type `reminder`, navigate to Grow → Marketing) and
one push, keyed `marketing_opening:<post id>`. If what was said cannot be
read, nothing is said until it can.

**The calendar is read strictly.** `agent_site.slots_for(..., strict=True)`
and `outside_calendar.busy_blocks_*(..., strict=True)`: a bookings read that
fails or comes back at its row limit, and an outside-calendar read that
fails (other than the feature not being set up), raise instead of counting as
"nothing booked". The offerings are read fail-closed here too (the agent
bundle reads them `or []`).

**A fix to the shared slot computation (all surfaces).** `slots_for` asked
module_entries for a `duration_min` column that does not exist, so in
production that read answered 400, the `or []` made it "no bookings", and
every slot read as open on the agent surface, the Site Concierge's picker and
B7's capacity signal. It now reads `appointment_at,duration_min_at_booking`
and the booked length from `data->>duration_min_at_booking`. Not changed
here: `booking_widget_router.py` selects the same missing column (around its
lines 650 and 1323: the widget's slot read and the double-book guard's read).
How each handles the failed read was not checked in this PR; it is worth its
own.

**Telling the owner the week is planned:** one Today item and one push,
"Chief planned next week's open chairs: 3 posts wait for your OK", with what
the pictures are and "a post comes down by itself if its time books first";
keyed by the run and attempt.

**The owner's request** (`POST /engine/run`) queues the open-chairs week
(`kind: openings`, "Chief is planning your open chairs ..."), replacing the
old 409. The week's rules: planned again at most twice (429), never over an
approved or sent post (409); a pulled post does not hold the week; the new
drafts are saved before the old ones are retired; a request that writes
nothing keeps the week's earlier posts. It may take over the week's
suggestion or plain week.

**The preview** (`GET /preview`) at the openings level adds `openings`: the
offering, how it was chosen, and the windows Chief would post about with
when each post would go out. Reads only.

**Cost** (an estimate, not yet measured live). One caption call a
business-week on the `draft` lane (Sonnet 5.5), about 2,000 tokens in and 400
out, about 1-2 cents, as B8's suggestion; nothing when the plain captions
stand in. The pictures are local renders (`cost_usd` 0); no credits
(`units=0`). The watch and the sender's re-check make no model call.

No migration (`marketing_posts.opening`, status `pulled`, source `opening`,
run kind `openings` and `marketing_desks.work_photo_ids` came with B3), no
Chief action, no frontend (F5 is the Boss view).

### Clips in the week (B12)

Solutionist (the desk's `autopilot` level: the real plan includes
`marketing_autopilot` and `ai_clips`, which is Practice alone) gets Chief's
weekly plan (B9's five flyer posts) with **up to two of its own video clips
folded in** (D6, Kevin's design of 2026-10-07). `business_marketing_clips.py`
is the clips' half; `business_marketing_planner._plan_week` folds them into
the same run, the same caption call and the same insert. Professional and
Boss never get clips (`clips.takes_clips` is False for every plan but
Practice; Boss is "No Video Clips"), and neither does the suggest level.
**No eligible clip: the week is exactly B9's** (the same posts, the same
caption call; the run only records `design.clips`).

**Which clips.** Every one of these:

| Check | Where it is read |
| --- | --- |
| a ready clip of this business, still stored | `media_assets`: `kind clip`, `status ready`, `source_removed_at` empty |
| kept by the owner (not skipped, not undecided) | `media_assets.decision = 'kept'` (Video Clips' Keep) |
| approved at the fingerprint it has now | `media_assets.approval.fingerprint == media_library.fingerprint(row)` (`clip_posting.approval_problem`) |
| not posted anywhere | no `social_publications` row naming it (`media->0->>clip_id`), status other than failed or cancelled: Chief's `post_clip`, the clip screen and the desk all post through that door |
| not already in a waiting post | no `marketing_posts` row naming it (`media->>clip_id`), status other than cancelled, failed or pulled, except this week's own drafts a replan is about to retire |
| covers ready | a ready story (9:16) cover (`image_artworks`, `director->>clip_id`, `status ready`): the cover every vertical network shows |

A read that fails picks no clip (`design.clips.state = 'unreadable'`): never
a guess that could post a clip twice. The week itself goes out as B9's.
A post the owner skipped (cancelled) or that failed lets its clip be picked
again; one that is waiting, sending or went out holds it.

**The pick.** Best first: the clip finder's score (`configuration.score`,
highest first; a clip without one after every scored clip), then the newest,
then the id. At most two a week, each clip once.

**When.** Each clip on its own weekday, Tuesday first, then Thursday,
Wednesday, Monday, Friday (two clips land two days apart when they can),
never two the same day. At the desk's hour or the next free hour up to
21:00, then 3:00 PM and after, on the business's clock; at least an hour
from now; and **at least three hours from every other post of the business
that day** (the week's flyer posts, the owner's own, anything planned).
With the default 11:00, the flyer goes at 11:00 and the clip at 2:00 PM.

**Add, not replace.** The clips come on top of the five flyer posts: seven
posts at most a week, two on a clip day. No limit is near: the posting
door's daily cap is 25 posts a business per rolling day; the week's five
included flyers and `MARKETING_DESIGNS_AT_ONCE` count designs, and a clip
needs none; `marketing_approve` takes 50 at once. A clip post's
`design_status` is `none`, so it never waits on the design tick.

**The post** (`source 'clip'`, `play_id 'video_clip'`, so the clips' own
results show in `play_scores` without ever reordering B9's plays):

- `media` is `business_marketing.build_media`'s for a clip, re-read
  fail-closed just before it is saved: `{clip_id, clip_fingerprint, covers:
  {story, wide}}` (the newest ready cover of each shape). The fingerprint and
  the covers are inside `content_hash`.
- `targets`: the desk's accounts (or every connected one when the desk
  names none) on a network `clip_posting` can place a vertical clip on
  (`COVER_SHAPES`: Instagram, Facebook, TikTok, YouTube, X, Threads,
  Pinterest, LinkedIn). TikTok and YouTube are included (Kevin's decision
  3: no plan gates a network). An account on any other network is left out
  (`design.clips.left_out`).
- The cover each network shows is `clip_posting.cover_for`'s at send time:
  the story cover everywhere a vertical clip plays (Reels, TikTok, Shorts,
  X, Threads, Pinterest), the wide cover on LinkedIn (else the story one).
  The run records it per network (`design.clips.picked[].covers`).
- `publish_text` carries the post's tracked short link (B6), as every desk
  post does. `post_clip_for` sends one caption to every account, so on
  Instagram and TikTok the link shows as plain text.

**The caption.** One more slot in the week's ONE caption call
(`write_week_captions`, `max_tokens` 300 more per clip, no new call): the
clip's title, the words the owner checked and its tags as data, a brief
that says nobody has watched it (nothing beyond its title and words) and
that it takes no flyer. The same business checks as every caption: numbers
and prices only from the facts, links only to its own site, **at most three
hashtags** (Kevin's decision 2). A caption that breaks one costs only that
clip, which stays eligible next week.

**The approval and the send.** Nothing posts without the owner's OK
(standing permissions, B13 below). The sender (B5) already re-checks a clip
post: the content still hashes to the approval, and the clip is approved as
it is now at the fingerprint the post was approved with
(`_clip_ready`); `clip_posting.post_clip_for` checks again. New here: a
clip Chief folded in (`source 'clip'`) that the owner has since taken off
the kept clips is refused in plain words. A clip post goes out through
`post_clip_for` (the request id `uuid5(post, 'rev:<revision>')`, so a retry
never posts twice).

**Telling the owner.** The week's one Today item and push now name the
clips: "Chief planned next week: 7 posts wait for your OK" / "5 have a flyer
and 2 are your own video clips, with their covers. Nothing posts until you
approve them." A clip is never counted as words only. The owner's request
(`POST /engine/run`) says the week comes with up to two clips.

**Replans.** A replan picks again; the week's own drafts do not hold their
clips, so the same clips can come back in new posts, saved before the old
drafts are retired. A worker that stops after saving keeps the attempt's
clip posts as it keeps its flyer posts.

**Cost.** No new paid call: each clip is one more caption in the week's
call, about 250 tokens in and 75 out on the `draft` lane, under half a cent
a week for two. Posting a clip calls no model (a signed link, the cover as a
JPEG). A business-week stays about $1.35 (up to about $2.50 when every flyer
takes its repair); the fan-out's $2.55 reservation is unchanged.

No migration (`source 'clip'`, `media` jsonb and `play_id` came with B3), no
Chief action, no frontend (F6 is the Solutionist view). Not yet seen live:
the `media->0->>clip_id` filter on `social_publications` (a PostgREST JSON
path with an array index; a 400 there reads as a failed read, so the week
goes without clips, never with a clip posted twice).

### Chief works the desk (B10)

`chief_marketing_actions.py` (2026-10-08). Chief does in chat what the owner
can do on the desk, through **the same server functions** the desk's API
calls: `business_marketing.engine` (the read), `create_idea` (New post, now
with `source='chief'`), `edit_slot` (Change), `cancel_slot_route` (Skip),
`post_existing_now` / `create_idea(post_now=True)` (Post now) and
`business_marketing_planner.run_route` (`POST /engine/run`). No second write
path: every change keeps the API's owner check, revision rule and content
hash.

| Verb | Class | How Chief calls it | What |
| --- | --- | --- | --- |
| `marketing_desk` | read | native lookup tool (and tag) | this and next week's posts (post_id, revision, time on the business's clock, status, words, accounts, picture), what waits for the owner's OK, Chief's read (the desk's own `note`), the level and the server's `upgrade` label; `results: true` adds `GET /results` (B6) |
| `marketing_new_post` | write A | tag | a draft (words; a Media Library picture by id or `"image":"latest"`, or a free composer `flyer` {headline, line, cta}; networks; a time with its zone, else the desk's next open time; a link on the business's own site) |
| `marketing_edit_post` | write A | tag | words, time, accounts, picture (or `remove_picture`) or link; a new revision, back to draft: an approved post needs the owner's OK again |
| `marketing_skip_post` | write A | tag | the post is cancelled and never goes out |
| `marketing_replan` | write C | tag | the week's writing again, by the route's own level rules and limits; optional `kind` (suggestion, week, openings) |
| `marketing_post_now` | write C | tag | a desk post (post_id + revision) or a new one goes out in about two minutes |

- **No approve verb.** Chief never approves a post: the owner approves on the
  desk (standing permissions come with B13). Post now is the desk's own
  "Post now" (it approves as the owner's and moves the time in one step):
  class C, on the owner's yes in that chat turn (the class-C gate holds a
  voice turn for a spoken yes), refused before anything is read on a
  scheduled, automatic or agent run (`_unattended`), and in
  `policy_engine.CLIENT_FACING`. `schedule_action` will not wrap any desk
  change.
- **Why tags.** `mcp_server.WRITE_TOOL_SCHEMAS` is also the outside agent's
  write list. Every desk write is the owner's alone, checked against the
  signed-in person on THIS chat turn (`_TURN_USER_ID` against
  `businesses.owner_id`, the API's `_owner_row`), which the agent surface does
  not carry; the table keeps out writes that shape what the public sees and
  writes that spend (a replan can start up to five paid flyers); class C is
  never a tool. The read is a native tool (`mcp_server.TOOL_SCHEMAS`, so also
  on the read-only agent surface, tripwire 37 to 38).
- **Who.** Owner and members read; only the owner changes anything. No signed
  in turn, no change.
- **The gate.** Nothing works, and no context block is read, unless
  `MARKETING_DESK` covers the business (`desk_on_for`): every verb says "isn't
  switched on yet". A replan asks for what the plan gives (`level_for`: suggest
  writes one suggested post, week and autopilot a week, openings the
  open-chairs week); asking for more names the server's own `upgrade` label
  ("A whole week of posts planned for you comes with Professional" for a
  Starter), never a plan written in the code. The route's limits stand: once
  a day for a suggestion, a week planned again at most twice, never over an
  approved or sent post or while its flyers are being made, the rate limit
  and the spend ceiling.
- **Stale.** Every change names the post's id and the revision Chief read. A
  revision that moved on (the owner changed it on the desk meanwhile) is
  refused before anything is written, and the desk refuses it again at write
  time; Chief says the post changed and reads the desk again.
- **Words.** A failed read is "couldn't read", never "nothing there".
  "Sent" and "posted" are said only when a post's status from the server says
  so (submitted, published); post now answers "approved, goes out at 3:42 PM".
  Refusals are the desk's own plain words. A flyer's words are held to the
  weekly flyers' checks (numbers and prices only from the business's own
  facts, its own site only, no hashtag) and made by the planner's own
  `make_flyer` (the free composer, cost 0).
- **In a turn.** On a marketing-shaped turn (the growth doctrine's triggers,
  Grow → Marketing on screen, or words like post, flyer, Instagram, desk) a
  compact read of the desk rides the prompt's per-message tail beside the
  doctrine, never a cached segment: the level, sending, Chief's read, up to
  six posts with post_id and revision, what needs a look, and the rules line.
  About 240 tokens with one post, about 500 at its six-post cap; read with a
  6-second limit, and a failed read says so. The verbs' catalog is static
  text beside post_image's in the per-business cached segment (about 800
  tokens, byte-stable), and the read tool's definition about 170.
- **The desk's own words** now name a run for what it wrote (note, masthead,
  Needs a look, Today): a suggestion is "a suggested post" ("Chief is writing a
  suggested post.", "Next week's suggested post is drafted.", "Chief suggested
  a post for next week. It waits for your OK", "The suggested post for the
  week of October 12 could not be written"), the open-chairs week
  "open-chair posts", and a week "next week's posts" while it is written. A
  week and a run without a kind read exactly as before. `chief_digest`'s plan
  carries its `kind`.

No migration (`source='chief'` came with B3). Tests:
`__tests__/test_chief_marketing_desk.py`.

### Standing permissions (B13)

`business_marketing_standing.py` (2026-10-08), D6 of the plan. At the
`autopilot` level (Practice, the Solutionist plan) the owner can let Chief
**approve** chosen kinds of posts without asking each time. Chief never sends
anything itself: the approval is the desk's own (`marketing_approve`, the
same revision and content-hash binding as the owner's tap) and B5's sender
sends it as it sends every approved post. Each one can be taken back until it
goes out.

| Kind | The posts it covers |
| --- | --- |
| `marketing_post` | Chief's weekly flyer posts (`source 'plan'`) |
| `post_clip` | the owner's own clips Chief folded into the week (`source 'clip'`, B12) |

Nothing else is ever approved on a standing OK: the weekly suggestion
(Starter, Solo, Booked), open chairs (Boss), the owner's and Chief's one-off
posts, and Post now.

**The grant** is `standing_permissions`' own, extended rather than forked:
the same storage (`businesses.settings.autonomy.standing[kind] =
{granted_at, granted_by, via}`), the same owner-only door
(`POST /agents/chief/standing {business_id, verb, grant}`; `grant: false`
revokes, or declines a question not yet answered), the same audit rows
(`standing_grant`, `standing_revoke`). The marketing kinds are kept apart
from the proposal kinds (`MARKETING_KINDS`, not `ELIGIBLE`): they never get a
release time, never ride the release tick and are never asked about by the
Approval Queue, so Chief's own `post_clip` proposal is not covered by the
week's clip grant. Chat never grants one ("the owner turns that on
themselves on the marketing desk"); chat may revoke one only on the owner's
own turn. `GET /agents/chief/standing` lists them under `marketing`, apart
from the send switches.

**Covered** (`covers`) only while every one of these holds:

| Check | Read from |
| --- | --- |
| the grant exists and was given by the business's current owner | `settings.autonomy.standing[kind].granted_by == businesses.owner_id` |
| the real plan includes it | `feature_gates.plan_includes(row, 'marketing_autopilot')`, and `ai_clips` for `post_clip` (ignores `BILLING_ENFORCE`; a comp counts; a subscription not trialing or active has no plan) |
| client-facing autonomy is enabled | `policy_engine.client_facing_autonomy(row) == 'enabled'` (a regulated practice defaults to disabled) |
| automations are not paused | `policy_engine.is_paused(row)` |
| standing permissions are not switched off | `STANDING_PERMISSIONS` (default on) |

**Where each check sits.**

| When | Where | Not covered |
| --- | --- | --- |
| grant | `standing_permissions.grant` (plan and autonomy) behind the door's owner check | 400 in plain words; a member gets 403 |
| approval | `approve_run`, from the planner's `tell_week` | the post stays a draft for the owner |
| send | `business_marketing_dispatch.dispatch`, for a post `approved_via 'standing'`, after the pause and pilot checks | the post goes back to a **draft**, unsent; the rest of its kind goes back too; the owner is told once. A business that cannot be read holds the post (back to approved, tried again next minute), never sent on a guess |
| every 2 minutes | `lapse_sweep`, at the end of the design tick (`business_marketing_designs`) | approved standing posts of that kind go back to drafts at once; the owner is told, unless they turned the permission off themselves |

A post put back carries the reason in its note: "Chief's standing OK no
longer covers this post (client-facing autonomy is off for this business), so
it waits for your OK."
Its content and hash are unchanged, so the owner can approve it as it is.

**When Chief approves.** Once the week has settled (the design tick's
`tell_week`: no post of the run still designing, so a post whose flyer is
being made is never approved early; `marketing_approve` refuses a designing
post anyway). Then each draft of a covered kind that is as Chief meant it:

- a flyer post whose flyer is ready with **no note** to the owner (a flyer
  Chief's own check was unsure about, and a words-only post whose flyer
  failed or ran late, wait for the owner);
- a clip post whose clip is still the owner's kept clip, approved at the
  fingerprint the post carries;
- every account still connected, and none that cannot take it;
- due at least an hour from now, so there is time to take it back.

One RPC call per post (`marketing_approve` is all-or-nothing per call, so a
post that moved on never holds up the rest), `p_via 'standing'`, `p_actor` the
business's owner, at the revision and content hash read. A refused one (the
owner changed it meanwhile, its time passed) is left alone.

**Chief's log.** Each standing approval writes an `audit_log` row (verb
`marketing_standing_approve`, actor `chief`/`standing`, `authorized_by
standing:<kind>`, payload: post, run, kind, revision, content hash, time,
and the grant's `granted_at`/`granted_by`) and a `chief_activity` row for the
owner ("Approved on your standing OK: Monday 11:00 AM post", `nav
grow:marketing`).

**Telling the owner.** The week's one Today item and one push (keyed by the
run and attempt, as B9) say it: "Chief approved 5 posts for next week under
your standing OK" / "Review or take back any before they go out: each one
waits on the desk until its time. 2 more wait for your OK; nothing else posts
until you approve it." With nothing approved on a standing OK the words are
B9's and B12's, unchanged.

**Take back** (`POST /marketing/{business_id}/posts/{post_id}/take-back
{revision}`, owner only): an approved post, the owner's or Chief's, goes back
to a draft (the next revision, the approval dropped, its words, picture,
accounts and time unchanged). A post already claimed for sending answers 409.

**Ask after three** (Kevin's "approval earns permission" rule, D6). When the
owner's last three approvals of a kind were each of Chief's draft unchanged
and stood (not edited or skipped afterwards), Chief asks **once**: `POST
/approve` answers with `standing_offer` (`{verb, kind, count, question}`), and
one Today item (`action_payload.standing_offer`, key
`marketing_standing_offer:<kind>`) and one push say "Want Chief to approve
your weekly posts?" with the question. That it asked is remembered first
(`settings.autonomy.standing_offered[kind]`); if that cannot be written, it
does not ask. The owner taps to grant through the door; `grant: false`
declines. `GET /engine`'s `standing` keeps showing the open question until
it is answered. Only on the Solutionist plan with client-facing autonomy on.

**Retire after three.** When the owner edits, takes back, skips or marks not
sent the last three posts of a kind Chief approved on the standing OK since
the grant (by when each happened; one that went out, or that the owner posted
now, ends the run, as `outcome_ledger.retired_verbs` does), the permission
retires itself: `standing_permissions.revoke(..., via='retire')`, its other
waiting posts go back to drafts, and one Today item and push say "I'm back to
asking before your weekly posts". Checked after each of those four owner
actions, on the desk or by Chief at the owner's ask: B10's
`marketing_edit_post` and `marketing_skip_post` call the same `edit_slot`
and `cancel_slot_route`, so they count exactly like the owner's own. Chief's
Post now on an approved post is read as posted now (kept), not as an edit.

**A write that did not land is never reported as done.**
`standing_permissions._write_autonomy` now raises `WriteFailed` when the
business cannot be read (it used to write `settings` as just the autonomy
block over every other setting) or the write answers nothing (None on any
error, [] when no row matched). A grant then answers 503 with nothing on the
record; a revoke or a "no" answers 503 and the grant or question stands; chat
says it could not be saved. A retire is confirmed before anything follows:
the revoke must land and a fresh read must show the grant gone (a read that
fails then trusts the landed write). If not, no post is withdrawn and nothing
is said; it is tried again at the next override, and before Chief next
approves anything on that grant (`approve_run` retires first and does not use
it). The question is asked only once remembering it has landed; otherwise
it comes on a later approval.

**Read off the posts' own history.** Ask and retire never use a counter: they
read `marketing_post_events` (the database's snapshot of every insert and
update of a post, B3's trigger) for the kind's posts over the last 120 days
(`snapshot->>source`, JSON-path select, at most 1,500 rows), and
`approvals_from` works out each approval and what became of it: sent,
posted now, edited (changed or taken back while waiting), skipped, not sent
(the owner's mark), withdrawn (Chief's own, by its note), failed, pulled or
waiting. "Chief's draft" is the content hash once its flyer settled. A post
whose first snapshot is older than the window is left out. A history that
cannot be read asks nothing and retires nothing.

**What the desk shows.** `GET /engine` (owner and members) adds `standing`:
per kind `available` (and `why` not), `granted`, `since`, `active`, `held`
(why a grant does not cover posts right now) and `offer`. Only the owner
changes it. Posts already carry `approved_via`.

**No migration.** `kind` is not a column anywhere: grants, the declined
answers and the question asked live in `businesses.settings.autonomy`
(jsonb). `marketing_posts.approved_via` already allows `'standing'` and
`marketing_approve` already takes `p_via`
(`supabase/APPLY-2026-10-07-marketing-suite.sql`); `marketing_claim_due`
already sends a post with `approved_by` and `approved_via` set; the history
is B3's `marketing_post_events`.

No new Chief action, no new job, no new switch (`STANDING_PERMISSIONS=off`
stops these too), no frontend (F6 is the Solutionist view). Not yet seen
live: the `snapshot->>source` filter and the JSON-path select on
`marketing_post_events` through PostgREST (a 400 there reads as a failed
read: no question, no retire, never a guess).

## Solutionist's own desk on the suite (B15)

Step 5 of the marketing-suite plan
(`docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md`: D1-D3, B15 and "Kevin, by
hand" 5), 2026-10-08. Mission Control's Marketing desk stops being a separate
single-tenant system and becomes the desk for Solutionist's own business on
the suite every business uses: one posting path (Post for Me, through its own
connected accounts), one store (`marketing_*`), one planner. Behind
`MC_MARKETING_SUITE` (off by default). **Off, the Buffer desk above is exactly
as it was** (its tests run unchanged). `platform_suite.py` holds the
switches; `platform_marketing_suite.py` holds Mission Control's routes. No
migration.

### Which business is Solutionist's own

Today Mission Control finds it as the row with `settings.platform_books`
true under the signed-in owner's account
(`platform_console._find_platform_business`). The worker has no signed-in
owner, and `settings` is the owner's own JSON: any business admin can set
`platform_books` on their own row (the `businesses_admin_update` policy), so
the flag alone is not an identity a server-side grant can rest on. New env
`PLATFORM_BUSINESS_ID` names it, and **one predicate validates it
everywhere** (`platform_suite.state`, service-role reads, remembered 5
minutes, a failed read 1 minute): its row is readable, `platform_books` is
true, and its owner is the platform owner's user (the auth user whose email
is `PLATFORM_OWNER_EMAIL`, read by id as `platform_chief_authority` reads a
business owner's address).

| State | What happens |
| --- | --- |
| valid, switch on | the suite is **active**: everything below applies; the Buffer desk drains |
| valid, switch off | the Buffer desk as before; the suite's fan-out leaves the platform business out |
| unset or invalid (a tenant's id put in by mistake, a row not flagged, an owner who is not the platform owner), switch on | the Buffer desk and its Thursday job keep working exactly as before, a loud error is logged, and `GET /suite/status` and `/drain` say so in a plain sentence. The id gets nothing special (no level, no profile, no exclusion from its own desk) |
| unknown (a read failed), switch on | fail closed: neither desk takes anything new that minute (503 in plain words), neither loop plans the week that hour, nothing is the platform business |

Mission Control's routes also check that the row's owner is the signed-in
platform owner (`require_owner`) and refuse in plain words otherwise.

The same owner check now guards the two places that took the first
`platform_books` row on its own (B15 review): the public news page
(`public_site._platform_news_posts`, mysolutionist.app/news) and the Buffer
desk's flyers and numbers (`marketing_design.platform_owner`,
`marketing_engine._news`) read `platform_suite.books_business`: the validated
id, else the oldest flagged row whose owner is the platform owner. A tenant
that flags its own row is never it.

### What that business gets (the suite active, that id only)

- **The autopilot level** (the week, its clips, standing OKs) whatever its
  billing row says: `platform_suite.effective_row` reads it as `comp_tier`
  practice, in memory only, in `business_marketing.level_for`, the
  planner's business reads and `standing_permissions.marketing_eligible`
  (B13: a standing OK still needs Kevin's grant and client-facing autonomy
  on that business). Never from a request; never for another id (a tenant
  setting `platform_books` on its own row gets nothing).
- **Its own profile** (`marketing_profile.platform_profile`):
  `marketing_engine`'s AUDIENCE (or the desk's own audience words), SYSTEM
  (no hashtags, no address in a caption), the clock America/New_York
  (`business_tz` and the fan-out's `zones` both), mysolutionist.app as its
  site and landing page, "THE SOLUTIONIST SYSTEM" in its flyer footer,
  `max_hashtags` 0. The business rule of up to three hashtags stays for every
  other business.
- **Its own numbers** (`marketing_signals.platform_signals`): the platform
  desk's reads (`growth_summary`, `founder_offer`, the news page, site_events
  with no business, the Buffer desk's posts, plans and play results) with the
  suite's own posts and plan subjects added in, so a week posted on either
  desk counts and a news post told on either is not told again. A side that
  cannot be read leaves the posts unknown (never a quiet week).
- **Its own plays and rules** (`business_marketing_engine`'s platform half):
  the platform's problems, five plays and `_rank`/`fill_slots`, leaning on the
  results of both desks (`merge_scores`); facts from
  `marketing_engine.verified_facts`; captions held to the platform's checks
  (20-220 characters, no link, no hashtag, numbers only from the facts, a
  founding-seat post quotes only the founding price). `PLAYS` still lists the
  business plays only; a platform play's entry is found through it for the
  caption request and the flyer.
- **Its links on mysolutionist.app.** `business_marketing_links.site_for`
  answers the platform's own site: hosts `mysolutionist.app` and www, origin
  `https://mysolutionist.app`, so a post's short link is
  `https://mysolutionist.app/go/<code>` and its `tracked_url` carries the
  desk's utm tags. The apex `/go/` asks the Buffer desk's codes first, then
  (`follow_platform`) the suite's: redirected only for a post of the platform
  business whose `tracked_url` is https on mysolutionist.app, counted only
  for a person. That lookup is keyed on the id, not the switch, so a link
  already out keeps working if the switch goes back off. **Results** read the
  platform's own pages (site_events with no business) and its own leads
  (`marketing_leads`). Not counted here: signups (`businesses.attribution`),
  which the Buffer desk's results count and the suite's measures do not have.
- **The suite's fan-out includes it whatever `MARKETING_DESK` says**
  (`desk_scope` adds it, `desk_on_for` answers True). Its desk's own
  `plan_enabled` is still its switch for Chief's weekly plan, as for every
  business.

### Mission Control's routes

The business desk's own paths and answers under `/platform/marketing/suite`,
so Mission Control mounts the shared `BusinessMarketingDesk` with one
`request` prop (F7). Each calls the business route itself, so the business
desk's owner check runs too.

| Route | Same as |
| --- | --- |
| `GET /suite/status` | (new) `{on, ready, business_id, reason}`: which desk Mission Control shows |
| `GET /suite/engine` | `GET /marketing/{id}/engine` (level autopilot, America/New_York) |
| `GET /suite/ideas/next-slot`, `POST /suite/ideas` | the same |
| `POST /suite/approve`, `/suite/slot/edit`, `/suite/slot/cancel`, `/suite/post-now` | the same |
| `POST /suite/posts/{id}/not-sent`, `POST /suite/posts/{id}/take-back`, `PUT /suite/settings`, `GET /suite/results` | the same |
| `POST /suite/engine/run` | `POST /marketing/{id}/engine/run`, refused while the Buffer desk's plan for that week has a post approved or out |
| `GET /suite/preview` | `GET /marketing/{id}/preview` |
| `GET /platform/marketing/drain` | (new) the Buffer posts still to go out |

All are the platform owner's alone (`require_owner`); a tenant owner gets 403
before anything is read. Granting a standing OK is
`POST /agents/chief/standing` as for any business (Kevin, signed in to the
platform business).

### Buffer drains

While the suite is active nothing new goes to Buffer: the Buffer desk
refuses a new post (`POST /ideas`, a new `POST /posts`), an approval
(`/approve`), `/post-now` and a planned week (`/engine/run`) with 409 and
"Solutionist's marketing runs on the marketing suite now..."; Platform Chief's
Buffer-desk handlers (`platform_chief_marketing`: `new_post`, a new
`save_draft`, `post_now`, `run_week`, `replan_week`) say the same, and the
Buffer snapshot carries `suite`. Since B15b Platform Chief's `marketing_new_post`
and `marketing_post_now` tags go to the suite desk instead while it is active
(below). A post-now card refused while it is being prepared
is that action's own answer in the reply (`platform_chief_authority.dispatch`
turns a refusal from `propose` into `{ok: false, label}`), never the whole
reply's failure; that holds for any action whose card cannot be prepared. Editing, skipping, cancelling and pausing posts
already there still work. Posts approved before the switch are left to go
out: the minute job keeps sending them (logged "Buffer drain"), and nothing
in Buffer is ever cancelled automatically.

`GET /platform/marketing/drain` (owner, either switch state, reads the
platform tables only, no Buffer call): `queued` (approved, window open),
`sending`, `in_buffer` (handed over, still being checked every 10 minutes
while `BUFFER_API_KEY` is set), `unconfirmed`, `missed`, `drafts`,
`last_goes_out`, `paused`, `buffer_publishing`, `suite_active`,
`suite_problem` (why the switch is on and the suite is not), and
`safe_to_switch_off` (the suite active, queued and sending both 0), with one
plain sentence. A failed read is a 503,
never "0 left". Do not pause the Buffer desk to drain it: a paused desk holds
its approved posts.

### One loop a week

| Switch | Who plans Solutionist's week |
| --- | --- |
| off, or on without a valid id | `marketing_engine.engine_tick` (the Buffer desk), as before. The suite's fan-out leaves the platform business out once its id validates (`desk_on_for` False even with `MARKETING_DESK=*`), and the old job skips a week whose suite plan has a post approved or out |
| on, valid id (active) | the suite's fan-out (`marketing_tick`, kind week). `engine_tick` does nothing; the suite does not plan a week whose Buffer plan has a post approved or out (`buffer_week_live`; the owner's request is refused the same way) |
| on, unconfirmed | neither, that hour |

A read across the two that fails plans nothing that hour on either side.
With the switch on and its desk's `plan_enabled` off, no loop plans the week:
switching it on is part of the switch-over (below).

### Platform Chief

B15 shipped the smaller safe change: Platform Chief's marketing verbs stayed
on the Buffer desk's path for managing what is draining, and refused anything
new (above). B15b routes them through B10's desk verbs for the platform
business: see "With the suite on, Platform Chief and MC Today" below.

### Kevin's switch-over

1. In the practitioner app, signed in to The Solutionist System, connect its
   social accounts (Build, Social Media, Post for Me).
2. Set `PLATFORM_BUSINESS_ID` to that business's id (web and worker), and make
   sure `POST_FOR_ME_PILOT_BUSINESSES` includes it (or is `*`) and
   `MARKETING_DESK_PUBLISHING=on`.
3. Set `MC_MARKETING_SUITE=on` (web and worker). `GET
   /platform/marketing/suite/status` says `ready: true`.
4. Turn on Chief's weekly plan on the suite desk (`PUT
   /platform/marketing/suite/settings {"plan_enabled": true}` until F7 shows
   the switch).
5. Watch `GET /platform/marketing/drain` reach `safe_to_switch_off: true`,
   then set `BUFFER_PUBLISHING=off`.

Not built here: Mission Control's frontend on the suite (F7); signups in the
suite's results. (MC Today and the Mission Control Chief digest: B15b, below.)

Tests: `__tests__/test_platform_marketing_suite.py`.

### With the suite on, Platform Chief and MC Today

B15b, 2026-10-08 (`platform_chief_suite.py`). While the suite is active
(`platform_suite`'s one predicate: `MC_MARKETING_SUITE` on AND a validated
`PLATFORM_BUSINESS_ID`), Platform Chief's marketing verbs, MC Today and the
Mission Control Chief digest work the suite desk for Solutionist's own
business. **Switch off, nothing here is reached**: no verdict is read, the
suite's handler maps are empty (a suite-only tag is "This action is not
permitted." exactly as before, with no card written), and the post-now card,
Today, the digest, the prompt and the snapshot are the Buffer desk's own. The
existing platform marketing, Platform Chief, Today and digest suites run
unchanged. Switch on but the suite not active (the id unset, invalid or
unconfirmed): the shared verbs, Today and the digest stay on the Buffer desk as
B15 left them, and the suite-only verbs refuse in `platform_suite`'s own
sentence. No migration; no change for any tenant.

**Platform Chief's verbs.** Each calls B10's own handler
(`chief_marketing_actions`), which calls the desk's own functions: no second
write path, and every B10 rule holds (revision and content hash, the owner
check, flyer words, the level, "couldn't read").

| Verb | Group (`platform_chief_authority.GROUPS`) | B10 handler |
| --- | --- | --- |
| `marketing_desk` | read | `handle_marketing_desk` |
| `marketing_new_post` | drafts (as on the Buffer desk) | `handle_marketing_new_post` (`source 'chief'`) |
| `marketing_edit_post` | drafts | `handle_marketing_edit_post` |
| `marketing_skip_post` | marketing_stop | `handle_marketing_skip_post` |
| `marketing_replan` | review: a card every time | `handle_marketing_replan` |
| `marketing_post_now` | review: a card every time (as before) | `handle_marketing_post_now` |

- **Which business.** Always the validated platform business, read as the
  service role and checked against the signed-in platform owner
  (`platform_marketing_suite._platform_row`), never an id from the tag. A tag
  naming another business is refused before anything is read; a tenant's
  post_id reads as not found (B10 reads posts by business). B10's own owner
  check runs too: the turn's user is set to the platform owner for the call.
- **Class C.** Platform Chief's yes is the owner's approval on the action's
  card (model output is never consent there). Post-now and replan are
  `review`: whatever the owner's policy says, a card. Their handlers refuse,
  before anything is read, unless they run from a card the owner approved
  (`current_authorization`, automatic false): "Posting right away needs your
  approval on its card, so nothing was posted." B10's own `_unattended` gate
  is set from that, never from the tag (the tag's underscore fields and
  business id are dropped).
- **The post-now card** (`platform_chief_suite.post_now_review`, called by
  `propose`) freezes a desk post exactly as read (post_id, revision, content
  hash, words, accounts, picture) or a new post's words, networks, picture
  and link. On approval a desk post whose revision or content hash moved on
  is refused ("That post changed after its card was made"); otherwise B10's
  Post now approves it as the owner's and it goes out in about two minutes.
  A new flyer is not posted from a card (save it as a draft first). A card
  that cannot be made (no such post, a network with no account, another
  business) is that action's own plain answer.
- **Replan** keeps Mission Control's own one-loop rule (`POST
  /suite/engine/run`): a week the Buffer desk has live is not planned again,
  and an unreadable Buffer week plans nothing.
- **No approve verb.** `marketing_approve` is in no group and no handler map.
  The owner approves on the desk; the only other approval is B13's standing
  OK, which the planner applies itself.
- **Answers** keep Platform Chief's reply shape: `ok`, `label` (B10's
  sentence, with "Grow → Marketing" said as "Mission Control → Growth →
  Marketing"), `result` (the same), `title` (B10's short label) and the
  post's id, revision and status.
- **Buffer spellings** in a tag (`text`, `channels`, `run_at`) are read as
  B10's (`caption`, `platforms`, `when`). The Buffer desk's own verbs
  (`marketing_save_draft` edits, `marketing_edit_slot`, `marketing_skip_slot`,
  `marketing_cancel_post`, `marketing_pause`) still manage what is draining;
  `marketing_run_week`, `marketing_replan_week` and a new
  `marketing_save_draft` still refuse.
- **The drawer.** In the marketing context Platform Chief gets
  `platform_chief_suite.PROMPT` (the verbs above, no approve, the drain) and
  `snapshot`: the suite desk as B10 reads it (`desk_digest`: posts with
  post_id and revision), its link results, the founder offer, and what the
  Buffer desk still needs (`buffer_drain`, with post_ids for a skip). Each
  source that fails is named unavailable.

**MC Today** (`platform_today._marketing`) reads, for the platform business:

| Item | From |
| --- | --- |
| posts waiting for Kevin's OK; failed, partly sent, unconfirmed, paused, missed; a plan not written; no accounts; quiet | the business desk's own Today items (`business_marketing_desk.today_items`), in Mission Control's room (`growth`, nav `platform-growth`) |
| "Chief approved N posts on your standing OK" (the next one's time, take back) | approved posts with `approved_via 'standing'` still to go out |
| "A post was pulled before it went out" | posts `pulled` in the last 7 days, with the post's own reason |
| the Buffer desk's leftovers, titled "(Buffer desk)" | its failed, unconfirmed, paused-with-approved-posts and missed items (missed now says nothing new is approved there), plus approved posts that missed their window and will not go out |

The Buffer desk's waiting drafts are not asked about: nothing is approved
there now. A desk that couldn't be read is one item saying so ("couldn't be
read just now... not the same as nothing waiting"), for each desk.

**The Chief digest** (`snapshot.marketing`) is the business desk's
`chief_digest` for the platform business with `desk: "suite"`, `where`
Mission Control's, `approved_on_standing_ok`, `pulled_last_7_days`,
`buffer_drain` and those items in `needs_owner`; the system prompt carries
`platform_chief_suite.DIGEST_PROMPT` in place of the Buffer desk's.
`posts_readable: false` comes with "couldn't be read" first in
`needs_owner`.

**Prepare post / Flyer Studio.** The backend has no hand-off that makes a
Buffer draft: "Save to marketing" is `POST /platform/marketing/assets/from-chief`
(a copy into the Buffer desk's asset library, no post), and "Prepare post"
is frontend-only (Mission Control's `ChiefCreativeResults` stores the asset
id and opens the Buffer composer). With the suite on, the frontend should
hand the artwork to the suite desk instead: `POST
/platform/marketing/suite/ideas {"artwork_id": <the Image Studio artwork id>}`
(Mission Control's creative tools save artwork under the owner's
`platform_books` business, `platform_console._find_platform_business`,
normally the same row `PLATFORM_BUSINESS_ID` names; the desk's own
`build_media` refuses a picture of any other business).

Not built here: the frontend for all of it (the suite's post-now and replan
cards, Prepare post on the suite, F7); `GET /platform/chief/permissions`
still lists "Posting right away" as always reviewed, not planning again.

Tests: `__tests__/test_platform_chief_suite.py`.
