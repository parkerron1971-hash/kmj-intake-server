---
title: "Member app new look (Look 5.1): a pastor or a leader posts their own moment"
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin on the mock "Next: a pastor or leader posts their own moment": "i like it lets do it"'
status: shipped
prs: ["kmj-intake-server#2016 (the tables: APPLY-2026-11-21-church-moments.sql)", "kmj-intake-server (the moments: member_moments.py)"]
migrations: [supabase/APPLY-2026-11-21-church-moments.sql (NOT applied)]
left_undone:
  - "Apply supabase/APPLY-2026-11-21-church-moments.sql. Until then nothing shows and nothing posts: every page is as before."
  - "Video: media_kind is 'photo' only; the column is ready for 'video' (a check change plus an upload path)."
  - "Replies are not counted on the poster's sheet: a reply is an ordinary private message started from the pill (/my/messages/to/<poster>), and nothing ties it to the moment. The sheet says 'Replies come to your Messages' with no number."
  - "Mission Control: removing a moment from the office is a later piece. The held list's rows carry kind 'moment' for a frontend follow-up to say 'moment' (today the held list shows the line and the poster's name)."
  - "An ended moment's photo stays in storage (a taken-down one is deleted). A sweep could clear ended ones later."
  - "Not checked on a real phone: Playwright Chromium and WebKit (Windows) 390x844 @2x, light and dark, reduced motion."
decisions:
  - "Who posts: church_news.can_post, asked fresh on the composer and every POST: pastors and picked posters to the whole church or a group they lead; a group's leader to their own groups only. Home decides the circle from what it has: the church's pastors and picked posters (one read set kept ten minutes per church) and the member's own groups (Home's groups read)."
  - "How long: a day (default), until Sunday (the end of the church's coming Sunday on its clock; tonight on a Sunday), or 3 days. The table allows seven days and two hours, because 'Until Sunday' posted on a Monday runs almost seven."
  - "The check: msg_screen on the line; 'harm' and 'self_harm' hold it (only the poster sees it, with 'A safety officer looks at this one before it shows.'; self_harm also tells the pastor through Prayer & care and shows 988). It joins church_news' held list (kind 'moment'); Let it through shows it for its time left, Keep it hidden takes it down. If the check can't run, nothing posts. The photo is checked and kept as a News photo (member_portal_write._photos)."
  - "A group with a teen in it gets no moment, the members'-posting photo rule mirrored: a moment always carries a photo, and member_posts refuses photos in a group with a teen (same ages: member_posts._as_posting). The words are the same: 'Photos can't be shared in a group with teens in it.'"
  - "The button is picked from this week (Sunday's service, an event, a gathering of the group the moment is for) and drawn for each member from Home's own This week records, posting to the same routes. A member it isn't for sees none."
  - "Home's row: one circle a person, their moments newest last; a pastor's derived moment (today's devotional by name, or their recent post by id) joins their circle; their own circle first, then pastors', then the derived word if it didn't join, then other leaders', then Sunday, groups and events. Leader moments never have Share. Reply only where member_pastor.may_message allows (kept ten minutes, as Home's pastor moment)."
  - "Seen: one row a member a moment, written once (ignore-duplicates), from the viewer only for leader moments; the phone's own seen rings stay. Love: one upsert (merge-duplicates), the viewer's script sets on/off before Home's reaction script sends it."
  - "Take it down: its poster, a pastor (fresh), or the church's owner (their preview, or settings.church_owner_contact_id). A pastor or the owner sees a trash button on others' moments in the viewer."
  - "Fail soft: a 42P01 / PGRST205 answer is kept five minutes per replica; Home then asks nothing more."
related: [2026-11-20-lumen-home-look-5-1.md, 2026-11-20-lumen-member-posts.md, 2026-11-20-lumen-tidy-ups.md]
---
`member_moments.py` (new) is the whole piece: the reads (the church's moments
kept 30 s, its pastors and picked posters kept ten minutes, the member's own
marks, the poster's counts), posting, seen and Love, taking down, the held
list's rows, the photo route, the composer (`GET /my/moment/new`), the row
with circles of several slides and its viewer script, and its CSS (joins the
Lumen sheet before the share sheet; member_mini stays at len-2, fonts last).
Wired in: `member_portal` (Home's gather, the composer and photo routes),
`member_portal_lumen.render_home` (the circles, the card, the buttons),
`member_lumen_stories.row` (hands over when a row has a leader's circle),
`church_news` (held list and decide), `rate_limit` (`moment_mark`),
`kmj_intake_automation` (the router). Tests: `__tests__/test_member_moments.py`.

Before building: both repos' `worklog/` had the Look 5.1 pieces (Home's
moments, members' posts, share, the tidy-ups); "leader-posted moments" was
on the Home piece's left-undone list. Nothing else overlapped.
