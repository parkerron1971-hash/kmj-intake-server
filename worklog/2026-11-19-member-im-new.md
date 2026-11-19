---
title: I'm new here in the member app (the redesign's Connect "Your next step")
date: 2026-11-19
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-18, on the approved Lumen member app mock (Connect, "Your next step": "I''m new here — Tell the church you''re new, and get a simple path to find your place."): "the i''m new here build it"'
status: in review
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "The Lumen Connect tab isn't on main yet: member_im_new.new_here_card(business, ctx, request) (or card_async) is exported for its 'Your next step' slot, not wired"
  - "FE (solutionist-studio NewHereRoom.tsx): a guest with from='app' has texted_at null; the row says 'Texted ' with no day. It needs 'Told us in the app {day of app_at}' for those rows (and could show card.wants). Not built here"
  - "Shows only where MEMBER_LUMEN shows the redesign (preview by default: the platform owner's preview and own sign-in)"
decisions:
  - "Lane: Kevin's 'build it' on the approved redesign"
  - "No migration: the answers live on the member's own record, contacts.metadata.new_here.app {at, changed_at, first_time, heard, kids, ages, wants, prayer (a yes, never the words), follow_up}, beside the text New here's keys"
  - "Tags: a first timer 'first-time guest' (new_here.save_card's and text_room's), someone coming a while 'new here'. Tags are added, never taken off"
  - "The prayer is a confidential ministry_care_requests row (source 'Member app, I'm new here', share=False, church_prayer.on_new), as the New here card keeps one. The same words again are kept once. Crisis words get the 988 line, as Ask the church does"
  - "The follow-up: church_follow_up.start(kind connect, route_answers=[], what 'New here cards'), routed exactly as the New here card (the welcome role first, a pastor ask never re-routes it); card_key app:new_here, card_name 'New here (member app) card' (its own lane on the Follow-up board). source_event app-new-here:<contact id>, so the table's unique index keeps it to one per member ever. Saving again patches its answers and leaves a note; the same answers again write nothing. A member whose text New here follow-up is open gets a note on it instead of a second"
  - "Nothing is texted or emailed to the member. The leader hears through Follow-up as for any card"
  - "Your path: the academy program they're on (else a program's first open class, else any open class), groups taking new people (not invite-only, not youth, not theirs), serving (My serving if on a Sunday team, else open serving teams in Groups), Get baptized (Ask: life_event, opens on A baptism via ?pick=baptism) and Talk with a pastor (Ask: visit, ?pick=talk; else help). Only what the church has; a part that can't be read is left out. Their picks first; a pick with no door here says it was passed on, only when a follow-up carries it"
  - "Who: member_lumen.visible and MEMBER_IM_NEW (off = rollback, on when unset), churches, the Church space, adults (not a teen or a child). The owner's preview shows the pages and saves nothing"
  - "The card's 'has this member told us?' is member_cache.Kept: 10 minutes once told, 1 minute before, a failed read never kept (the card then says Start). Nothing else on any other member page reads anything new"
  - "The New here room (new_here.guests_of) lists them with this week's texted guests: from 'app', app_at, the answers as the card. One more read (their list) and, when there are any, one for their follow-ups; a failure leaves them out, never the list. counts_of stays the texts' numbers"
  - "Rate limit: member_im_new (6 an hour per member) on top of member_action, both fail closed; plus a per-member lock on each server copy"
related: [2026-11-14-new-here-guest-texts.md, 2026-11-17-guest-lane-new-here.md, 2026-11-18-member-lumen.md, 2026-10-27-member-asks.md]
---
Before building I read both repos' `worklog/`: New here (the guest texts, BE
and FE 11-14), the guests' lane (11-17), Ask the church and the member app
speed and cache work; nothing had built a newcomer step inside the member app.

`member_im_new.py` (new): the switches, `told_state` (kept), `clean`,
`answers_for`, `hand_on`, `keep_prayer`, `save`, the Your path parts
(`classes_part`, `groups_part`, `asks_part`, `path_rows`), the pages
(`render_form`, `render_path`, `serve`), POST `/my/new`, and the card
(`new_here_card`, `card_async`). Wired: `member_portal._serve_page` (GET
/my/new), `kmj_intake_automation` (the router), `rate_limit`
(`member_im_new`), `new_here.guests_of`/`counts_of` (the room),
`member_asks.render_care` (`?pick=`), `.env.example`.

Tests: `__tests__/test_member_im_new.py` (save, update-not-duplicate, the
prayer, routing, a text follow-up already open, preview, both switches,
adults and churches, failed reads, Your path, the card, the room, the rate
limit, the session). Screenshots at 390×844 were taken with made-up sample
data (not committed).
