---
title: Guest Welcome Path (visitor flow upgrade)
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: 'upgrade the visitor flow: capture visitors, automated texts from the church, Chief hands the follow-up call to the People & Care admin or whoever the church assigns; then "by default the calls goes to people and care until we get a welcome team ... allow this to be selected by any church"; then "build"'
status: shipped
prs: [kmj-intake-server#2002, kmj-intake-server#2008, solutionist-studio#1658, kmj-intake-server#2005, solutionist-studio#1660, kmj-intake-server#2007, solutionist-studio#1661, kmj-intake-server#2012, kmj-intake-server#2013, solutionist-studio#1663, kmj-intake-server#2014, solutionist-studio#1665, kmj-intake-server#2015, solutionist-studio#1664]
migrations: [supabase/APPLY-2026-11-20-settings-server-keys-refresh.sql (NOT applied; staged in the SQL editor for Kevin's Run click)]
left_undone:
  - "Kevin presses Run on APPLY-2026-11-20-settings-server-keys-refresh.sql, then mark its ledger row APPLIED (prod still 42 keys at 22:40Z)"
  - "GUEST_PATH is unset = owner (the platform's own church); turning it on for every church is Kevin's call, on a Thursday, with a What's New entry and a church_findway.json re-export"
  - "Love City: New here is off and its texting registration unsent, so no guest texts or Text me boxes there yet; calls, the Guests room and the brief work"
  - "Kevin's call: a confirming reply before the welcome for yeses ticked on public forms"
  - "Kevin's call: whether any of the church's consent rows counts as a yes at the kids desk and welcome desk"
  - "group leaders who hold no church role get a People & Care note instead of a follow-up; Take a class has no stream"
  - "mock items not built: Tell Kids Club to expect the kids; week two's one-more-try call; replies to the shared number aren't held"
  - "New here's door writes (_keep, enroll, save_card) don't check hold_v; a write in the same moment as a reply could drop the hold"
  - "the Saturday heads-up claims in church_shepherd_notices (no table of its own)"
decisions:
  - "calls go to People & Care (first_guests) until the church has a Welcome Team (a role whose job is welcome) and the office says yes; each church can pick always People & Care, one person, or a team, plus rules and a backup"
  - "the call is due within 2 days at 6 PM church time; a day late the backup takes it; three days late the pastor is told"
  - "the Monday note is signed by the senior pastor; each church picks its own newcomers' event"
  - "after week one at most 1 automatic text a week, never more than 4 in any 7 days; a guest's reply holds every automatic text until a person answers"
  - "the call brief is built from the church's own records, no AI call; a prayer request is only ever named, never quoted"
  - "GUEST_PATH unset = owner; off is the rollback"
related: [2026-11-20-guest-path-every-door.md, 2026-11-20-who-calls-our-guests.md, 2026-11-20-guests-room.md, 2026-11-20-guest-path-weeks-two-to-six.md, 2026-11-20-guest-call-brief.md, 2026-11-20-guest-replies.md, 2026-11-20-settings-keys-refresh.md, 2026-11-14-new-here-guest-texts.md]
---
Mock: https://claude.ai/artifact/WmRiSK8seJky8pJUK5nztE (8 boards; Kevin
approved it and set four calls). Built the same day in seven backend and six
frontend PRs, all merged, all behind GUEST_PATH:

1. guest_path.py, the shared core (#2002).
2. Every door joins the texts with a carrier-worded Text me yes: kids desk,
   welcome desk, website card, guest forms, member app (#2008, FE #1658).
3. Who calls our guests (#2007, FE #1661).
4. The Guests room under People & care, with the scorecard (#2005, FE #1660).
5. Weeks two to six: two roads, the Saturday heads-up, the signed note, the
   weekly limit, and hold (#2013, FE #1663).
6. Chief's call brief, "How did it go?" and the next-step hand-offs, plus the
   card's four new questions (#2014, FE #1665).
7. A guest's reply reaches their caller and holds the texts (#2015, FE #1664).
8. The settings guard's list catches up for guest_calls, payroll and
   extra_storage (#2012). Its SQL isn't applied yet.

Each piece has its own worklog entry (see related). Read them before
changing the guest flow.
