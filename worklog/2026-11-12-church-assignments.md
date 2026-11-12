---
title: Church assignments, PR A — whoever is over people starts them, hands them work, sees it move
date: 2026-11-12
agent: Claude Code (Claude Opus 5.5)
asked: 'lets build what is missing; allow for the admin to pick days for work load that works for them; allow for Jessica to be able to hand out assignments to each of them as well; a way for churches to set this up in a general sense when they establish leaders over people'
status: shipped
prs: ["kmj-intake-server#1801"]
migrations: ["supabase/APPLY-2026-11-12-church-assignments.sql (applied 2026-11-12, the file as at 01ea57c0)"]
left_undone: ["PR B (weekly done, done / not yet / late, the one-on-one): 2026-11-12-church-assignments-done.md", "PR C: the Lead tab's assignments and Your people (mock to Kevin first)", "PR D: the Chief verbs", "F1 / F2 (frontend): My week's Your assignments and day picker; the board", "Not timed on production: no sign-in to call it with. The board is about 20 reads for a church of 7 logins and 12 leaders in the fake"]
decisions: ["An assignment is a task; the new columns only add duty, done_when, check_key, startup_key, stuck, raised and checked_at, plus raised_by (the email names who sent it up)", "Over is church_over, from the church's seats and leaders map: qualifying as church_map.chain_for climbs, walked down each person once, a person with an office login is their login", "A first assignment is the duties a login does of its own (the Executive Pastor's lane is its two, not the 25 it covers), or a person's switches", "The calendar check reads worship_services and Services & Events, not events (the activity log)", "The first-Monday report doesn't move; a monthly duty with a day stays monthly", "The grouped tell only where the switch is open, only for two or more in one sweep", "Review round 1 (#1801): the map never hands anyone an office login the office rule doesn't (no Manager or Member seat over an Admin); a money duty's day is the owner's or an Admin's to pick", "The top of every chain (the owner's email, the owner's person, senior-job and pastor_yes_roles holders) is never under anyone; a failed Auth read of the owner's email is a 503 (messaging_router.owner_email_read)", "kids_checked is evidence only; the sweep reads only open churches, only checks that can pass, page by page; a failed email or people read never claims a raise", "The migration's CHECKs and FKs are NOT VALID (PGlite check church_assignments_db.mjs, in CI)", "Claude's decision in the #1801 review (from Kevin's wish that the one over them be in control; Kevin hasn't ruled on the rule itself): once sent up, only whoever sent it up, whoever it went to, or someone over them clears it; done still works for the assignee and shows as resolved", "Review round 2: once sent up the assignee can't take it back either; those rules hold in the database (raised_at=is.null filters, 409); every read a write's answer needs happens before the write", "Claude's decision, round 2 (2026-11-12; Kevin hasn't been asked yet): only the owner's identity is never under anyone; senior-job and pastor_yes_roles holders (every elder at an Elders church) are under the owner only", "Known limit: an owner whose record carries another email and who holds no senior role can still show under an Admin"]
related: [2026-11-11-church-team-week-together.md, 2026-11-02-exec-pastor-oversight.md]
---
Kevin's review (artifact FDqG3nA3jBaNVaSzzviW5f) found every office login has duties and a week,
but nobody hands anyone a first assignment, and almost nothing knows when a job is done. This is
the backend for the general rule: whoever a church puts over people starts them, hands them work
and sees it move, and the people under them pick their days. The plan is
`docs/CHURCH_ASSIGNMENTS.md` (the spec, corrected where the code proved it wrong).

Built: `church_over.py` (under / is_over / above, from church_duties and church_map, never names
or title words), `church_startup.py` (31 templates and start), `church_work_checks.py` (ten
checks that tick items off), `church_assignments.py` (the routes but the one-on-one, picked days,
the raised tell and the hourly sweep), picked days read by My week's rhythm, the team page and
the Monday roll-up, the grouped hand-off tell in church_office_tasks and church_leader_tasks, a
`raised` line on My week, `CHURCH_ASSIGNMENTS` (off | owner | on, default owner), and the
migration. Tests run the rule at Love City, Grace Baptist, New Hope and Riverside.

Review round 1 on #1801 (seven findings, all fixed in the same branch): two security holes in
church_over (the map walk handed a Manager or Member seat an Admin's login, and the senior pastor
showed up under every Admin when his record's email wasn't his sign-in one), an always-passing kids
check, a raise lost for good to a failed email read, a sweep that could starve, the migration's
lock, and who clears a sent-up item (a rule the reviewer, Claude, decided from Kevin's wish that the one over them be in control). The reviewer's repros are tests now.

Round 2 (four more): the take-back rule once sent up, writes that read everything their
answer needs before they write, the stuck rule held in the database, and the rule that the
senior holders are under the owner only (Claude's decision, not Kevin's: he hasn't been asked yet). The migration was applied on 2026-11-12, the
file as it is at 01ea57c0 (not changed since).

Merged as #1801 (acaf213c) and deployed on 2026-11-12; the frontend is solutionist-studio #1522.

Before building more here: the response shapes the frontend uses are in the doc's "What the
frontend builds against".
