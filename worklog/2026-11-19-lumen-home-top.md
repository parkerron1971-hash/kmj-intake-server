---
title: "Member app new look — the new Home's top half (Look 4.1): the greeting, Up next, Also for you"
date: 2026-11-19
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin approved the Look 4.1 Home mock and said "build this app". This piece: the greeting, the Up next card and the "Also for you" picture tiles, and Home''s layout. The Home feed with comments (member_portal_news.home_block) and the devotional pages are other helpers'' pieces.'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "Black base: the new Home draws right on the look's dark switch (body.lm-dark, checked on black), but nothing turns it on. The new look is still white for every church whatever its base (the 11-18 decision). Whether a church's Black base should turn the new look dark is Kevin's call, and it would be the whole app, not just Home."
  - "Faces of who's going (the mock's photos on the card, and its band of faces when a spot has no picture). Kevin hasn't decided whether members' photos may show to other members, and the new look shows numbers, never faces: '12 going'. A spot with no picture draws its default art."
  - "'3 people prayed for you' (the mock's prayer tile). The only count is the group prayer wall's 'I'm praying' marks on the member's own requests (group_prayer_marks): a read Home doesn't make. The tile is today's 'How can we pray for you?' entry."
  - "'Meet Pastor James' for someone new: there's no pastor record (name, photo, title) for the app to read. Someone new sees groups to join and prayer."
  - "The mock's 'doors open 10:00' and 'We'll save you a seat': nothing in the records says them. The card shows the room from the calendar."
  - "Not checked on a real phone: Playwright Chromium and WebKit 390x844 at 2x, reduced motion. WebKit on Windows draws Figtree at one weight (as before), so its shots read lighter."
decisions:
  - "Behind MEMBER_LUMEN (member_lumen.page()). Off is byte for byte today's look: 288 page x scene dumps (36 pages, 8 scenes) identical to main. On, only Home and the Pictures list (the new 'Prayer on Home' spot, and a spot's 'and on Home' note) change; every other page differs only in the sheet's hashed address."
  - "The greeting reads the church's clock (church_checkin.church_zone_name, from the church row in hand; New York when none): the moon from 5 PM to 5 AM, the sun otherwise; Good morning / afternoon / evening, It's Sunday on a Sunday, Welcome for someone who told the church it's their first time. The phone's-clock greeting script is no longer on Home."
  - "The sentence says only what the records say, facts in 600 weight, no chips: the gathering Up next features and when ('Young Adults is tonight at 7 at The Johnsons' home'), the church's next service ('Sunday is in 3 days'), where they serve and when to be there ('you're on Greeters at 9:45', the team's name and its call time). Sunday: 'Service starts at 10:30. You're on Greeters at 9:45.' Someone new: 'We're so glad you found us. Your first Sunday is Sunday at 10:30.' No records, no sentence."
  - "The service's day and time come from, first found: the check-in settings (the day and start time the office set; church_checkin.card, already read), Planning's schedule (worship_services, through My serving: sunday_serving.mine now also returns next_at; only someone on a team reads it), a calendar event on a Sunday named for the service (worship, service, sunday, mass). Calendar events carry their own time now when the date says one (member_portal_church.clock_of, 'HH:MM'; an offset time is left out)."
  - "Up next features one card: the church live > Sunday's service while check-in is open (its buttons are the check-in: I'm here, Watching online, Choose who; checked in: Welcome home and Change it; a check-in that didn't go through: today's full card under Up next) > someone brand new's first Sunday (Your path, to /my/new) > the sooner of their group's next gathering (within 7 days) and the next event, a tie to the group. While live with check-in open, the slim live bar carries Join and the card carries check-in; while live without it, the card is the live room and there's no bar. Nothing: today's welcome card (Watch a message, Read)."
  - "A group's I'll be there is the group's own RSVP (group_gatherings, /my/groups/meet/rsvp), now coming back to Home when sent from Home (back=/my). Who's answered is read once for the featured gathering (group_gatherings.answers), kept 30 s per gathering, forgotten by the member's own answer on that server copy, and read fresh on the page that comes back from it (?done=rsvp_*). Count: members of the group who said going, from two, as a number ('12 going', 'You and 11 others'). Chat when the church's messaging and the group's chat are on, else Open the group; a live group meeting gets Join; RSVPs that couldn't be read get 'Are you coming?' to the Meet tab."
  - "Brand new: they told the church in I'm new here (member_im_new) that it's their first time, and their first service since hasn't passed (the next service, when it's within a week of the day they told us); without a known service, for the week after they told us. Read through told_state, which keeps it (a read at most once a minute per member, every ten minutes once told)."
  - "Also for you: two picture tiles. A weekday: the devotional today (DAY n leaf, '6 min', 'Rooted · day 4 of 21', a progress line) and prayer; then serving this week, then the latest message. Sunday: serving today and the message (Today's message / Last Sunday / Latest message); then the devotional, prayer. Someone new: groups to join (open groups by name: 'Find your people') and prayer. The count pill is the card plus the tiles. What's a tile isn't repeated below."
  - "Pictures are the church's own spots (member_app_photos.choose): the group's (group:<id>), the event's (event:<name>), Home's top photo for the live room, the service and a first Sunday, the devotional's cover (its look, washed in the church colour unless the church chose), the serving team's group, and 'prayer', a new spot (member_app_pictures.LUMEN_FIXED, listed only where the new look shows; KEY_RE takes it). Edit mode (/my?edit=pictures): the frosted Change on the card's picture (a link) and on each tile (the tile opens its spot), as today's Home does. The spots' notes say 'and on Home' under the new look."
  - "Nothing is lost: under Up next the asks to serve and the celebrations; then Also for you; then the news block (titled by the feed helper); then Coming up (minus the featured event), Today (the verse, the reading plan, the devotional when it isn't a tile), the latest message when it isn't a tile, the church's own tiles (when it saved some), the groups not on the card, prayer when it isn't a tile, and the foot cards (install, alerts, Ask the church)."
  - "Reads: the same as today's Home on a warm page, off and on. On a cold page, two kept reads more, both inside the Home gather (no extra wait of their own): who's coming to the featured gathering (only when one of their groups meets on a schedule this week) and what a new person told us. The rest is read by what Home already reads: the groups read carries each group's regular time, chat switch and members (the select widened), Home's serving read hands over all of My serving (sunday_serving.home; waiting() is its asks, the same reads), the devotional read hands over the devotional itself (member_portal_devotionals.home_extras(info=...)), the check-in read hands over what the card was drawn from."
  - "Look: member_lumen_home.CSS joins the Lumen sheet through member_lumen_ui.templates(), before the type block, which stays last; every rule under body.lm. The church colour only on the leaf, the badges, the labels, the main buttons, the pill and the short rule; a 4% church tint on the card with a hairline and a soft shadow; no gradients, sky, countdowns, chips in sentences or left borders. Moves (a tile's press) only with the phone's yes to motion."
