---
title: "Member app new look (Look 5.1) — Home's feed: one stream, edge to edge, with your groups' posts and prayer requests"
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, on the Look 5.1 mock: "this is awesome. much better design. lets build this including the new still to build!" This is the feed part (helper B of seven).'
status: in review
prs: ["kmj-intake-server (Look 5.1 feed)"]
migrations: []
left_undone:
  - "No duration chip on the message picture: sermons keep no running time (supabase/APPLY-2026-09-30-sermons.sql has no duration column). The mock's '♡ 89 · 12 comments · 214 watched' line under a message is left out too: messages have no reactions, comments or watch counts."
  - "No 'Maybe' on an event (no storage for it), and no 'M from your groups': who answered isn't read per group. 'N going' is the event's own count."
  - "No 'Elena chose prayers only. Send her a note': a group's prayer request has no prayers-only choice (the wall has no comments at all), so the sentence wouldn't be true. The request shows the asker by first name, as the wall promises ('The group sees your first name'), not 'Elena Ruiz' as the mock does."
  - "A group's Board post has no Love, Praying or Comment: the Board keeps none of those. It shows who posted, the words and 'Open <group>' (the mock's group icon), and no 'Got it' (that would need the seen read). The pastors' word to every group (group_id null) isn't in the feed."
  - "'Loved by …' doesn't change in place when the member taps Love or double-taps; the heart button does. It is right on the next page."
  - "The group items and the newest message are Home's only; the all-posts page (/my/news) keeps the church's posts. A message a post carries draws in full on Home (it has the sermon library) and as a plain row on the all-posts page (no new read there)."
  - "Saved posts lists the 30 newest saved (the record keeps 100); no paging."
  - "The Home that answers 'I prayed' without JavaScript reads the group items fresh; with JavaScript the button answers in place. On another server copy the kept group items (30 s) can show the old state for up to 30 seconds after a reload."
  - "Not checked on a real phone: Playwright Chromium and WebKit at 390x844 @2x (touch for double-tap)."
decisions:
  - "Behind MEMBER_LUMEN (member_lumen.page()). Off (and preview for a member who isn't the platform owner) is byte for byte main's: 995 page x scene dumps (the feed harness's 141, the Home harness's 288, the see-all harness's 338, the pastor harness's 228), all identical as bytes, re-run after rebasing on #1985 and #1992."
  - "The stream (member_lumen_feed.home_feed): 'Share a praise or a prayer…' with the member's face (it opens /my/post, the members' composer from #1992: contract 2), a thin band, then posts edge to edge with a hairline between, no card frame. The heading 'What's happening at <church>' stays for screen readers only (the mock has none)."
  - "A post (card): face or the church's mark, 'Maya Brooks in Young Adults' for a group's post, the kind and time, Pinned, and '…' which opens the post. Photos full width (no frame, their own shape; a tall one 4:5; two side by side; three or more an album). Then Love · Praying · Comment and Save at the right, 'Loved by Ben and 6 others', the caption with the poster in bold (under a photo), 'View all N comments', the newest comment, and the write pill (Add a comment…) on /my/news/comment with its checking, held and crisis (988) answers exactly as #1975 made them. Amen and Celebrate leave the row (the mock's row) and stay on the post's own page."
  - "Prayers only: the post on the soft panel ('Please pray', its words in serif) with 'I'm praying' and how many are, then 'Comments are off for this one. Tap Praying to let them know.' Off and not-open-yet keep their lock lines."
  - "Double-tap a photo to Love it (pointer timing on a phone, dblclick with a mouse; a second double-tap doesn't take it back); one soft white heart; with reduced motion it only fades. The Love button stays the control; the photo isn't a link any more (a tap would have left the page)."
  - "'Loved by': the newest Love that isn't the member's, by first name (as the post's own page names who reacted), read in Home's own people read (church_news._decorate previews: the reactions read brings created_at, the lover rides in the contacts read). 'Loved by you' when it's only them; '· N praying' after it."
  - "The newest message (member_feed_more.message_of): the library's newest published message when it was preached in the last 7 days, not a sample, not already carried by a post. 16:9 picture (member_portal_sermons._art: the series' art, a photo named for it, or the poster) with a play disc, 'Light Has Come · Part 2 of 2', the title in serif, speaker and scripture, Watch (or Listen when audio only) · Listen · Share. No data-lm-media mark: the card has no player (contract 4 marks playable elements), the picture opens the message's page, where the mini player (#1989) carries it on; marking a link there made the mini player's script ride on Home with nothing to play. A post that carries a message draws the same."
  - "An event a post carries: its picture framed (the post's photo, else the church's picture for the event) with the date on a leaf, 'Saturday, Nov 28 · 9 AM', the event's title, 'Fellowship Hall · 12 going', the post's words, then Going: the post's Sign me up (/my/news/signup) or the event's RSVP (/my/rsvp, coming); 'Sign up' to Events for a paid sign-up; Full; '✓ Going' when they are. Share only when the church's public events page is on and the event is public (the occasion's `public`, which member_portal_church.upcoming_for sets with #1986; until that lands no event offers Share), with the event's picture only when the church's website already shows it."
  - "Share (contract 1, with the coordinator's addendum) is on church messages and events only, each with data-share-id (the sermon's id; the event's entry id) so the sheet can make Your story; _share hands them to member_lumen_share.link() when that module is there (#1986) and writes them by hand in its attrs() order until then: <a class=\"lm-share\" href=\"/sermons/<id>\" or \"/events\" data-share-kind data-share-title data-share-sub data-share-img>, the public page without JavaScript. Never on a member's post, a prayer request, or a post's photos."
  - "Your groups (member_feed_more.gather): the member's groups with their row embedded (group_members → groups: name, name display), then their Board posts and their prayer walls together (group_prayers with group_prayer_marks embedded), then the people on them; the last 14 days; the group page's rules (a word for leaders reaches leaders, a post for later waits, never a pastor card or an answered request, only the member's own groups). Home shows the newest two, merged by time. Kept 30 s per member (member_cache.feed, MEMBER_CACHE=off reads every time); a partial read isn't kept. The test fake learned these two embeds."
  - "A prayer request (prayer_card): 'Elena in Young Adults', 'Prayer request · 4h', the soft panel, the words in serif, 'I prayed' / 'You prayed' and 'N people prayed' with up to three faces. It is the wall's own mark: POST /my/groups/prayer/mark (group_prayer.mark, membership checked). The route now answers JSON for the feed's script (Accept: application/json) and goes back to Home at the request with back=/my; it forgets the member's kept items. The wall's own form is unchanged. The asker's own request has no button."
  - "A group's Board post (group_post_card): who posted by the group's name setting (a teen by first name), the words, 'Open <group>' to its Board."
  - "Save: POST /my/news/save toggles the post on contacts.metadata.member_saved (ids, newest first, at most 100), the record's updated_at guarding an office edit (as member_lumen_look.save), the member's own row only; signed in, same-origin (member_portal_church._signed_in), the per-person limit; a post they may see (church_news._live_post), or one already on their list; the owner's preview saves nothing. JSON for the script, else back at the post. The session's record carries the list (contacts_for_email/_phone select saved:metadata->member_saved: no read); saving forgets that kept record on this server copy. Saved posts: /my/news/saved (new look only; off goes to News), from a 'Saved posts' line on Me."
  - "Order: pinned first; then what the member hasn't opened, with the group items and the message newer than what they have; 'You're all caught up' (the mock's ringed check) and Earlier; then the rest. Home keeps four of the church's posts, plus the new message and two group items; See all posts under them as before."
  - "The group page (#1985, #1992) draws its members' posts with card() and its held post with _source/_picture/_words; those now wear the Look 5.1 card, and so does its Board card (member_portal_groups._lumen_post_card: the same header, words, Got it and the leader's tools), so the page reads as one stream. A held post: a gold edge, the shield note inside the 20 px padding, Take it down."
  - "Reads (harness over the test fake, by table): Home cold 38 → 42 (+group_members, +group_posts, +group_prayers, +contacts: the group items, once per 30 s per member), warm 24 → 24. /my/news 14 / 14, Me 1 / 1, Connect 5 / 5, a post's page 23 / 23 (warm). The church's clock is still read once for the whole feed. Saved posts (new page): 8 warm."
  - "CSS in member_lumen_feed.CSS (the hashed Lumen file, before the type block, which stays last): every rule under .lm, tokens only (var(--bg), --fg, --s1, --lm-line, --acc, --acc-fill, --on-acc, --lm-tint-12) except white on photos (the play disc, the heart, the +N veil). New classes are lf-* so they can't meet the six other helpers' blocks. Motion only with the phone's yes; reduced motion keeps the heart's fade alone."
