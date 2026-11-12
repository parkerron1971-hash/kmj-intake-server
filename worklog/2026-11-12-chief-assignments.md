---
title: Church assignments, PR D — Chief hands out work, reads it and moves it
date: 2026-11-12
agent: Claude Code (Claude Opus 5.5)
asked: 'give Naiya the lock-in room by the 20th; start Tiara''s first assignment; how is Laquesha doing?; move my weekly text to Thursday; I''m stuck on the policy, waiting on Pastor''s copy; mark the rooms one done; send Minister Ray the retreat sign-up list for Youth'
status: in progress
prs: ["kmj-intake-server#1806"]
migrations: []
left_undone: ["My week's from_office (PR C1) still has no frontend", "No Chief verb takes an assignment back (the board does); undo_last can't reach these verbs (no inverses registered)"]
decisions: ["The module is chief_church_assignments.py: chief_assignments.py is Chief's own outcomes worked over days, and a local branch named chief-assignments already held that older work, so this branch is church-chief-assignments", "Ten verbs, each calling the routes' own functions after the routes' own checks (church_assignments._allowed and _ready), so no office seat is over a pastor or an elder, the sent-up rule and the money-day rule hold as on screen", "Action tags, not native tools: WRITE_TOOL_SCHEMAS is also the outside agent's list and carries no signed-in person; registry chief_only; the three reads are mid-turn tools", "All ten in chief_areas.VERBS as everyone's own work (ALL): who may act for whom is church_over's, never a lane's", "send_handover is class C (an email to a person, no recall); the rest class A", "A write on a tainted turn is held in the handler, class A or C, until the person says it again", "People named by name, first name or a role word with a name (the role's title counts), looked up on the server among who this login may act for; assignments by words of their title, plural endings matching; none or several changes nothing and says which", "Receipts are whole lines: who, what, when, where it lands and who hears", "The turn's tail gets a short CHURCH ASSIGNMENTS block only where the switch is open for the church and the login has an office seat", "Review #1806: a read that brings in other people's words (titles, done when, notes, stuck notes) raises the turn's taint through chief_of_staff's sink, so every write later that turn is held; a read of only my own words (mine, or a ready-made's as it came) doesn't; untrusted_text unchanged", "Review #1806: a first assignment that lands in part says what landed and that asking again makes only the rest, never 'Nothing changed'; an email is promised only when there's one on file", "The tool loop's private-read allow-list names the three reads, so they really run mid-turn"]
related: [2026-11-12-church-assignments.md, 2026-11-12-church-assignments-done.md, 2026-11-12-church-handovers.md, 2026-11-12-church-lead-assignments.md]
---
PR D of `docs/CHURCH_ASSIGNMENTS.md`, after A (#1801), B (#1802), C1 (#1804) and C2 (#1805).

Built: `chief_church_assignments.py` (people_under, assignments_of, one_on_one, give_assignment,
start_first_assignment, mark_assignment, mark_stuck, send_up_assignment, set_my_day,
send_handover), wired into chief_of_staff (handlers, progress words, the turn's block),
action_registry, chief_areas, chief_tool_loop and the prompt's tag list. Tests at Love City,
Grace, New Hope and Riverside.
