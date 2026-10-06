---
title: Clip covers link from the design, not the clip (fix found in the live proof)
date: 2026-10-06
agent: Claude Code (Claude Opus 5.5)
asked: 'ok so is the video clip and images system made completely right?'
status: shipped
prs: [kmj-intake-server cover-link-on-the-design, solutionist-studio cover-from-library]
migrations: []
left_undone: []
decisions: ["Nothing writes to a clip: preserve_media_review keeps configuration (and a set approval) permanent", "The cover names its clip in director.clip_id; the library list reads it back as cover_image_id"]
related: [2026-10-05-clip-covers.md]
---
Kevin asked whether the clips and images system was completely right; the honest
answer was "built, not proven". Running it for real (Find my best clips opened to
every business, a 10-minute sermon in Church) showed: the Chief flyer works end
to end, all 4 clips got clean frames, the Make cover button appears. Make cover
then failed: it wrote the cover id into the clip's configuration, which the
preserve_media_review trigger forbids ("The media change could not be confirmed");
my tests mocked the database without the trigger. The cover now names its clip
and the list reads the link back. The earlier "approve again after a new cover"
note was wrong too: the trigger also forbids changing a set approval.
