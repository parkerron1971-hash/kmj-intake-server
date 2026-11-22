---
title: "Member app new look: read a plan with your group, and a reminder at your hour"
date: 2026-11-21
agent: Claude Code (Claude Opus 5.5)
asked: "Plans, step 4: read it with your group (pick On my own or one of the member's groups, stored; the day's together question gets a 'Send to <group>' button that opens that group's chat with the question in the box, unsent, the ?say= pattern; group and teen messaging rules as usual; optionally 'N reading this' if it's a cheap kept read) and reminders (a per-member hour, 'Remind me every day at 7:30 PM', through the existing member push and scheduler pattern, respecting quiet hours and the member's alert switches). Storage as an APPLY file; fail soft until it's applied."
status: shipped
prs: ["kmj-intake-server (this PR)"]
migrations: ["supabase/APPLY-2026-11-21-member-plan-prefs.sql (#2054; NOT APPLIED until Kevin runs it)"]
left_undone:
  - "The reminder has no box on Notifications: a member turns it on and off on the plan's page, and adding a kind to member_push.KINDS would change today's Notifications page and every church's settings. It still goes only where the church sends member alerts at all and stays quiet for a member who turned every alert off."
  - "The church's own reading plan (/my/reading) has no 'read with' or reminder row: the design draws them on a plan the member started."
decisions:
  - "member_plan_prefs (one row a member a plan): the group they read it with and the reminder time. Read through member_cache.Kept (30 s per member, keyed with the phone's plans version, which every save changes; 60 s per group and plan for how many read it with that group). Until the APPLY file is run the table isn't there (42P01 / PGRST205, kept 5 minutes as 'not applied yet', member_moments' rule): no row, no button, no line, every page as before; a write says it didn't save."
  - "Read with: On my own or one of the member's groups whose chat is open to them (member_lumen_watch.talk_groups: messaging on, the chat not off, everyone may write or they lead it; kept), as buttons in a form. The Plans tab says 'You're reading this with <group>' under Continue, with how many of the group read it with them; the day's 'For your group' gets 'Send to <group>': /my/groups/<id>/chat?say=<the question>, the box filled, nothing sent. The chat page applies its own rules (teens, who may write)."
  - "Remind me: a time on a quarter hour, offered only outside the church's quiet hours (texting_hours), on the plan's page once it's started. The sweep (remind_tick, on the clock every quarter hour, PLAN_REMINDERS=off stops it) sends at most once a day (reminded_on claimed before it sends), from the member's time to 45 minutes after, only while the plan runs today and today's day isn't read, never in quiet hours, never for a sample church, only where the church's member app sends alerts (push set up, a kind switched on), never to a member who turned every alert off, to the phones where they turned alerts on: '<church>: Day N of <plan> is ready: <day title>', opening the day."
  - "Both write routes: the member's session, same-site, the member-action rate limit, a plan they can read, a group of theirs, a time that's offered; only their own row; the plans version stamped."
related: [2026-11-21-lumen-plans-tab.md, 2026-11-21-lumen-plan-page.md, 2026-11-21-lumen-plan-day.md]
---
Read a plan with your group, and a reminder at the hour you choose, behind the APPLY file.

Checked: switch off and MEMBER_LUMEN=preview for a non-owner, 951 page x scene dumps each (Home harness 656,
Bible harness 295): same 951, differ 0 against main, both. Reads with the switch on, per page and table, in four
looks: Home harness 1920 / 1920 over 328 page-looks; Bible harness with the Plans pages and two day pages 1221 on main,
1216 here over 256 page-looks: no plan page reads more coming back (the member's choices, the group count and the
member's groups are kept); a first visit to a plan's page adds one member_plan_prefs read and the two small group reads
Watch already keeps; /my and /my/directory (500 in that harness) move with their 30-second feed cache. In a real browser
(Chromium and WebKit): On my own, Remind me at 8:15 AM and Off each saved through the page's own form and came back
saying so. Member suites with the Bible, devotional and export ones: 1783 passed. Shots before and after (Chromium and
WebKit, light and dark, 390x844 @2x, Love City's Consecrate Your Focus with a group and a 7:30 PM reminder) in the
session scratchpad's plans-build-shots/pr4/.
