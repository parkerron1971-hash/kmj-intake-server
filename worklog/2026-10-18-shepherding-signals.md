---
title: Shepherding, round 2 (server) — what Chief watches and who is told
date: 2026-10-18
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-17: drifting judged on Sundays only (never giving), any attendance counts, nobody flagged in the first month ("yes. i like plan"); the late chain applied to shepherds; the Chief section and Monday brief (canvas 31su6kdYmYecH5b2NxjBJN boards 4-5). Round 2 of the shepherding build, after round 1 (#1485) went live'
status: in progress
prs: [kmj-intake-server PR pending]
migrations: [supabase/APPLY-2026-10-18-shepherding-signals.sql]
left_undone:
  - "The office screens for round 2 (drift numbers, the rhythm panel, the no-Sundays-yet card, move rows in the proposal) are the frontend PR built against the same contract"
  - "A shepherd's \"they were there\" for someone who forgot to check in is not built; any attendance record (staff, kiosk parent, phone, online) already counts"
  - "New member: no separate notice when someone becomes a member; they wait as a family for the next proposal (and appear in the Lead Pastor's Monday brief as waiting), and their open Welcome card gets a note naming their shepherd when one is approved"
decisions:
  - "A recorded Sunday is a date on the church's check-in weekday (church_checkin settings; Sunday on the church's clock by default) with any attendance at all, so a Sunday with check-in off is nobody's miss. An occasion's own _checkin_day wins over when the rows were typed in"
  - "Drifting = absent on the 3 newest recorded Sundays and present on at least 2 of the (up to) 6 before; fewer than 5 recorded Sundays flags nobody. A family attends when any adult or member child in it does"
  - "Monday (07:00+ church time, once per church per week): new drift opens a signal and tells the shepherd; an open signal with no touch since its first missed Sunday and told 6.5+ days ago climbs one step of church_roles.chain_above (vacant roles passed over) and stops at the top; a touch stops the climb; attending again resolves it"
  - "Emails are planned first, sent (each key recorded in church_shepherd_notices), then the signals are written, then the week is marked, so a crash never double-sends and a rerun finishes the writes"
  - "Care need: the hourly sweep (not a hook in card intake) finds open care_need cards from the last 3 days for people in shepherded families and tells the shepherd once, naming who has it, never the card's words; not when the shepherd holds the card. A pastor's card shows as \"A pastor has this one.\" on the family page"
  - "The Lead Pastor's brief goes only when something needs them (drifting, a shepherd with 3+ families unreached, families waiting); only churches with at least one shepherded family are swept"
  - "Chief: church_people section=shepherding (owner/manager only, like care) with an optional name; draft_shepherd_moves writes move rows (from_shepherd_contact_id) into the proposal draft; approving reassigns and emails only the new shepherd"
  - "Family names keep the last name as written when one record has it typed all lowercase (McBride, not Mcbride)"
related: [2026-10-18-shepherding.md, 2026-10-17-sunday-checkin.md]
---
Round 2 of shepherding: Chief watches each shepherded family's Sundays and
tells the right person.

The migration (signals and a sent-once ledger) was rehearsed whole and
rolled back, applied, and probed again on a Love City household: a signal
opened, climbed, resolved and reopened, a notice, and eight bad rows
refused both times (a second open signal, another church's family or id,
an update onto another church's family, a bogus kind, level 99, an empty or
duplicate key). Both tables are server-only.

On Love City's real rows today there are no recorded Sundays in the last
12 weeks and no shepherded families, so the sweep passes the church by and
nobody can drift until Sunday check-in has run a few weeks.

Alarm rehearsed: removing the 2-of-6 guard turned two tests red; restored.
