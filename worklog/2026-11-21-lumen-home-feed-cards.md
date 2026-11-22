---
title: "Member app new look (Look 5.1): Home's feed ends with the church's own cards, and the older sections leave Home"
date: 2026-11-21
agent: Claude Code (Claude Opus 5.5)
asked: "Kevin's Home plan (2026-11-21, 'yes to everything'), gaps four and five. There's no feed at a church that doesn't post (Love City has 0 news posts): after the posts, fill it with the church's own records as cards in the mock's styles (the newest message, Pick up where you left off, the class Continue row, upcoming events with Going / Maybe / Share where those routes exist, the verse of the day with Share as a picture if a route exists), then 'You're all caught up'. Remove the older look's sections the mock doesn't have (Also for you, Coming up, Today, Your group, the home screen and Get notified cards, which move to Me, and Ask the church, which is on Connect). Today's look unchanged."
status: shipped
prs: ["kmj-intake-server (this PR)"]
migrations: []
left_undone:
  - "Maybe on an event card: /my/rsvp knows coming, serve and can't, nothing for maybe, so the card has Going and Share only."
  - "The owner's desk strip (good news waiting, held comments and posts, the church's first news) is the next PR; the poster's 'Post the church's first news' row stays in the feed until then."
decisions:
  - "The cards are member_lumen_feed.church_cards and church_block, drawn by member_portal_lumen.render_home after the feed (`news`), from what Home already read: no read of their own. The newest message (Home's library, never a sample) is a message card ('New message' while member_feed_more.message_of says it's new, else 'Latest message'), left out when a post carries it; Home asks home_feed not to put it in the stream (newest=False) so it sits after the posts as the plan orders it. Rows under it: Meet the pastor for someone new (member_pastor.who, which Home already reads for them; the tile went with Also for you, so the row keeps it), Pick up where you left off (the newest message the member started and hasn't finished, from Watch's place on their own record, member_lumen_watch.state: not the message on the card), and the class (member_portal_lumen.my_class: Lesson n of m · Continue, to /my/classes)."
  - "Events after this week (This week has the rest), at most three, never a sample, each an event card through the feed's own _event: the picture with its date leaf, the day and time, the title, where and how many are going, Going (POST /my/rsvp, coming), and Share where the event is public and the public events page is on (member_lumen_share)."
  - "The verse of the day on the ivory card (.lm-page), opening its chapter, with 'Share as a picture': the Bible's own verse share (member_lumen_bible.verse_share, contract 1, kind verse with its BOOK.CH.V id), whose sheet hands over the /my/story/verse picture."
  - "Then the church's own tiles when it saved some, and 'You're all caught up' (member_lumen_feed.end). Not when the news couldn't be read (the cards still show), and not twice when the feed already said it between what's new and what's been seen."
  - "Gone from the new-look Home: Also for you (the devotional is a moment, prayer a door, the message a card), Coming up (event cards), Today (the verse is a card, the plan lives in Bible), the message tile, Your group (groups are in the stories and Connect), the prayer row, and the foot cards. Installing the app and the Get notified nudge are on Me now (member_portal._lumen_me, the same two cards, each showing itself only where it can help; the review bot pointed out the nudge hadn't moved at first); Me's Notifications row and Ask the church were there already, and Ask is on Connect. The asks to serve and the celebrations (each wants an answer) moved above the composer rather than leave Home. Home stops reading the reading plan's days in the new look (nothing draws them), and stops building the foot cards."
  - "Dead code removed with them: coming_rows, reading_row, continue_row, group_rows (member_portal_lumen), member_lumen_home.tile / also / icon and their CSS, member_pastor.tile."
  - "CSS only in member_lumen_feed.CSS (the rows, the verse card, the end), through member_lumen_ui.templates(), order unchanged; every rule under .lm with the page's tokens."
related: [2026-11-21-lumen-home-stories.md, 2026-11-21-lumen-home-sunday-pass.md, 2026-11-20-lumen-share.md]
---
A church that doesn't post still has a feed: its newest message with Pick up and the class under it, its
events, the verse, then "You're all caught up". The older look's sections are gone from the new-look Home.

Checked: switch off and MEMBER_LUMEN=preview for a non-owner, 951 page x scene dumps each (Home harness 656,
Bible harness 295), main and this branch dumped back to back: same 951, differ 0 in both modes. Reads with the
switch on (warm), per page and table in four looks: Home harness 1984 -> 1956 over 328 page-looks, every
difference one read fewer on a page that draws Home (reading_progress: the plan's tick left Home); no page
reads anything new. Bible harness the same one fewer on Home, beside the group feed's known run-to-run noise.
Home's own first load: 38 -> 37 reads, warm 15 -> 14. Member suites with -n 2: 1678 passed (9 new in
__tests__/test_member_lumen_home_feed_cards.py; the old sections' pins rewritten for the plan's Home). Shots
before and after (Chromium and WebKit, light and dark, 390x844 @2x, full-page Home for the rich sample church
and a church with no posts, and Me) in the session scratchpad's home-build-shots/pr3-feed-cards/.
