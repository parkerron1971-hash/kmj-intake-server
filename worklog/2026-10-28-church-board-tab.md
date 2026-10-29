---
title: The member app's Board tab — the board's meetings, agenda, minutes, decisions and approvals, for the church's people on a board
date: 2026-10-28
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-28: "Please build step 2 (the board member''s yes from the member app ...) and then step 1 (a Board tab, with approvals inside it) ... build the Board tab for computers from the start and stay out of Home"; then "lets build the board tab"'
status: shipped
prs: [kmj-intake-server#1636]
migrations: []
left_undone:
  - "Read-only: a board member can't mark attendance, write minutes, move or second from the member app; the secretary does it in the office (Board & minutes)"
  - "Files on an agenda item show by name only (the office has them); the member app doesn't open the church's Documents"
  - "A board member's no on a check request is still the treasurer's, in the office"
  - "No email or push when a meeting is set or minutes go out beyond Board & minutes' own Send minutes email"
  - "Love City has no boards yet: the tab shows for nobody until the office makes one and adds its people (each with an email, for the approvals' codes)"
decisions:
  - "Who: the church's people on a board (church_board_members.contact_id, active, the board not archived), and only their own boards. Matched by person, not login: board members use the member app, not office logins (two ways in)"
  - "Minutes, votes and who came show once the secretary sends them for approval (or they're approved); a meeting still being written shows its agenda only. The decisions log follows the same rule"
  - "The tab follows CHURCH_BOARD (on only): members never see a Board tab before the office has Board & minutes"
  - "Last in the bar for a board member; one who also has Serve keeps Serve there (the phone's bar holds six) and finds the Board at the top of Serve and in a computer's sidebar"
  - "Computer-first: the Lead tab's list-and-file layout (340px list beside the meeting from 1000px); a phone opens on the list"
related: [2026-10-28-church-board-member-yes.md, 2026-10-28-church-money-levels.md, 2026-10-28-member-app-computer.md]
---
The Board tab at /my/board (member_portal_board.py): the next meeting with its time, place, video link and agenda, the earlier minutes it approves, past meetings with their minutes once sent, the decisions log with search (/my/board/decisions), who sits on the board and its quorum, and a row into the board's approvals (/my/board/approvals, from #1633) while check requests show in the member app. It reads Board & minutes (church_board.py) with a member's view: no pen, only their boards. Tests: __tests__/test_member_board_tab.py.
