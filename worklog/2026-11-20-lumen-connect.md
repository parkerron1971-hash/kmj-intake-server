---
title: "Member app new look (Look 5.1) — Connect and a group's page"
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, on the Look 5.1 mock: "this is awesome. much better design. lets build this including the new still to build!" This part: the Connect tab and a group''s page in Look 5.1 (posting by members is the next PR).'
status: in review
prs: ["kmj-intake-server (Connect and a group's page, Look 5.1)"]
migrations: []
left_undone:
  - "The Connect title has no messages button of its own: the top bar's bubble (with the unread count) is that button, and the top bar belongs to the shell's work. If the shell gives Connect the mock's large-title bar, the page's own <h1> moves into it."
  - "'N people praying this week' under the prayer card: nothing counts people praying across groups today (the wall counts prayers this month, per group). Left out rather than made up; the faces beside it go with it."
  - "'12 signed up' on the open class: the classes read keeps no sign-up count. Left out."
  - "Invite on a group's page: a group has no invitation to send (leaders bring people in from the office). Left out."
  - "A Board post's ... menu: a leader's Pin, Take it down and Send now stay under the post as on the Board (the mock's ... is a menu the app doesn't have yet)."
  - "Writing to the group: a leader goes to the Board's form, a member to the group chat (where it's open to them); members posting in their groups is the next PR."
  - "News is no longer a row on Connect (the mock's More is Your pastor, Events, Church directory). News stays a tap away from Home's feed (See all posts)."
  - "Not checked on a real phone: Playwright Chromium and WebKit at 390x844 @2x, reduced motion."
decisions:
  - "Connect, in the mock's order: 'Connect' and 'Your people at <church>'; Your groups (Find a group); Serving (My schedule); Classes (All classes); Prayer (Prayer wall); Find your people (See all); then Your next step (the 'I'm new here' card and the asks, kept: nothing else on Connect leads to them) and More."
  - "Your groups: a row per group with its picture (the church's own for the group, else a photo named for it, else its initials on the soft teal), when it meets next on the church's clock ('Tonight at 7 PM', the Classes page's words), else its own words for when it meets, and where. Meeting now first, then the soonest gathering, then by name; five, then See all. The badge is the group's real unread count: its chat's messages since the member last read it plus its unread notes from the office, the same counts Messages shows (member_portal_threads.counts, now with each group chat's own count from the same reads); no badge, a chevron."
  - "Serving: the earliest date the member is asked for or on, as a card with the day on a leaf, 'team · time' (the team's call time, else the service's), the place 'with' the others on the team that day by first name. An ask: I'll be there posts My serving's own yes (POST /my/serving/answer), Can't make it opens the ask (its 'can't that day' and 'other Sunday' answers). A date said yes to: You're on, and Can't make it opens My serving's sub flow. A cover already asked shows that, no buttons. More asks: one row under it."
  - "Classes: the class in progress (program, else title), 'Lesson n of m' (n = lessons done + 1) and the next lesson's title when its next class names one, else when the next class is; the bar. Then the first class open to join with when it starts and who teaches, and Sign up (the Classes page's own join, POST /my/classes/join)."
  - "Prayer: this week's requests on the walls of the member's groups (not answered, not for the pastors only, not taken down), never the member's own, each by first name as the wall shows them to the group, two read out in the serif, 'N new this week from your group(s)'. Pray for them opens the newest one's wall; Ask for prayer is /my/prayer (private, to the pastors). With none: 'How can we pray for you?', 'It goes privately to the pastors.' and Ask for prayer."
  - "Find your people: groups open to join (not full, not invite-only), two for someone already in a group, four for someone in none; the picture, the name, when it meets and how many are in it (counted from groups_for's own members read); Join (open) or Ask to join (a leader says yes) post the groups' own join (POST /my/groups/ask); Asked once they have."
  - "More: Your pastor (member_pastor: the face, 'Your pastor', the name and title), Events ('N this week' from Coming up's own list, else 'What's coming up'), Church directory (only while the directory is on, in Church, never in Youth)."
  - "A group's page: the group's picture across the top (its initials on the soft teal when it has none) with Back (Connect) and More floating over it (the shell's bare frame: no bar at the top on this page); the name in the serif; 'Members only · N people · Thursdays at 7 PM' (the group's own words when it has no weekly time); a few faces (photos only where members may see them) and 'Maya, Luis and 12 others'; Joined (You lead) and Chat; Posts · Events · Prayer · Members (the group's Home and Board, Meet, Prayer and People; Video while a meeting is open). More holds Members and Leave this group. Someone outside: the cover, 'Open to join' or 'A leader says yes' and when, who leads, Join or Ask to join, no tabs, no count (today's rule)."
  - "Posts: a leader's waiting requests and draft study first (as today), the next gathering on a card (the day on a leaf, when, where and the leaders' note, who's going), I'll be there (the group's own answer, which now comes back to the group's page when asked from there; asked anywhere else it goes where it always did) or You're going / I'm here / You're counted on the day, and Directions (a map of the group's street address, only when it has one; it shows only to the group). Bring something and the video room as today. Then the box to write (above). Then the Board's posts as Home's feed cards (member_lumen_feed's card classes), eight of them, pinned and the pastors' newest first; See all posts opens the Board. Opening Posts counts the posts it shows as seen."
  - "The other tabs keep their own content under the new head."
  - "Reads: Connect adds the prayer card's two reads (the requests, then the askers' first names), kept two minutes per church and set of groups on each server copy (group_prayer.recent), so a warm Connect reads what it read before (5); a cold one 19 -> 21. The unread counts are the top bar's, read for the page already (kept 15 s). A group's page reads exactly what it read before."
  - "Look: member_lumen_connect.CSS in the Lumen sheet before the type block; tokens only (the floating Back keeps its white plate over the photo); Light, Dark and Same as my phone; reduced motion drops the press."
  - "Behind MEMBER_LUMEN. Off is byte for byte main's (dumps below); /my/connect still goes to /my/groups."
