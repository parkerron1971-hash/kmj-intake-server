---
title: ChurchSavvy's Media part, two fixes — a volunteer hears their clips are ready, and Go live lists the church's services (server)
date: 2026-10-26
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-26: "go with your picks, do the media fixes first"; "go ahead, you build step 2 after the media fixes" (the two left over from the Media part, kmj-intake-server#1563)'
status: in progress
prs: [kmj-intake-server#1601, "solutionist-studio#1367 (the app half; merge kmj-intake-server#1601 before it)"]
migrations: []
left_undone:
  - "Signing in from ChurchSavvy returns to /churchsavvy, not the address that sent you there, so a signed-out volunteer opening the email's link lands on Media's first part rather than Clips"
  - "Church Areas step 2 (the walls) is next"
decisions:
  - "A clip run started by someone with no office login (only a ChurchSavvy part) tells them by email, from the church's name, with a link to ChurchSavvy's Media → Clips. A volunteer can't turn on phone alerts (that's in the office's settings), so the push to grow:video-clips never reached them"
  - "The owner and anyone with an active seat still get the phone alert as before; if the seat read fails, the phone alert goes as before"
  - "Go live's \"Counts as attendance for\" is read by the server (GET /live/occasions, the same gate as going live), because a part has no seat to read Services & Events with; the office's Live page uses it too"
  - "Going live checks that the service it counts attendance for is one of this church's own active ones (it took any id before)"
related: [2026-10-23-churchsavvy-media-part.md]
---
- `clip_finder.py`:
  - `notify` sends a volunteer the email in place of the push;
  - new `office_login` and `tell_team_member`.
- `live_router.py`:
  - `occasions()` reads the church's services through `church_checkin`'s roster readers, from yesterday on, soonest first;
  - new route `GET /live/occasions`;
  - `live_start` checks `entry_id`.
- `__tests__/test_churchsavvy_media_part.py`: 6 new tests.
- `__tests__/test_live.py`: its fake database knows the service it goes live for.

Checks:
- `test_churchsavvy_media_part`, `test_live`, `test_clip_finder` and the access ratchet: 94 pass.
- I broke each fix on purpose, and a test caught all five:
  - no check on the service;
  - past services listed;
  - a failed calendar read shown as empty;
  - the push sent to a volunteer;
  - a failed seat read taken as "volunteer".
