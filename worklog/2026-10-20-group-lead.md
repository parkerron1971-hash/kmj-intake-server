---
title: My group on the Lead tab — a group leader's whole group on their phone
date: 2026-10-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-20: "you can continue to work on things." Next from the approved canvas "Church Groups, Together" (board Lead: "You lead Sisters in the City. Good evening, Tasha.")'
status: shipped
prs: [kmj-intake-server#1537, solutionist-studio#1314]
migrations: []
left_undone: ["Chief drafting a note to each person who's missed three gatherings (the canvas's 'Send the 3 notes'): today the leader sees who, and with messaging on, a Message link for each", "the leader desk on a computer (the canvas's three-pane Desk board)"]
decisions: ["a group's leaders get the Lead tab even with no church role (member_portal), and it opens on their group; with a church role too, My group is the first segment", "this month: people and asking to join; came last time and going next; saw your pinned post (else your last post)", "Quick: Post to the Board, Take attendance on the day (Gatherings otherwise), Open video (an approved host) or Join the video, Group chat (Prayer wall when chat is off or messaging is)", "Needs you: Say yes / Not now right on the tab (it lands back here; any other back address goes to the group as before); who missed each of the last three gatherings and joined before them; that a request shared in the group went straight to a pastor this week (nothing to do)", "Chief's draft of this week's questions shows here too; Your last post with seen by, Got it and email counts", "a leader of several groups switches between them; an archived group isn't there", "wide Lead pages (this one and the existing ones) start after the 92px rail from 1100px instead of under it"]
related: [2026-10-20-church-group-space.md, 2026-10-20-group-gatherings.md, 2026-10-20-group-study.md]
---
`group_lead.py` (new): `led_groups`, `missing_lately`, `to_pastor_this_week`, `view`, `hello`, `render_body` + CSS. `member_portal_lead`: GET /my/lead/groups[/<id>] (`serve_groups`), My group in the segment, the Lead tab opening on the group for a leader with no church role, the rail fix. `member_portal`: the Lead tab for a group's leaders. `member_portal_groups`: Asking to join answered from the Lead tab lands back there (`_requests_block(back=)`, `_BACK_RE`).

Checks: 13 tests in `test_group_lead.py` (13 sabotages caught, including a leader with no church role missing the Lead tab in the bar, answers leaving the tab, newcomers listed as missing, an archived group, an unescaped name); 872 tests across the Lead, group and member files and the access ratchet. My group rendered and looked at at 390, 1280 and 1600.