related: [2026-11-18-member-lumen.md, 2026-11-19-member-lumen-moments.md, 2026-11-19-lumen-next-motion.md, 2026-11-19-member-im-new.md]
---
`member_lumen_home.py` (new) holds the top half's pieces: the clock words, the
greeting and its sentence (`line`), which card is featured (`pick`), where the
service time comes from (`service_next`), who's brand new (`first_sunday`), the
card, the tiles, the live bar and the CSS. `member_portal_lumen.render_home`
lays Home out and builds the card and tiles from the church's records;
`next_gathering`, `groups_and_next` and `told` are its reads, run inside
`member_portal`'s Home gather.

Before building: both repos' `worklog/` had the 11-18/19 Lumen pieces (switch,
people, Bible and classes, give, fonts, motion, moments, I'm new here) and the
practitioner app's church Home; nothing on the member Home's top half.

**Checked.** Harness over the test fake (the moments harness plus the church's
clock, a scheduled group with RSVPs, serving, a devotional, picture spots and a
new person): `lumen-home/tools` in the session scratchpad. Shots at 390x844 @2x,
reduced motion, Chromium and WebKit, beside the approved frames:
`lumen-home-shots/side-by-side/` (day, scroll, Sunday, someone new, live, black,
no picture, edit mode, the picture page).

**Measured** (the harness over the test fake, so database time is about 0; main and this branch
interleaved request by request, median of 60 warm): off 8.0 / 8.0 ms, on 7.8 / 8.2 ms on a weekday,
7.7 / 8.4 on Sunday, 8.8 / 9.2 for someone new, 9.1 / 9.5 while live. Home's page 38 KB to 39 KB.
Reads per Home (harness): warm 15 / 15, off and on; cold 16 off, 18 on (the two kept reads).

Rebased on the feed (#1975): its CSS and this block both sit before the type block; this card's date
leaf is `.lm-leaf4` (the feed's event cards own `.lm-leaf`); Home still carries `mpn.RX_JS` once.

**Tests.** `__tests__/test_member_lumen_home.py` (20), and the three Home tests in
`__tests__/test_member_lumen_pages.py` rewritten for Up next.
