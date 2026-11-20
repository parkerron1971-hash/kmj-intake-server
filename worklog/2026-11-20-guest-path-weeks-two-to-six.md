---
title: Welcome Path weeks two to six — the two roads, the Saturday heads-up, the pastor-signed Monday note, one a week, and hold
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-20, on the Welcome Path mock: "capture visitors, place them in a flow where they receive automated texts from the church ... top tier", then "build"; the Monday note signed by the senior pastor; each church picks its own newcomers'' next-step event. Wave 2, builder 4: weeks two to six, the Saturday heads-up, the signature, the one-a-week limit and the hold check.'
status: in review
prs: [kmj-intake-server#2013, "solutionist-studio: the Guests room path editor (its own PR, same day)"]
migrations: []
left_undone:
  - "Live only where GUEST_PATH lets it (unset = owner: the platform's own church) AND New here is on for the church (settings.new_here.on). Love City has New here OFF, so nothing here texts or heads-up there until it is switched on"
  - "Hold is only honored: nothing here sets or clears metadata.new_here.hold (a later builder does, when a guest replies)"
  - "Week two's 'One more try' call and 'Their next step has a person' (the mock's person steps) are not built: they're the caller's and the leaders', not texts"
  - "The kids desk's heads-up goes to holders of a role whose job is 'kids'; logins by the kids area are not read. A church with no kids role gets the kids' names in the greeters' note only"
  - "The heads-up claim reuses church_shepherd_notices (server-only sent-once ledger, PK business_id+key) with key guest-heads-up-<saturday>-sat, to avoid a migration. A table of its own would be cleaner if Kevin prefers"
  - "The sweep looks at up to 5,000 path guests across churches per tick (the last 50 days); more than that and the ones past 5,000 wait"
  - "Connected ends only the road texts (weeks two to six); week one's texts go as before"
decisions:
  - "New module guest_path_weeks.py; new_here.py: DEFAULTS/settings_of/NewHereIn/clean/put_new_here/overview extended, run_scheduled honors hold, the limits, signs the Monday note and logs each send. No migration: settings.new_here and contacts.metadata.new_here.path"
  - "Timing (church clock, moved inside texting_hours): first visit = path start (texted_at), or a Plan your visit guest's first check-in. W2 = first Wednesday >= first visit + 8 days. came back: the day of their first later visit, 3 h after that day's first check-in (attendance, or the kids desk for their family: church_guests' rule), never past auto_until-0:15, never within 30 min of arriving, gone when the day ends. not yet: W2 11 AM ('Thinking of you'), W2+14 11 AM ('Our door is always open'), each good for a day. both roads: W2+7 11 AM the church's picked Services & Events occasion ({event}, {when}), good until 3 h before it or a week; skipped when none is picked, it's gone, or it passed"
  - "Connected (church_guests._connected) ends the path: path.ended {why: connected}; a connected read that fails sends nothing that tick"
  - "Limits for every automatic text but the welcome: at most 4 in any 7 days (the welcome's 'Up to 4 msgs'); from 7 days after the path started, at most 1 in any 7 days counting texts after week one. path.log keeps each send's time (2 weeks; the text door's welcome counts at texted_at)"
  - "Hold: run_scheduled keeps a held week-one text in path.waiting {moment, action} and the sweep resumes it through run_scheduled once the hold clears; a road text stays due while held. Either is skipped with why (path.skipped, path.waits) once its moment passed by more than a day (a thank-you: past its own day)"
  - "Every write to the guest is a compare-and-set (guest_path_weeks.update): it lands only while hold, texted_at and path.claim are as read, else re-reads; a send is claimed (path.claim) first, a claim older than 15 minutes is never re-sent (skipped 'unsure')"
  - "Sweep: guest_path_weeks.sweep_tick every 15 minutes beside church_follow_up_sweep (leader-gated, sync on a worker thread), sample churches left out (exclude, drop_samples, skip), at most 30 texts and 20 heads-ups a tick, churches in shuffled order"
  - "Signature (settings.new_here.signature {on, name}, on by default): the church's name for it, else the senior role holder (member_pastor.who): 'Pastor <first>' when the role title says Pastor, else the name; none found = unsigned"
  - "Heads-up (settings.new_here.heads_up {greeters, kids}): Saturday 9 AM to 1 PM church time, once per Saturday; who may come = first visit in the last 14 days and not back (not connected), plus Plan your visit guests not come yet (card in the last 14 days; a date answer must be tomorrow); kids' first names from the kids desk, oldest first. Greeters = job 'welcome' role holders, else the first_guests Manager login(s), else the owner; kids desk = job 'kids' role holders, families with kids only. A holder who is a login: push + email (care_handoff.tell's way); else email. Nobody reached = the claim is let go"
  - "GET /new-here adds `path` only where the Welcome Path is on (signer, signer_from, events to pick, the picked event, when each goes, who hears Saturday, limits). PUT takes back/thinking/next_step/door_open/signature/heads_up as optional keys: an old client's PUT never sends them, so merge never touches them. next_step must keep {event} and {when}; a newly picked event must be coming up; no card link outside the welcome; no 'Reply YES' (START_WORDS)"
related: [2026-11-20-guest-welcome-path.md, 2026-11-20-guest-path-every-door.md, 2026-11-20-guests-room.md, 2026-11-20-who-calls-our-guests.md, 2026-11-14-new-here-guest-texts.md, 2026-11-14-texting-hours.md]
---
Weeks two to six of the Welcome Path, behind the same switches as week one.
`guest_path_weeks.py` reads each church's path guests with church_guests'
own readers (visits, connected), decides the one road text due for each,
claims it on the guest's row, reads the church and the guest again, and
sends it; it also resumes week-one texts that waited on a hold and sends
Saturday's heads-up. `new_here.run_scheduled` now honors hold and the limits
and signs the Monday note. Tests: `__tests__/test_guest_path_weeks.py`.
