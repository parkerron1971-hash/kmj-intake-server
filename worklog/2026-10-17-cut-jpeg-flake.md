---
title: The cut-picture upload test stops failing one run in twenty
date: 2026-10-17
agent: Claude Code (Claude Opus 5.5)
asked: 'Found while landing kmj-intake-server#1468 ("yes point the website buttons at the new cards."): its CI went red in test_brand_asset_upload.py, a file it does not touch.'
status: shipped
prs: [kmj-intake-server#1469]
migrations: []
left_undone: []
decisions:
  - "Drop the 2-byte JPEG cut: it removes only the end marker, and a noisy JPEG without it often still decodes every pixel, a whole picture the server may store"
  - "Seed the test noise, so every run cuts the same bytes"
related: [2026-10-16-logo-upload-storage.md]
---
test_a_picture_that_does_not_decode_is_refused_and_nothing_is_written[jpeg-2]
failed on #1468's second CI run after passing on its first, with the same
code. The test made fresh noise every run and cut the last 2 bytes of the
JPEG, which is only the end marker. In 2000 fresh noisy JPEGs, 99 still
decoded whole without it (the 10, 30 and 50-byte cuts: 0 of 2000; WebP
minus 40 and GIF minus 200: 0 of 300). The upload check is right to take
such a file, since every pixel is there. The test now cuts 10, 30 and 50
bytes from seeded noise.

Its twin in test_storage_path_confinement.py (test_drop_refuses_a_truncated_jpeg[2],
the site-image drop) failed this PR's own first CI run the same way: 54 of
1000 fresh 128px JPEGs decoded whole without their end marker. Same fix.
