---
title: Find clips in a service streamed through Solutionist, and the YouTube steps
date: 2026-11-24
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "both" (a "Find clips in this service" button on each service recording, and a helper for sermons whose video is on YouTube)'
status: waiting on Kevin
prs: ["kmj-intake-server (this PR)", "solutionist-studio (the buttons, its own PR)"]
migrations: []
left_undone:
  - "Merging this deploys the clip service (clipper_worker/ changed): check its /health says busy false first; a deploy stops a running clip job."
  - "SERVICE_CLIPS ships as owner (the platform owner's churches). Set SERVICE_CLIPS=on on kmj-intake-server on a Thursday for every church, with a What's New entry in the frontend."
  - "Not tried on a real service yet: the first real run should be Love City's 11-22 service (owner mode shows the button there). Watch the clip service's [clipper] recording lines."
  - "YouTube videos still can't be clipped directly (YouTube's rules, datacenter blocks, rights): the sermon shows the download-from-YouTube-Studio steps and opens Video Clips to upload."
decisions:
  - "No upload and no copy: the service is a media_assets source row (origin 'service', byte_size 0, id uuid5 of the session), so Find my best clips, the plan's hours, review and handoff work unchanged. The 7-day sweep never touches it; deleting the recording (church_storage.remove_recording) stamps source_removed_at."
  - "The clip service reads the full-quality recording while kept (playlist cut here to whole segments, signed for 4 h) and remuxes it without re-encoding (-c copy, checked across a resume with ffmpeg 8.1). Within a day of the day-14 trim, or when the stretch's full-quality bytes would pass 4.75 GB, it reads copy.mp4 with -ss/-t. Both only from CLIPPER_COPY_HOSTS (already set for the copies); a source_url there is still refused."
  - "Where the sermon starts and ends (FindClips.from_seconds/to_seconds, a service only): the run's hours are the stretch's; over 2 hours needs one. Clips are filed at their times in the whole service (the offset kept on the run's counts, so a resumed run files the same)."
  - "A service has no hand cutter (409 with how to) and no reviewed handoff of its own; its preview is the smaller copy once made, else a note."
  - "GET /media-library/{biz}/services tells the sermon and Live screens what to offer (services, clips); a person without the clips duty gets the access check's 403 and sees nothing."
related: [2026-11-17-recording-small-copy.md, 2026-10-05-find-best-clips-backend.md, 2026-10-29-church-stream-relay-service.md]
---
A service streamed through our relay can now be clipped where it already
lives. "Find clips in this service" (on the sermon draft and on the Live
page's recent services) adds it to Video Clips as a recording and opens it
there, with an optional "Where is the sermon?" step. `service_clips.py`
holds the rules; `clip_finder.drive` hands the clip service a signed
playlist or the copy's link instead of an upload link; `clipper_worker`
gained `playlist` / `recording_url` (+ `start`, `end`, `seconds`) on
POST /jobs. Tests: `__tests__/test_service_clips.py` (33) and the clip
service's new cases, including a real-ffmpeg read of a resumed recording.
