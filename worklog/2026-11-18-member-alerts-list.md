---
title: The member app's bell list — "Your alerts" on /my/notifications, and the bell's dot
date: 2026-11-18
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-18 night, on the approved Lumen member app redesign (v29, accent level 2): "level 2 and yes build the bell list and the i''m new here build it."'
status: shipped behind MEMBER_LUMEN (preview by default)
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "The bell's dot is not wired into the top bar: the Lumen top bar wasn't on main when this shipped. member_alerts.alerts_unseen(business, contact_id) -> bool is ready for it (cached 45 s per member; call it off the event loop, e.g. in serve()'s gather, and keep the answer for the bar like member_portal_threads.BADGE)."
  - "While church threads are closed for a church (CHURCH_THREADS), the list only has what member_push_sends can name a person for: announcements, live, new sermons, 'Someone prayed for you', plus chats. Event reminders, class nights, kids, groups, news and serving need threads open (church_thread_notes is the only per-member record of them)."
  - "Not in the list: youth posts (their room is their place; church_threads leaves them out too), a group chat set to Evening summary or Off (its evening note isn't kept), the leaders room before the member has a participant row in it."
  - "Checked with tests and a rendered screenshot only; not seen live (Lumen is preview-only)."
decisions:
  - "No migration: the last look is one church_thread_reads row with thread 'alerts' (the table has no check on thread; 'alerts' is never a note's thread). While that table is missing the dot stays hidden and the list still shows"
  - "Sources: church_thread_notes from the church for this member and the church-wide ones (threads open), else member_push_sends' church-wide kinds and prayed:<id> claims for their own requests; chats from msg_messages, one row per chat, only chats member_push.chat_recipients would tell them about"
  - "Their kinds: the church's switch per kind and not turned off by them; an office reply follows New messages only (push_reply's rule)"
  - "Privacy is the lock screen's: rows show the words member_push chose for the lock screen (title and line). A chat says 'New message' / 'New message in <group>'; an office reply says 'New message from the church', never its text"
  - "Who sees it: member_lumen.here() (serve() decides MEMBER_LUMEN once per page) and MEMBER_ALERTS_LIST=off as this list's own way back; off, the page is the old settings page and nothing is read"
  - "Opening the page marks seen off the page's path (the dot goes at once on that server copy); never in the owner's preview, never when the list failed to load"
  - "Times on the church's clock (group_gatherings.zone, else PLATFORM_DEFAULT_TZ): clock time today, Yesterday, a short weekday this week, else the date"
related: [2026-11-17-church-threads.md, 2026-11-18-member-lumen.md, 2026-11-18-member-app-cache.md]
---
member_alerts.py builds the list and the dot; member_push.render_page takes the rendered Recent section and turns the page into "Your alerts" with "What reaches this phone" above the old settings. Reads happen only on /my/notifications (in one gather with the page's own, each source's reads side by side in at most three rounds); no other page reads anything for it. Tests: __tests__/test_member_alerts.py (kinds, privacy, seen/unseen, switch modes through serve(), empty and failed reads, no reads elsewhere).
