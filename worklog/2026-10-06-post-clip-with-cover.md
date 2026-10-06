---
title: Post an approved clip with its cover to the connected accounts
date: 2026-10-06
agent: Claude Code (Claude Opus 5.5)
asked: "Build post a clip with its cover: post an approved clip to the connected accounts, with its story or wide cover as the thumbnail"
status: waiting on Kevin
prs: [kmj-intake-server clip-post-with-cover, solutionist-studio clip-post-with-cover]
migrations: []
left_undone: ["Not proven live: no real post was made and the posting service was never called; the first real post should go to a test account", "A Chief action that posts a clip with a caption Chief writes is not built", "The wide cover is mapped only for LinkedIn, which is not switched on; every network switched on today gets the story cover"]
decisions: ["Owner only (auth plus a service-role owner check), like covers", "Same door as Social Media posts: social_publish_router.send_post (record, daily cap, hand-off, results, cancel)", "The clip must be approved as it is now and be the one the app showed (fingerprint), else a plain 409 before anything is signed or sent", "Story cover on vertical players (Instagram and Facebook Reels, TikTok, YouTube Shorts, X); wide only where a 16:9 card is used (LinkedIn), falling back to story, then none", "A cover is used only if it is a ready design of this business naming this clip in that shape", "The cover goes as a JPEG at Image Studio's public published-artwork path (a Reel cover must be JPEG)", "The video goes by a signed link: an hour for a post now, an hour past the time for a scheduled one; handed over, never stored", "request_id per tap becomes the post id (uuid5), so a retried tap never posts twice; the same post within a day returns the first"]
related: [2026-10-06-covers-both-shapes.md, 2026-10-05-clip-covers.md, 2026-10-05-find-best-clips-backend.md]
---
`POST /media-library/{business}/clips/{clip}/post` (clip_posting.py) posts an
approved clip to the business's connected accounts now or at a time, with its
cover as the video thumbnail. It reuses the Social Media publish path: the
shared part of `/social/publish` moved into `send_post`, which now also takes
the media the posting service fetches (so a signed link is never kept), per
network settings (each network's own thumbnail, Reels placement, a YouTube
title) and an idempotency id. `post_for_me.create_post` accepts a media item
with a `thumbnail_url`. Image Studio's JPEG publishing step is now
`image_studio.delivery_jpeg`, shared with the clip post.

Before building more here: a scheduled clip post hands the posting service a
link that lives until an hour past the post time (up to about 90 days),
because it fetches the file when the post goes out. If that is too long,
copy the clip into the posting service's own storage (`/social/media-slot`
style) instead. Tests: `__tests__/test_clip_posting.py` (34, no live calls).
