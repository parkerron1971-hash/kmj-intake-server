---
title: "Member app new look (Look 4.1) — Home's feed, with comments under each post"
date: 2026-11-19
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin approved the Look 4.1 Home mock ("build this app") and earlier asked: "make sure the people can comment under news feed. i know who ever make the post can allow whether people can comment or not." This piece: the feed block on Home ("What''s happening at <church>"), behind MEMBER_LUMEN. The top half of Home and the devotional pages are other helpers'' pieces.'
status: in review
prs: ["kmj-intake-server (Home feed with comments)"]
migrations: []
left_undone:
  - "Love on a comment in the feed: the mock's '2h · Love · Reply'. Whether you loved a comment and how many did is a read of its own (church_post_comment_loves); the feed shows '2h · Reply', and Love stays on the post's own page."
  - "Reactor names ('Maya, Luis and 39 others'): not read for the feed (only the post page reads them), so the summary says how many people reacted ('7 people'), counted from the reactions Home already reads."
  - "Faces of who is praying under Prayers only, and the mock's '9 new since Sunday' / 'New since your last visit on Sunday': no read has them. The count is 'N new' (the bell's own count)."
  - "The bottom sheet with every comment (HomeComments): it would need the post's whole thread, a read of its own. The box is inline on each card; View all N comments opens the post's page."
  - "The mock's I'm coming / Details buttons on an event post: the card keeps today's event row (opens Events) and the post's own Sign me up."
  - "Home still shows the first four posts (as today's Home). More would read more (each post's author is checked for a pastor's role, a read per new author)."
  - "Posting from a phone (member_portal_write) is not in the new look; only its Comments and When choices are restyled (CSS only, white knob on grey). The line under Comments still says 'Members can comment…' for every choice; the mock's per-choice line would be markup."
  - "Black: Lumen is white-only on main (member_app_ui.base_of). The feed uses only the page's tokens and was checked with the mock's black tokens laid over the page; a real black base needs the foundation to define its tokens (incl. --lm-line)."
  - "A lost answer after the server saved the comment: the words come back in the box and a second tap would save it again (no retry check like instant send's)."
  - "Not checked on a real phone: Playwright Chromium and WebKit at 390x844, reduced motion."
decisions:
  - "The block is member_portal_news.home_block's new-look branch (member_lumen.page()), drawn by member_lumen_feed.home_feed; render_home is untouched (member_portal passes me, site and the new count to the block)."
  - "No read of its own: church_news.home_view(previews=True) asks the comment-count read for the words too (select id, writer, reply_to, body, created_at, newest first) and puts the writers in the same people read; seen marks come from the bell's own read. Today's look asks exactly what it asked before (a test pins the count read's address)."
  - "The church's clock is looked up once for the whole feed (member_portal_news.when_label(tz=)): every label used to cost a read of businesses and of practitioner_profiles. Home in the new look reads 26 → 22 (harness); today's look 26 → 26."
  - "The newest comments: the comment with the newest activity and its newest reply, one in; with no reply there, the comment before it too (church_news.preview_of). Held comments never show on Home (the post page still shows a writer their own)."
  - "A comment from Home: the same /my/news/comment route and the same checks, answered as JSON when the fetch asks (member_portal_news._comment_json): the same-origin check, the session, the per-person limit, the post's own visibility, comments open, the poster's choice, msg_screen. 'Checking…' shows at once; then the server's own bubble, or the page's held words, or the crisis words with 988 (role alert; the pastor is told, as today). Refused (the check down, comments off, closed, the preview): the words go back in the box with today's words why. Without JavaScript the form posts as it always did."
  - "Wording is member_portal_news': held is 'Thanks. A safety officer looks at this one before it shows.' (the mock's 'Thanks. Your comment will show once it's been read.' was not used); 'Comments are off for this post.'; 'Comments are off for this one. Tap Praying to let them know.'; 'Comments aren't open at <church> yet. You can still react.'; 'Every comment is checked before the church sees it' (shown while writing)."
  - "Prayers only: Love · Amen in the row, and the soft I'm praying button is the pray reaction itself (so the two can't disagree); its count line swaps with the tap (CSS)."
  - "Pictures: a post's own photos (one as a header, a tall one stays tall; two side by side; three and +N). An event post: the event's picture spot (member_app_photos.choose on event:<name>, the church's choice or a photo named for it) under a date leaf in the church's colour; with no picture there, the leaf alone. Nothing made up."
  - "Calm: white page, the card a thin line, no coloured fills; the church's colour only on the heading's short rule and italic name, Love, the write pill's send and small labels. Titles in the serif, plain (no accent word)."
  - "Switch off: 141 page × scene dumps (19 pages × 3 day scenes, 22 news pages × 4 news scenes, 8 poster pages) byte for byte main's. Switch on: only Home differs from main (and the sheet's name)."
related: [2026-11-18-member-lumen.md, 2026-11-18-member-lumen-people.md, 2026-11-19-member-lumen-moments.md, 2026-11-18-member-instant-send.md, 2026-10-23-church-news-feed.md]
---
`member_lumen_feed.py` holds Home's feed in the new look: the cards, the comment bubble (shared with the
comment route's JSON answer), the script that sends a comment from Home, and the CSS (in the hashed Lumen
file through member_lumen_ui.templates(), before the type block, every rule under body.lm; moves only with
motion allowed). Data: `church_news.home_view(previews=True)`, `church_news.preview_of`. Tests:
`__tests__/test_member_lumen_feed.py`.

Measured locally (harness over the test fake, database time ~0; median of 30 warm requests, Server-Timing
total): Home off 3.5–4.0 ms on main and here; Home on 3.4 ms main / 3.8–4.1 ms here (noise); a post 2.5 ms
both. Reads per Home: off 26 / 26; on 26 → 22. Home's HTML in the new look 40 KB → 58 KB (11.0 → 13.7 KB
gzip): four cards with their comments instead of one card and three rows.

Before building, this repo's worklog had the 2026-10-23 news work (shipped) and the Lumen pieces; nothing on
a Home feed in flight besides the parallel helpers (Home's top half, the devotional pages).