related: [2026-11-18-member-lumen-people.md, 2026-11-20-lumen-meet-the-pastor.md, 2026-11-20-lumen-dark-light.md]
---
`member_lumen_connect.py` (new) draws Connect's blocks (`title`, `group_rows`,
`serving_card`, `classes_list`, `prayer_card`, `discover`, `more_rows`) and a
group's page (`cover`, `head`, `buttons`, `tabs`, `tonight`, `composer`), and
holds the CSS. Wired in: `member_portal_lumen` (`connect_data` reads the prayer
card and the per-group counts alongside the rest; `render_connect`),
`member_portal_groups` (the new look's head, tabs, Posts tab, Board cards and the
outside view; the Posts tab marks what it shows as seen; a gathering answer asked
from the group's page comes back there), `member_portal_threads` (`chat_unread`
fills each group chat's own count; `counts` keeps them), `member_portal_church`
(`groups_for` keeps how many are in each group), `group_prayer` (`recent`, kept),
`member_lumen_ui.templates()` (the CSS before the type block). Tests:
`__tests__/test_member_lumen_connect.py` (23); the Look 4 pins on Connect and the
group page (`test_member_lumen_pages`, `test_member_lumen_people`,
`test_member_pastor`) now pin Look 5.1.

**Checked.** Switch off: 1,396 page x scene dumps identical to main (this work's
harness, 445: the Home harness's 81 pages plus Connect, five groups and every tab,
under five scenes; the dark work's Home harness, 656, and Bible harness, 295),
with only the ids of chats a page creates masked. MEMBER_LUMEN=preview for a member
who isn't the platform owner: 445 identical.

**Measured** (harness over the test fake, database time about 0; main and this
branch interleaved request by request, median of 60 warm, Server-Timing total):
Connect on 7.6 / 8.4 ms; a group's page on 7.2 / 7.4, its Prayer tab 6.8 / 6.8;
off 8.0 / 7.8 and 6.5 / 6.7; Home 14.9 / 15.0 on, 14.6 / 15.5 off (noise). Reads:
Connect 19 -> 21 cold (the prayer card's two, kept), 5 / 5 warm; every group page
and tab the same as main, cold and warm, on and off.

Shots (Chromium and WebKit, 390x844 @2x, light and dark, the mock's frame beside the
build): the session scratchpad's `l5-connect-shots/pr1/` and its `side-by-side/`.
