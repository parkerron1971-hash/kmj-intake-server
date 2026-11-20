---
title: "Member app new look (Look 4.1) — See all posts: four on Home, the rest on the all-posts page"
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, on Home''s feed in the new look: "show 4 post and a show more tab where people can see other post from another page."'
status: in review
prs: ["kmj-intake-server (See all posts)"]
migrations: []
left_undone:
  - "Show more is a plain link to the next ten (?page=2), a page of its own; it doesn't fetch the next ten into the page you're on. It works with or without JavaScript, and Back to the newest sits at the top of page 2 on."
  - "The all-posts page reads the newest 80 posts for its first two pages (News' own read today) and 40 more for each page after, up to 400 (page 40). With a filter that matches few posts, older matches past that read aren't reached (as on today's News)."
  - "The count on See all posts is left off when Home's own read came back full (40 posts: more may be there) and when Home already shows them all. Today's birthdays aren't counted (they sit on Celebrating today and on the page's first page)."
  - "The page's tab bar marks Connect (News has always lived under Connect); Back in the bar goes Home."
  - "Not checked on a real phone: Playwright Chromium and WebKit at 390x844 @2x, reduced motion."
decisions:
  - "Behind MEMBER_LUMEN (member_lumen.page()). Off (and preview for a member who isn't the platform owner) is byte for byte main's: 767 page x scene dumps (the feed harness's 141, the Home harness's 288, this work's 338) identical to main. On, only Home (the row) and /my/news differ from main."
  - "Home keeps four posts. Under the fourth, See all posts replaces the feed's All news: a quiet full-width row with a hairline like the cards, 'See all posts', the count in grey and a chevron (member_lumen_feed.see_all). The count is church_news.home_view's, from the read Home already makes (count=, through member_portal._feed_previews): the posts the page lists, milestones and good news about a person included (Home leaves those to Celebrating today)."
  - "The page is today's /my/news in the new look (member_lumen_feed.all_posts; member_portal_news.serve hands over when the look is on): the heading and filters as before, then the posts as Home's feed draws them (member_lumen_feed.card: the reactions, the newest comments, the write pill, the poster's choice, an event's date leaf over its picture spot), pinned first, ten at a time, Show more under the tenth. Today's birthdays and anniversaries sit together on one card after what's pinned, on the first page only (News' 'Today we celebrate', drawn like the cards). Have good news? and the posting note stay at the foot."
  - "A card's forms come back to the page they're on without JavaScript (card(back=)): /my/news?page=2, the filter kept. member_portal_news._go keeps page=N (digits only) as it kept f=."
  - "Reads: church_news.feed_page is one read of the posts, the member's groups, and the decorations for this page's ten only, with whose authors are pastors read together (pastors_among: their roles in one read and the church's roles in one, not two reads for each new author); the church's clock once for the page. Harness, warm: /my/news on 56 reads on main (today's cards read the clock per label and decorate 40) to 14 here; page 2, 11. Home: 24 / 24 on, 28 / 28 off. Today's News and Home ask exactly what they asked."
  - "Words: 'See all posts', 'Show more', 'Earlier posts' / 'Back to the newest', 'That's every post.' Everything else is News' own words."
  - "CSS in member_lumen_feed.CSS (the hashed Lumen file, before the type block): tokens only (var(--bg), var(--fg), var(--lm-line), var(--acc)…), so dark mode draws it; the row's press colour waits for the phone's yes to motion. The old .lm-fall rule is gone. render_news' new-look branch (old cards restyled) is gone: the new look never reaches it now."
related: [2026-11-19-member-lumen-home-feed.md, 2026-11-19-lumen-home-top.md, 2026-11-18-member-lumen-people.md, 2026-10-23-church-news-feed.md]
---
`member_lumen_feed.py` holds the row (`see_all`), the all-posts page
(`all_posts`, `page_href`, `_today`) and their CSS; `card()` takes `back`.
`church_news.py`: `feed_page`, `page_window`, `page_count`, `pastors_among`,
`_decorate(batch=)`, `home_view(count=)`. `member_portal_news.py`: `serve`
hands /my/news to `_all_posts` under the new look; `home_block(total=)`.
Tests: `__tests__/test_member_lumen_all_posts.py` (17); the News test in
`test_member_lumen_people.py` moved to `feed_page`.

Before building, this repo's worklog had the feed (#1975) and Home's top
half (#1977); nothing on paging News.

**Measured** (harness over the test fake, so database time is about 0; main and this branch interleaved request by
request, median of 60 warm, Server-Timing total): Home on 8.4 / 8.7 ms (weekday), 9.7 / 9.4 (someone new); off
8.0 / 8.6, 7.8 / 8.0 (noise). /my/news on 8.9 / 6.9 ms, page 2 8.6 / 5.8; off 9.4 / 9.1. Page 1 78 KB (main's
News in the new look 75 KB with every post), page 2 70 KB.

**Checked** in Chromium and WebKit (Playwright, 390x844): See all posts opens the page, a comment posts in
place (Checking…, then the bubble), a reaction answers in place, Show more opens page 2, Back goes Home.
