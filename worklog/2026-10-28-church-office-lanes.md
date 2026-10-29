---
title: The office's lanes — each admin's login is set up by picking their lane (Office & Leadership, People & Care, Sunday & Serving, Media & Communications, Treasurer)
date: 2026-10-28
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-28: "will each setup be in aligned to the role itself. like we have 4 admins and responiblities for each" and "make these roles for admin so all i have to do is assign them to the person"'
status: shipped
prs: [kmj-intake-server#1632, solutionist-studio#1399]
migrations: []
left_undone:
  - "The lanes are the same for every church (from Love City's approved plan); a church can't rename them or make its own yet"
  - "A lane hides the other areas' pages from the menu; it doesn't lock them (seats by area, the areas plan's last step)"
  - "Chief keeps to the lane: its own PR (2026-10-28-chief-areas.md)"
decisions:
  - "A lane is a login and its areas, from the approved leadership plan (2026-10-27): Office & Leadership (Manager: Office, Messages & safety), People & Care (Manager: People & care, Kids & youth, Groups & classes), Sunday & Serving (Manager: Worship & media), Media & Communications (Manager: Worship & media, Website & outreach), Treasurer (Admin, since money opens only to admins and the accountant)"
  - "Giving a login its lane is giving it the lane's areas: an ordinary pick (business_users.areas), so the menu, the first page and what reaches the login follow it, and no new table or column is needed. The map names a login's lane when its pick is exactly one"
  - "An invite can carry a lane (POST /team/invite {lane}): the lane sets the role and the areas on the invited row, so the person's login is set up the moment they accept. A manager can't invite the Treasurer (an Admin), as before for admins; lanes are a church's"
  - "The Treasurer's lane isn't given to an existing login in Logins & areas: it's an Admin seat, given at the invite"
related: [2026-10-26-who-sees-what.md]
---
Changes:
- `church_areas.py`:
  - `LANES`, `lanes_view`, `lane`, `lane_of`, `lane_for_invite`;
  - `PUT /church/areas/login` takes `lane`;
  - new `GET /church/lanes`;
  - the map carries `lanes`, and each login's `lane`.
- `business_users_router.py`: `InviteBody.lane`. The invite sets the role and areas from it, and its email names the lane.
- Tests:
  - `__tests__/test_church_login_areas.py`: 2 new;
  - `__tests__/test_d_prb_roles.py`: 1 new.

Checked:
- These tests: 20 pass.
- Removing the invite's areas, or the lane's areas in the pick, fails a test.
- The team, areas, invite, seat, role, ownership, export, worklog, church and step-up subsets: 1,453 pass.
