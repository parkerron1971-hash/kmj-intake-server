---
title: Chief's church hand-offs go on History (cards, shared prayer, shepherd emails, the late chain)
date: 2026-11-09
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-09, on the 11-08 left-undone list (History missed the card, shepherd and prayer hand-offs): "ok make the changes for the left for later stuff."'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "Other church modules that act on their own still don't write History (none of church_checkin, devotional_daily (the daily text), church_news, church_event_signups calls audit_log). The pages promise History only for what you ask of Chief and these hand-offs, and test_church_site pins that. A first check-in's hand-off does go on History: it runs through church_follow_up.start"
  - "A hand-off that failed (a read failed, the save failed) writes no History line; only what was done is listed. The follow-up board and the office alerts still show those"
decisions:
  - "One helper, church_history.note(): actor_type 'chief', actor_id 'church' (HistoryPanel shows it as Chief), source 'church', best-effort and never raises. Six verbs, added to audit_log.vocabulary() and pinned equal by test_church_history"
  - "Any active seat reads History, a viewer included (audit_log._require_ledger_read). So a line names the leader it went to and the kind of card, and never who a card or prayer is about, what they wrote, or a family's name. Shepherd lines give counts ('asked to shepherd 3 families'), never families. The row links by its follow-up or care-request id only"
  - "Written where the thing was done, after it was done: church_follow_up.start (the hand-off) and its sweep (leader told, nudged, a day late, three days late); church_prayer.on_new (a shared request to a prayer leader) and its sweep; church_shepherding.tell_shepherds / tell_new_shepherd / tell_pastor; church_shepherd_signals.run_church (Monday digest, the chain above, the Lead Pastor's brief, care notices). A prayer request kept for the pastors is handed to no one and writes nothing"
  - "The home page's Chief section and People and Care now say History also lists each card, prayer request and shepherd email Chief hands on"
  - "On the PR review: two events stay neutral on History because their emails promise privacy. A care notice to a shepherd reads 'Sent Marcus Grant a note about a family they shepherd', and a shepherd's ask for a pastor (which goes to the Lead Pastor only) reads 'Passed a shepherd's note to Kevin McCloud'"
  - "A 'told' line is written once the email went out. If stamping the row as told then fails, the next sweep emails again and writes a second line: two emails, two lines, which is what happened (kept on the review's question rather than hiding the second email)"
related: [2026-11-08-home-rooms-and-week.md]
---
The 11-08 fact-check of the church home found that History (the audit log) never saw Chief's church hand-offs: church_follow_up, church_prayer, church_shepherding and church_shepherd_signals sent their emails and alerts without a ledger row, so the pages were narrowed to "what you ask of it". Now each hand-off writes one plain line as Chief, in words any seat may read, and the pages say so.

Each module's own test checks its lines and that the person, the request's words and the family never appear: test_church_follow_up, test_church_prayer, test_church_shepherding and test_church_shepherd_signals. A ledger that's down never stops a hand-off (test_a_history_line_that_fails_never_stops_a_hand_off). test_website_forms counts one more write per connect card: the History line.
