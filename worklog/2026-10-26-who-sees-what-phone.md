---
title: Who sees what on the phone — business pushes reach who still opens the business; a church login hears its own week
date: 2026-10-26
agent: Claude Code (Claude Opus 5.5)
asked: "continue (after: yes go with your picks and build it… keep building after you show me)"
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone: ["the in-app bell and morning brief (notifications table) are still church-wide; the Home page change in solutionist-studio hides them for a limited login", "Chief's answers narrowed per person"]
decisions: ["no model call: the note is My week's first item and a count", "a morning with nothing for them sends nothing", "the owner, admins and a login that sees the whole church hear business pushes as before", "a removed seat's phone hears nothing (a fix for every business, not only churches)", "a read that fails sends as before"]
related: [2026-10-26-who-sees-what.md, 2026-10-26-serve-tab.md]
---
Continuing Who sees what (canvas https://claude.ai/artifact/99aFvCSRXU1x9pmqUcncoP), Build
item "Church areas and keys". The login-areas migration from #1593 is applied (SQL editor,
2026-10-26; ledger updated here).

A business push (`push_notifications.send_to_business`: the morning brief, a new booking, a
new email, a store order) went to every device carrying the business id. Two things wrong
with that: a seat that was removed kept its subscription and kept hearing everything, and on
a church a kids director's phone heard "2 new leads · 1 overdue invoice" every morning while
her app showed only Kids. Now `_who_hears` keeps the owner's and the active seats' devices,
and `church_morning.limited` leaves out a church login that works only some areas (Church
Areas on). Each of those gets one morning line of its own (`church_morning.notes`, from the
morning tick): the first thing in its week from `church_my_week.build` and how many more, on
its devices on that church, opening on My week (`operate:my-week`). `send_to_user` gained
`business_id` so the note doesn't reach the person's devices on another business.

Shipped: merged and switched on 2026-10-26 evening (Kevin set CHURCH_AREAS=on on kmj-intake-server and kmj-intake-worker; checked both read exactly on; the worker redeployed 20:09 EDT).
