---
title: The cover's face close-up is the best face in the clip, not the biggest
date: 2026-10-06
agent: Claude Code (Claude Opus 5.5)
asked: "Kevin: whatever is missing, make the upgrades so it's better"
status: done
prs: [kmj-intake-server better-face-frame]
migrations: []
left_undone: ["The clip service must be redeployed with railway up after merge (the auto-mode classifier blocks Claude from deploying to production; Kevin runs it)", "Blinks and eyes cast down are not seen: five landmarks give head turn, not eyelids or gaze", "A two-camera conversation where each camera holds one person is still talking_head, so the close-up can be the other person; telling people apart needs a face recognition model, not added"]
decisions: ["Score = size x sure x frontal x sharp; strong profiles and tiny faces are never used, so a clip with no usable face gets no close-up and the cover uses the frame", "Sharpness is measured on the brows-and-eyes band scaled to 128 px, so an open mouth's teeth don't count and faces of different sizes compare", "No smile bonus: on the sermon footage the mouth-corner width moved as much with speech as with a smile", "A two_shot clip samples only around its poster moment, since another moment can be the other person"]
related: [2026-10-06-covers-look-like-the-person.md]
---
The face close-up used to be the largest face within 1.5 s of the poster
moment, so its expression was whatever that second held: often turned aside.
It now samples 14 moments across the clip plus the five around the poster and
keeps the face that best faces the camera, is sharp, big and surely a face.
On the 10-minute rehearsal sermon, 4 of 5 clips changed to a face looking at
the camera (three were turned aside, one looking down at notes), always the
same man, in about 1 s per clip locally; the fifth kept its frame, which
already faced the camera.
