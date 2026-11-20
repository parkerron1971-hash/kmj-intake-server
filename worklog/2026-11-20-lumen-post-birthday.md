---
title: "Member app new look (Look 5.1): ask for the birthday when a member taps Post in a group"
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "yes ask for the birthday when they tap post" (members without a birthdate on record could not post in their groups)'
status: in review
prs: ["kmj-intake-server (this PR)"]
migrations: []
left_undone:
  - "Mission Control doesn't show a birthday a member gave (contacts.metadata.member_birthdate) beside the office's; the office still sets contacts.birthdate, which wins."
  - "A member who gave a teen's birthday stays in the Church space (Youth is chosen from contacts.birthdate alone) and can't post in groups until the office records their birthdate and turns messaging on for them (the existing teen wording says so)."
  - "Found, not fixed here (it was on main before this): after any member's group post, the group's page says 'Posted to Youth.' (member_portal_church.DONE['posted'], the Youth space's wording, read for done=posted). member_posts.DONE['posted'] has the right line; a one-line follow-up."
  - "Not checked on a real phone: Playwright Chromium and WebKit at 390x844 @2x, reduced motion."
decisions:
  - "Where it lives: contacts.metadata.member_birthdate (yyyy-mm-dd) on the member's own record, never contacts.birthdate. Written like member_saved and member_watch: service role, their own row (the id comes from the session, never the form), guarded by updated_at, inside POST /my/post (its checks: this church's address and same site, a live session and never the preview, the new look showing to that session, the per-person limit)."
  - "Asked once: once given it can't be changed from the app (save_birthdate returns 'kept' and writes nothing), so nobody turns into an adult after being treated as a teen. The office's contacts.birthdate always wins."
  - "Posting only. Posting's age is contacts.birthdate, else the given one (member_posts.posting_birthdate). Messaging and member_messaging_rules read contacts.birthdate alone and are unchanged, so a typed birthday never opens messaging; a leader with only a typed birthday is never one of a group's two approved adults. A typed birthday that says someone is a teen makes them a teen in posting's rules (it only narrows what a group allows: two adult leaders, no photos)."
  - "Checks: a real date, not in the future, under 110 years. Under 13 (member_spaces.is_child, the same line sign-in uses) isn't kept and doesn't post: 'Members under 13 can't post in groups. Please ask a parent or the church office.' A teen's age is kept and the existing teen wording shows."
  - "The composer asks only while posting has no age for them and a group is on offer, above Post: 'Your birthday', one native date field, 'We ask once. It keeps teens safe in groups.' The script hides it (and stops requiring it) while The whole church is picked; without the script it always shows. Post saves the birthday, then the post, in one submit. The composer's own classes and the Bible's field (lm-field), with two spacing rules in member_lumen_connect.CSS (through member_lumen_ui.templates())."
  - "No new read: the session's contact select carries it (bday:metadata->member_birthdate, beside watch and saved), and so does the owner's preview record."
related: [2026-11-20-lumen-member-posts.md]
---
`member_posts.py`: `given_birthdate`, `posting_birthdate`, `_as_posting`,
`check_birthdate`, `save_birthdate`; `rules()` uses posting's age; the composer
asks (`render`, `POST_JS`); `POST /my/post` saves it before the post.
`member_portal.py` and `member_portal_preview.py`: the select. Tests:
`__tests__/test_member_posts_birthday.py` (13).

**Checked.** Switch off: the dark work's Home (656) and Bible (295) page x scene
dumps identical to main; MEMBER_LUMEN=preview for a member who isn't the
platform owner, the same. The composer, a group's page, Messages, Me and
Details in four birthday states, light and dark (104): off and preview
identical; on, only the composer differs (the field when there's no birthday,
the script's two lines, the new post_birthday words). Reads: Home 82 and
Bible 59 pages x 2 looks the same as main (one Bible-harness page that 500s
on both varies run to run); the composer 2 warm reads with or without the ask.
Server-Timing medians (60 warm, alternated, same look): Home 5.8 / 5.4 ms,
Bible 3.0 / 3.0, the composer 2.2 / 2.2 with or without the ask.
