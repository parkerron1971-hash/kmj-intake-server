---
title: "Member app new look (Look 4.1) — Meet the pastor: the tile for someone new, a row on Connect, and the pastor's page"
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: 'For the Look 4.1 "Meet the pastor" tile, asked whether the app should get a pastor profile it doesn''t have yet, Kevin said: "yes add one."'
status: in review
prs: ["kmj-intake-server (Meet the pastor)"]
migrations: []
left_undone:
  - "The mock's 'Say hello after the service' line under the tile: nothing in the records says it. The grey line is the role's title."
  - "No bio, service times or phone number on the page: the app has none for the pastor. The note is the one place for the church's own words."
  - "The title is the church's own role title, as its tradition named it or as the church renamed it. A library default that reads as a list ('Rector, Pastor or Priest', 'Elders (Shepherds)') shows as it is until the church renames the role on its roles page."
  - "Send a message shows only when member messages are on and their rules let this member write to the pastor (both can message, no block, no teen and adult). The church's conversation and Ask the church aren't offered here: the page doesn't invent a new way to reach the pastor."
  - "A named member's note is checked (msg_screen) before it saves; the owner's is not (the church's own words, like the office's news posts)."
  - "Not checked on a real phone: Playwright Chromium and WebKit at 390x844 @2x, reduced motion."
decisions:
  - "Who: whoever holds the church's senior role (church_roles: job senior), the first by name when several share it, as church_follow_up hands a card to the senior role; the first version's 'pastor' key too. The name, and that role's title. No one in it: no tile, no row, no page (/my/pastor goes Home)."
  - "The picture: the church's new Pastor picture spot (member_app_pictures.LUMEN_FIXED, listed only where the new look shows; KEY_RE takes it), set with the same Change flow; else the pastor's own profile photo (member_photos, only when members may see it: an adult by birthdate); else their initials. A photo named 'pastor' in the library is not guessed at."
  - "The note: settings.member_portal.pastor_note {text, at, by}; no migration. Written on the page in edit mode (/my/pastor?edit=pictures) by the owner (their preview) and the people the owner named to change pictures (member_app_pictures.may_edit): POST /my/pastor/note with the picture route's checks (this church's address, same site, the session, may_edit, the per-person limit), cleaned (plain text, no runs of blank lines), up to 600 characters, empty takes it away, written to this church's row only, settings read right before the write. The church the app keeps for a minute is forgotten on that copy (member_cache.forget_church), so the page after Save shows it; picture saves now do the same."
  - "Where: Home's Also for you for someone new (they told the church it's their first time), after groups to join; prayer moves below as its row. Connect, for everyone: one quiet row by Directory and News (the face, the name, 'Your pastor · <title>'), so the page has a way in after someone's first week. Regular members see no tile on Home."
  - "The page: Back (history, else Home), the picture (4:3, the face kept in view; with no photo, the initials in a circle), YOUR PASTOR, the name in the serif, the title, the note in the reading face under a hairline, Send a message (/my/messages/to/<id>) when the rules allow. Editors see a quiet 'Change the picture or the note'; in edit mode the picture carries Change (the Pastor spot, coming back here) and the note is a box with Save."
  - "Reads: the pastor (roles, holders, records: three reads) is kept five minutes per church on each server copy. Home asks only for someone new, after what they told the church (already read inside Home's gather), so a regular member's Home reads nothing more, warm or cold; someone new's cold Home reads it once. Connect asks (kept). The page asks, plus member messages' own reads for Send a message only while messages are on."
  - "Look: member_pastor.CSS in the Lumen sheet before the type block; tokens only; the tile is member_lumen_home.tile exactly (picture with the corner icon, the small-caps label, the title, one grey line)."
  - "Behind MEMBER_LUMEN. Off is byte for byte main's (dumps below); /my/pastor is the unknown page it is today (to Home)."
related: [2026-11-19-lumen-home-top.md, 2026-11-20-lumen-see-all-posts.md, 2026-11-18-member-lumen-people.md]
---
`member_pastor.py` (new) holds who the pastor is (`find`, `who`, kept), the
picture (`picture`, `spot_default`), Home's tile (`tile`, through
member_lumen_home.tile), Connect's row (`row`), whether Send a message can
work (`may_message`), the page (`render_page`), the note's route
(`POST /my/pastor/note`, `clean`, `save_note`) and the CSS. Wired in:
`member_portal_lumen` (render_home's tile for someone new, `told_and_pastor`,
Connect's row), `member_portal` (/my/pastor, the Home gather, the Pastor
spot's Change page), `member_app_pictures` (the spot, back to the page, a
spot's own default, the kept church forgotten after a save),
`member_lumen_ui.templates()` (the CSS before the type block),
`kmj_intake_automation` (the router). Tests: `__tests__/test_member_pastor.py` (19).

Before building, this repo's worklog had Home's top half (#1977, which left
"Meet Pastor James" out for want of a pastor record) and See all posts
(#1978); nothing on a pastor profile.

**Checked.** Switch off: 995 page x scene dumps (the feed harness's 141, the
Home harness's 288, the all-posts harness's 338, this work's 228: pages x
Home scenes x a pastor with a photo, with the church's picture, and none)
identical to main as bytes; MEMBER_LUMEN=preview for a member who isn't the
platform owner, 228 identical. On: only Home for someone new, Connect,
Pictures, the Pastor spot's page and /my/pastor differ from main (the sheet's
address aside).

**Measured** (harness over the test fake, so database time is about 0; main and this branch
interleaved request by request, median of 60 warm, Server-Timing total): Home on 10.2 / 10.2 ms (a
member), 10.9 / 11.4 (someone new); off 8.9 / 9.3, 9.3 / 9.4; Connect 4.5 / 4.7, 5.4 / 5.5 (noise).
Reads: a member's Home 27 cold / 24 warm on main and here; someone new's Home 27 -> 30 cold (the
pastor's three, kept), 24 / 24 warm; Connect 7 -> 10 cold, 5 / 5 warm; the page 6 cold, 2 warm (the
harness stubs member messages' guardians and blocks: 4 warm in production while messages are on).

Shots (Chromium and WebKit, 390x844 @2x, reduced motion): the session scratchpad's
`lumen-more-shots/pr2/` (tile, the church's picture, initials, no pastor, a regular member, the page,
initials and no note, an editor's page, edit mode, the note box, the spot's Change page, Connect, Connect
with no pastor, Home's edit mode).
