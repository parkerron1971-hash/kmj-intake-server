---
title: In a church, whoever does the posts or the clips can see the church's pictures
date: 2026-11-02
agent: Claude Code (Claude Opus 5.5)
asked: "The Media & Communications login's covers and pictures show as unreadable in the media library and the Create desk (follow-up to the duties work Kevin approved, #1691-#1693)"
status: in progress
prs: [kmj-intake-server#1696]
migrations: []
left_undone:
  - "Uploading a picture (POST /ai/images/upload, the marketing desk's 'add a photo') is still the owner's: a write, left as it was"
decisions:
  - "Only churches change: Image Studio's gallery and one-image reads open to the owner (as before), an Admin, or a login that holds() posts or clips; a Manager with neither is refused (403); a failed duties read is a 503, never a yes"
  - "For those logins image_artworks is read as the service role, pinned to the church that was checked, and each preview is signed as the service role only for a row of that church whose original is in its folder"
  - "The owner's path is unchanged (their token, RLS, their own signing); a failed business read falls back to it, which is never a yes for anyone else"
  - "Every other business keeps the owner-only rule; writes (generate, upload, publish) and the build actor are untouched"
related: [2026-11-01-media-gates-duties.md, 2026-11-01-church-duties.md]
---
`image_studio.church_reader`, `reader_rows` and `reader_storage_headers`; `present()` takes the
checked business as `reader` to sign the preview. The frontend reads only these two routes
(`imageApi.ts`: `listArtwork`, `getArtwork`, and `downloadArtwork` through the signed URL), so no
FE change is needed. Tests in `__tests__/test_image_studio_church_readers.py`; the step 2b section of
`docs/CHURCH_DUTIES.md` names the reads.
