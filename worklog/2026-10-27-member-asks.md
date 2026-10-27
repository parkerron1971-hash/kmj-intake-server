---
title: Ask the church — members ask for a room, help, a visit, a life event or a pledge (server; switched to the owner)
date: 2026-10-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-27, after Rooms & spaces, Pledges & campaigns, the member directory and the church calendar shipped: "we need to create a path for members to be able to request these things from the church app as well"'
status: shipped, switched off (platform owner only until a Thursday)
prs: [kmj-intake-server (this PR), solutionist-studio (the office section and askRollout.ts, next)]
migrations: []
left_undone:
  - "Thursday switch-on: CHURCH_MEMBER_ASKS=on on Railway (it defaults to owner) and askRollout.ts OPEN_TO_EVERYONE in the app, the same day. Every ask stays off at each church until its owner turns it on"
  - "Room and pledge asks need their tables: supabase/APPLY-2026-10-27-church-spaces.sql and -church-pledges.sql (both NOT APPLIED at the time of writing). Until then those two asks are simply not offered"
  - "A life event register (weddings, funerals, dedications, baptisms) doesn't exist; life events land in Prayer & care as requests the office follows up on"
  - "Members can't take back a room ask or a pledge from the app; the office does (Rooms & spaces, Pledges & campaigns)"
  - "Members don't see a campaign's church-wide total, only their own pledge and what they've given toward it"
  - "Rooms only (kind room): the church van and equipment aren't offered to members"
  - "The bell entry is the whole church's (Chief + bell are still church-wide), so it carries no name for care and giving; phone alerts go only to the logins that handle each ask"
decisions:
  - "Lane: Build, under the Build item 'Love City leaves Subsplash (M-1)'"
  - "No migration. The church's choices are settings.member_portal.asks = {on: [room, help, visit, life_event, pledge, event], at, by}; asks land in church_space_bookings, ministry_care_requests and church_pledges"
  - "Care rows carry submission.kind help | visit | life_event (a contract: Prayer & care and the help-requests work read it), source 'Member app, Ask the church' (or 'Member app, Youth'), confidential yes, and the pick in need / visit / life_event. Never shared with the prayer team"
  - "Who and which church come from the member's session; the form's contact_id, business_id, status, kind and booked_by are never read. A room ask is church_spaces.book as a member-level request: status requested, kind use, contact_id the member, booked_by null"
  - "Members see free and busy only (booked times on the day they pick), never a title or a name; a clash is 'taken then', never what's there"
  - "Room asks need Rooms & spaces open for the church (CHURCH_SPACES, its owner switch read as 'the church's owner is the platform owner') and an active room; pledges need Pledges & campaigns open and a campaign that hasn't ended (a pledge Sunday often comes before the start)"
  - "Pledges keep church_pledges' rules (its amount check, one per giver per campaign, request_id): pledging again changes the amount of the one pledge. recorded_by is the member's own contact id (a member signs in as a person, not a login). Progress is the member's own paid gifts to the fund in the campaign's dates (church_pledges.progress)"
  - "Minors: a teen (13 to 17) or anyone member_directory.is_minor marks (a child on a family, a teen linked to a parent, a youth/kids tag) gets only prayer and help; help goes the youth way (pastors only, marked Youth). Kids, and an adult leader who switched into Youth, are sent back to /my. A read that fails is a 503, never 'an adult'"
  - "Rate limit: member_ask (6 an hour) and member_ask_day (15 a day), strict, on top of member_action"
  - "Who hears: room → the office; help, visit, life event → People & care; pledge → the owner, admins and the accountant. Owner and admins always; with CHURCH_AREAS on, also the logins whose areas are the whole church or include it. Phone alerts via push_notifications.send_to_user, the bell via notification_engine.create_urgent_alert (deduplicated per ask)"
  - "Switch CHURCH_MEMBER_ASKS = off | owner | on, default owner (church_keys' pattern): with owner, only the platform owner reaches the office routes, and members are served only at a church whose owner is the platform owner (read from Auth, kept ten minutes, a failed read is a no)"
related: [2026-10-27-church-spaces.md, 2026-10-27-church-pledges-recurring.md, 2026-10-27-member-directory.md]
---
Before building I read both repos' `worklog/`: nothing on members asking the
church. The pieces this rides are today's Rooms & spaces (#1606), Pledges &
campaigns (#1607) and the member directory (its minor rules and the office
section's pattern).

- `member_asks.py` (new): the switch, the church's choices, what each ask
  needs, the minor rule, the three member POSTs (`/my/ask/room`,
  `/my/ask/care`, `/my/ask/pledge`), the pages (`/my/ask` and one page per
  ask, in the member app's own look: each ask one card in a family colour,
  and after sending, a card that says what happens next in the church's
  name), the office's `GET`/`PUT /member-portal/{biz}/asks`, and who hears.
- `member_portal.py`: serves `/my/ask*`; Home gets an "Ask the church" row
  under prayer and Me a row in "Your church life", only when something is
  on (no read at all for a church with nothing on).
- `member_app_ui.py`: the ask pages light Home.
- `rate_limit.py`: `member_ask`, `member_ask_day`.
- `kmj_intake_automation.py`: mounts the router before the site catch-all.

Checks: `__tests__/test_member_asks.py` (27). I broke eleven rules on purpose
(minors ignored, every ask for a teen, the form's contact, the prayer team,
an ended campaign, the rate limit, asks on by default, the switch, who hears)
and the tests caught each one; the two that passed (no clash pre-check, a
title in the busy read) are held by church_spaces' own clash check and by the
page never printing a title. Looked at in a browser at 375px and 1280px, on
the black and the white base. The access ratchet, member portal, directory,
tabs, spaces, pledges and rate-limit suites pass.
