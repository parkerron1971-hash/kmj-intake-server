---
title: Church threads — the member app's notes read like texts, and members write back
date: 2026-11-17
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-17: "the goal is not be a text message itself but using the app to push through as like a text", members "can respond and it not be an issue", then "group notifications for groups people are in specifically". "make this happen".'
status: in review
prs: [kmj-intake-server#1899]
migrations: [supabase/APPLY-2026-11-17-church-threads.sql (NOT APPLIED; Kevin applies it)]
left_undone:
  - "The office's screen is the frontend's (solutionist-studio), built against the /church-threads API in parallel. The office's phone alert opens nav 'operate:church-threads': the frontend has to map that page."
  - "Apply supabase/APPLY-2026-11-17-church-threads.sql. Until then everything stays quiet (nothing recorded, /my/inbox goes back to /my, status says open:false)."
  - "CHURCH_THREADS is owner by default: only the platform owner's churches. Turn it on for every church on a Thursday after Kevin has seen it."
  - "No header icon in the member app's top bar: the Home card and Me's line are the ways in."
  - "No release or remove for a held message in the office API (the contract has none). Held rows are only shown to reviewers, flagged held."
decisions:
  - "Kept in the inbox: announcements, live, sermons, events, classes, prayer, kids, news, serving, groups. Not group chat messages, not youth posts. A 'groups' note with no /my/groups/<uuid> url (the pastors' word to every group) is not kept."
  - "A url under /my/groups/<uuid> is that group's thread, whatever its kind (a group prayer's 'praying with you' lands in the group's thread)."
  - "The lock screen only changes once a row is saved: a closed switch, missing tables or a failed write leave the old lock screen and the old link."
  - "A church note's lock screen: the church's name, then 'title — body'; a title that is the church's name already (news alerts) isn't said twice."
  - "Minors: member_asks lets a teen ask the church for help, so a teen may write to the office too. Kids, and an adult who switched into Youth, go back to /my (asks' rule). The office's alert about a teen's message goes to the same office logins as anyone's."
  - "A held message (screen said harm) is saved held; only the writer sees it in the app, and the reviewers are told by a staff push with no name and no words. Reviewers = the church's safety officers (messaging_router team logins), or the owner while none are named. The same people see held rows in the office API."
  - "The office's reply pushes at once to the member's phones with the reply's words (like a text), titled with the church's name; skipped when the member turned 'New messages' off; the church's per-kind switch isn't needed; quiet hours don't hold it."
  - "No FK on church_thread_notes.contact_id: one stale id in a bulk insert (event sign-ups live in JSON) would fail the whole chunk."
  - "Pace is counted from saved rows (20 a day, 5 seconds apart), so it holds across replicas; the member app's own member_action budget sits in front."
related: [2026-10-27-member-asks.md, 2026-10-20-group-chat-inside-the-group.md, 2026-10-23-church-news-alerts.md]
---
Every note member_push sends to a church's members is now also kept in the
member's inbox in the app, so it reads like a text conversation instead of
a lock-screen blip that's gone once swiped.

- `church_threads.py` (new): the CHURCH_THREADS switch (off | owner | on,
  owner by default, member_asks' platform_church rule), recording (one row
  per person in same-key bulk inserts, or one church-wide row), the
  lock-screen text, the member-side reads, the staff alerts, and the office
  API: `GET /church-threads/{biz}/status`, `GET /church-threads/{biz}`,
  `GET /church-threads/{biz}/{contact_id}`,
  `POST /church-threads/{biz}/{contact_id}/reply`.
- `member_portal_threads.py` (new): `/my/inbox`, `/my/inbox/church`,
  `/my/inbox/group/<gid>` (members only, else 404), and
  `POST /my/inbox/church/send` (screened by msg_screen as group chat is).
- `member_push.py`: `_send` records after the ref claim and before the
  device lookup, and rewrites the payload for a recorded note; the morning
  delivery opens `/my/inbox` when everything that waited was an inbox note.
- `member_portal.py`: the routes, Home's card while something is unread,
  Me's "From your church" line.
- `kmj_intake_automation.py`: both routers, before the site catch-all.
- `account_lifecycle.py`: both tables are exported and deleted with the
  business, and skipped on import (they cite people and groups by id).
- `__tests__/test_church_threads.py`: 33 tests.

Before building more here: the frontend's office screen is the other half,
and nothing in the app shows the inbox until the migration is applied.