related: [2026-11-20-lumen-see-all-posts.md, 2026-11-19-member-lumen-home-feed.md, 2026-11-20-lumen-dark-light.md, 2026-10-20-group-prayer-wall.md]
---
`member_lumen_feed.py` is rewritten to the Look 5.1 anatomy (card, message_card,
prayer_card, group_post_card, composer, saved_page; the comment line; the
script: comments, Save, I prayed, double-tap). `member_feed_more.py` (new): the
group items, the newest message, Saved. `church_news.py`: `_decorate` names the
newest lover (previews only). `member_portal.py`: Home's gather runs
`member_feed_more.gather`; the session's record carries the saved list; Me's
'Saved posts'. `member_portal_news.py`: `/my/news/save`, `/my/news/saved`,
`home_block(extras=, library=)`. `member_portal_groups.py`: the mark route's JSON
and back=/my; the group page's Board card and a member's held post wear the new card (the held note sits inside
the padding, clear of the gold edge). `member_lumen_connect.py`: the group page's posts edge to edge under its band.
`member_cache.py`: `feed`. Tests: `__tests__/test_member_lumen_feed_l5.py` (18);
the feed, all-posts and Home tests follow the new markup and reads.

**Measured** (harness over the test fake, so database time is about 0; main and this branch alternated, median of 30
warm, Server-Timing total): Home on 12.9 / 12.1 ms, cold (nothing kept) 13.1 / 16.0 ms (the four group reads, which
run beside Home's other reads); /my/news 9.9 / 8.6; Me 4.8 / 4.5; Connect 5.5 / 5.8. Off: Home 11.1 / 12.4 (noise,
same bytes), /my/news 13.4 / 13.4, Me 5.0 / 5.0. Home 69.7 → 72.8 KB.

**Checked** in Chromium and WebKit (Playwright, 390x844 @2x, touch), light and dark: double-tap Loves once and shows
the heart, Save and unsave in place, I prayed and back (the count moves 4 → 5 people prayed), a comment posts in place
(Checking…, then the line); without JavaScript, I prayed and Save come back to Home at the item. No console errors
(the harness has no /my/timing beacon route).
