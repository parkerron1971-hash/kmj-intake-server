---
title: "Member app new look (Look 5.1): a message with no art of its own shows its YouTube picture"
date: 2026-11-21
agent: Claude Code (Claude Opus 5.5)
asked: "Kevin said the live app doesn't look like the mock. Love City's last eight Sunday services went into Watch as YouTube links with no series and no art, and every picture is a generated colour wash where the mock has real photos. Use the video's own YouTube picture wherever a message's picture is drawn in the new look: Watch's hero, the rails, Every message, a message's page, Home's message card, the moments, the share sheet and the story picture. Series art first, then the YouTube picture, then the wash."
status: shipped
prs: ["kmj-intake-server (this PR)"]
migrations: []
left_undone:
  - "Today's look (MEMBER_LUMEN off, or preview for anyone but the owner) is unchanged: its messages keep the colour wash. Only the new look asks for the video picture."
  - "The player on a message's page still loads YouTube's own frame (youtube-nocookie) when the page opens, as before; only the pictures moved onto our address."
  - "A YouTube Short keeps its side bars in the small picture (YouTube draws a tall video into a wide frame); church services are wide, so this didn't seem worth a special case."
decisions:
  - "The order is member_portal_sermons._art's: the series' own art, then the church's photo named for it (both unchanged), then the message's YouTube picture, then the colour wash. _art takes yt=\"small\"|\"wide\"; only new-look callers pass it (member_lumen_watch, member_lumen_feed, member_portal_lumen), so today's look draws exactly what it drew."
  - "The id is read from the link by sermons_public.youtube_id, the same parsing video_embed_src used (watch?v=, youtu.be, /live/, /shorts/, /embed/); video_embed_src now calls it, so the player and the picture always agree. Its output is unchanged."
  - "The pictures are fetched by our server, not the phone (member_yt_pictures, GET /my/yt/<id>.jpg and <id>-w.jpg). Why: Watch and Home draw a dozen of these on every visit; loaded straight from i.ytimg.com, each visit would tell Google the member's address before they press play. The page's Content-Security-Policy is only frame-ancestors, so neither choice needed it widened; serving them ourselves follows how the story picture already reads pictures on the server, and it lets the server do the two things the phone can't do well: cut hqdefault's baked-in black bars off (16:9 at the centre, so even a tall moment or a square tile never shows a bar) and know whether a video has a maxresdefault (it falls back to sddefault, then hqdefault) with no script."
  - "The address is signed (an HMAC over the name, customer_token.derive_key('member-yt-picture')), so the route serves only pictures our pages drew: the church's address never serves just any video's picture. Only i.ytimg.com is ever asked, with a checked 11-character id, at most 3 MB and 4 megapixels. No database read at all."
  - "Kept per server copy for six hours within 24 MB (a church may change a video's picture), a video with no picture remembered for ten minutes, a failed fetch never kept; the phone keeps each a day (public, ETag, 304)."
  - "Sizes: the small one (480x270, from hqdefault) on rails, rows and the share sheet's card; the wide one (up to 1280x720) for Watch's latest, a message's page and the mini player's picture, a series' top, Home's message card and tile, and the story picture."
  - "The picture draws over the message's own colour wash (an inline gradient on the picture's span, the same colours the poster used), so one that can't load leaves the wash, not an empty grey box. Markup is member_app_ui.photo's (mb-ph is-colour), so every place that lays out a photo lays this out; no new CSS."
  - "Home's Sunday moment uses the day's message's picture only when the church has no photo of its own (it used the default picture there)."
  - "The story picture (/my/story/message/<id>.png) reads the wide picture through member_lumen_share.picture_bytes (its sermon read now selects video_url, the same one read)."
related: [2026-11-21-lumen-tab-tops.md, 2026-11-20-lumen-watch.md]
---
Watch, a message, Home's message card, the share sheet and the story picture show a message's own YouTube picture
in the new look when it has no art of its own. One new route (GET /my/yt/<name>), no database read, no migration.

Checked: switch off and MEMBER_LUMEN=preview for a non-owner, 951 page x scene dumps each (Home harness 656, Bible
harness 295): same 951, differ 0 in both modes against main. With two YouTube messages added to the harness (one with a start time), today's look:
688 pages each, same 688, differ 0 off and in preview. Reads with the switch on, per page and table, in four looks: Home harness 1984 / 1984 over 328 page-looks (and with the YouTube messages, 1984 / 1984), no page differs; Bible harness every page that answers 200 the same, 1132 / 1132 over 224 (its Home is a harness crash on main and here alike, whose parallel reads vary run to run). Member suites: 1615 passed (test_member_yt_pictures: 40 new).
Shots before and after (Chromium and WebKit, light and dark, 390x844 @2x) in the session scratchpad's
watch-fix-shots/ (before-*, pics-*).
