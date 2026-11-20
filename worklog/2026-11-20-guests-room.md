---
title: The Guests room under People (This week and the Scorecard), read-only, behind the Welcome Path switch
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-20, on the Welcome Path mock (canvas WmRiSK8seJky8pJUK5nztE, boards Guests room and Numbers): "build". Builder 3 of 3: the Guests room and its scorecard, step 6 of the build order, built now so the other pieces have a home'
status: in review
prs: [kmj-intake-server (this PR), solutionist-studio (the Guests room)]
migrations: []
left_undone:
  - "Wave 2: the hold (a reply that stops the automatic texts until someone answers) is read if metadata.new_here.hold is set, but nothing sets it yet; the reply that waits today is an unread text from the guest"
  - "The Monday text is called the Monday note, not the pastor's note: signing it by the senior pastor isn't built"
  - "A guest's texts read 'skipped' when the scheduler finished the row and no outbound text sits within 10 minutes of its run (chief_scheduler keeps no reason for a skip)"
  - "The kids desk's family line is the check-in's own line (2 kids checked in), not the children's names"
decisions:
  - "Read-only: church_guests.py writes nothing, sends nothing, hands nothing on. GUEST_PATH off is a 404 on both routes, so the app hides the room"
  - "Who: business_access('manager') (the Follow-up board's floor) and People & care's areas: owner and admins always, every login while Who sees what is off, else church_areas.my_areas is the whole church or includes people_care; an unread view is a 503"
  - "A guest: new_here.texted_at, new_here.app.at, or a welcome follow-up (guest_path.is_guest_follow_up), once, from the earliest; texting the word again (visits >= 2) started when the record was made. Door: metadata.new_here.door, else the earliest signal's door (card_key text/app/checkin:first kids/web/form:*)"
  - "This week: New this week (met in 7 days), Came back (met in 28 days, came again in the last 7), Planning a visit (a Plan your visit card in 14 days, not come yet). A planned visit's first visit is its first check-in"
  - "Visits: the path's first day, then each later church-clock day with the guest's attendance row or a child_checkins row for a family they're an adult in"
  - "Connected = a group_members row in an active group of any kind (small group, team, class, ministry; Serve teams are groups) joined on or after their first visit, or an academy_enrollments row (active or completed) enrolled on or after it"
  - "Called within N days: the first note logged as reached (church_follow_up.REACHED: Talked, Left a message) within N days of the hand-off (assigned_at); N is settings.guest_calls.due_days (guest_calls.py's key), 2 unless 1 or 3. On time in the calls table uses the same window; calls go to whoever logged the first reached note"
  - "Next move, in order: a reply waiting (oldest), the longest-late open call at Reach out with a caller, anyone with no one (no leader or handed back), else calm, which says why (no guests, or cards not sent yet)"
  - "Texts this week: New here's queued rows for the next 7 days by step and day; an invite to a guest who checked in 20+ hours after their text is said to be skipped, by name, because that is new_here._came_back's own rule"
  - "What Chief did: the newest 5 church_history lines (audit_log, actor church, target a guest's follow-up), in their own words (they never name the guest)"
  - "Reads: every list a page at a time (1,000 at most per read, 20,000 at most in all); a core read that fails is a 503, never nobody; the texts, What Chief did and connected come back null on a failed read and the room says so"
related: [2026-11-14-new-here-guest-texts.md, 2026-11-17-guest-lane-new-here.md, 2026-11-17-guest-print-cards.md, 2026-11-19-member-im-new.md, 2026-10-26-checkin-welcome-handoff.md]
---
Before building I read both repos' `worklog/`: New here (texts, the guests'
lane, the print cards), the member app's I'm new here, first check-ins and
the follow-up board. Nothing had put every door's guests in one room.

`church_guests.py` (new): `GET /church/guests/{business_id}` (This week) and
`GET /church/guests/{business_id}/scorecard?period=month|season|year`, plus
`GET /church/guests/{business_id}/status` (the menu asks it once: the same
gate, no guest read), mounted
after the guest card in `kmj_intake_automation.py`. It builds on `guest_path.py`
(PR #2002, the Welcome Path's shared core) and reads what New here, the
follow-ups, check-in and Groups wrote.

Tests: `__tests__/test_church_guests.py` (34): every door once and no other
church's, the door and family line, the texts' steps, the call and status
line, the facts, a kids desk family coming back, a planned visit, the next
move in order, the side cards, the funnel, connected, by door and caller, the
church's call window, the periods, the read line, paging, failed reads (core
and side), the switch, churches only, the Manager floor and the areas, the
mount order.
