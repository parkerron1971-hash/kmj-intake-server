---
title: "Solutionist: clips folded into the week (marketing suite B12)"
date: 2026-10-08
agent: Claude Code (Claude Opus 5.5)
asked: "This will work. let's build this."
status: waiting on Kevin
prs: []
migrations: []
left_undone:
  - "Kevin: nothing runs until MARKETING_DESK covers a Solutionist (practice) business (worker AND web), and nothing sends unless MARKETING_DESK_PUBLISHING=on and the owner approves; the first clip week should go to a test business with a kept, approved clip that has a ready story cover, and TikTok or YouTube connected"
  - "Not seen live: the social_publications filter media->0->>clip_id=in.(...) (a PostgREST JSON path with an array index). If production answers 400 it reads as a failed read: the week goes out without clips (design.clips.state 'unreadable'), never with a clip posted twice"
  - "Not measured: the week's caption call with two clip slots (estimated under half a cent more a week); posting a clip calls no model"
  - "A clip whose Chief post the owner skipped can be picked again next week (only waiting, sending or sent posts hold a clip). If Kevin wants a skipped proposal to rest for a while, that is a small rule in business_marketing_clips.in_posts"
  - "B13 standing permissions (post_clip, marketing_post) and F6 (the Solutionist view) are not built; the preview endpoint does not show the clips Chief would pick"
decisions:
  - "Eligible: media_assets kind clip, status ready, source_removed_at empty, decision 'kept' (Video Clips' Keep; undecided does not count), approval at the fingerprint it has now (clip_posting.approval_problem), no social_publications row naming it (media->0->>clip_id) in a status other than failed/cancelled, no marketing_posts row naming it (media->>clip_id) in a status other than cancelled/failed/pulled (this run's own drafts excepted on a replan), and a ready story cover (image_artworks director->>clip_id, size 1088x1920)"
  - "Gate: business_marketing_clips.takes_clips = plan_includes(marketing_autopilot) and plan_includes(ai_clips): Practice only. Professional, Boss (no ai_clips: 'No Video Clips') and the suggest level never read a clip"
  - "Pick: configuration.score highest first (unscored after every scored clip), then newest (finished_at/created_at), then id; at most 2 a week, each clip once"
  - "Place: one clip per weekday in the order Tue, Thu, Wed, Mon, Fri; the desk's hour or the next free hour to 21:00, then 3 PM and after; >= 1 h from now; >= 3 h from every other post of the business that day (the week's flyer posts included); compared as instants"
  - "Add, not replace: up to 7 posts a week. Checked limits: send_post's 25 posts/business/rolling day; FLYERS_PER_WEEK and MARKETING_DESIGNS_AT_ONCE count designs (a clip needs none); marketing_approve takes 50; the run's post reads take 10-60"
  - "Post: source 'clip', play_id 'video_clip', design_status 'none', media = business_marketing.build_media's (clip_id, clip_fingerprint, covers story+wide by id), so the fingerprint is in content_hash; targets = the desk's accounts (or every connected one) on a network in clip_posting.COVER_SHAPES (TikTok and YouTube included); tracked link in publish_text as every desk post; saved in the week's one insert; post id uuid5(run, '<attempt>:clip:<n>')"
  - "Cover per network = clip_posting.cover_for at send time (story on every vertical player, wide on LinkedIn else story); the run records it per network in design.clips.picked[].covers"
  - "Caption: one more slot in the week's one caption call (max_tokens +300 per clip; no new paid call), the clip's title, checked words and tags as data, no flyer; the business checks (numbers/prices from the facts, own-site links, <= 3 hashtags); a broken caption drops only that clip"
  - "Sender: the existing B5 re-check (digest == approved_hash == content_hash; clip approved as it is now at the post's fingerprint) covers a clip that changed after approval; added: a source 'clip' post whose clip is no longer kept is refused (business_marketing_dispatch.UNKEPT)"
  - "Telling the owner: the week's one Today item + push counts the clips ('5 have a flyer and 2 are your own video clips, with their covers'); a clip is never counted as words only. The owner's request message says clips come with the week"
  - "A failed clip read (any of the four) leaves the week exactly B9's, with design.clips.state 'unreadable'; an unexpected error in the clip half is caught and recorded, never fails the week"
related: [2026-10-07-marketing-weekly-plan.md, 2026-10-08-marketing-openings.md, 2026-10-07-marketing-desk-send.md, 2026-10-06-chief-post-clip.md, 2026-10-06-post-clip-with-cover.md, 2026-10-06-covers-both-shapes.md]
---
B12 of docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md (D6). Solutionist's
week (the autopilot level) is B9's five flyer posts plus up to two of the
business's own clips: business_marketing_clips.py picks and places them
(eligibility reads, rank, days and hours, video accounts, covers), and
business_marketing_planner._plan_week folds them into the same run, the same
caption call and the same insert as source 'clip' drafts, sent by B5 through
clip_posting.post_clip_for. The sender also refuses a Chief-picked clip the
owner has since un-kept. No migration, Chief action or frontend. Tests:
__tests__/test_business_marketing_clips.py (no live calls). Docs:
docs/MARKETING_DESK.md, "Clips in the week (B12)".
