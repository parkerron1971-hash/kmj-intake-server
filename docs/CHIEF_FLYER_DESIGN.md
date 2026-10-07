# Chief flyer art direction

Mission Control's Chief now receives a seven-direction creative benchmark: portrait/type,
concept scenes, editorial stories, tactile collage, textured posters, restrained milestones,
and product heroes. These are composition principles, not templates or permission to copy
reference brands, people, offers or claims.

## Generate, compose and review

- `generate_image` accepts a structured art direction and up to four reference inputs. Each
  input has an explicit style, subject, logo, product or edit-target role. The server compiles
  the production prompt and resolves selected chat images to private owned gallery IDs
  before the existing approval ledger freezes the proposal. Both immediate and later
  approval therefore use the same image inputs. Chat comparison alone stores nothing.
- Optional benchmark artwork is looked up inside the owner's platform business using the
  exact `Chief design benchmark v1: <style_key>` prompt label. Absence falls back to the
  direction description. An edit never receives an automatic new style reference.
- `compose_flyer` renders an owner-specified layer layout using Chromium already installed
  by the Railway build. It preserves supplied raster assets and renders editable text and
  shape layers. It creates a PNG and reconstructible SVG master, not a PSD or a layer
  extraction from flattened artwork. Generate a text-free key visual first when needed,
  then compose over it after it is ready. No paid image call is needed for typography edits.
- The existing private `image_artworks.prompt` field stores a versioned JSON layout for
  composed assets. No schema migration or public storage policy is required. Raw images
  remain in the existing private bucket; the master endpoint checks owner + business and
  embeds owned assets into an attachment download. No remote URLs, HTML or scripts are
  accepted by the layout schema. Browser network requests are blocked.
- Review design prefills a request that attaches the actual owned artwork to Chief's vision
  input. Refine does the same. The complete editable layout is supplied for composition
  revisions. Review is a user-triggered Chief turn, not an automatic quality score or silent
  paid regeneration. References unavailable at review time are reported explicitly.

## Limits

Four image inputs/layers per design, 24 layers, 320-2400px canvases. Fonts use installed
sans, condensed, serif and monospace families; SVG font appearance may vary in another
editor unless that font is installed. Copy needs explicit line breaks. Rendering rejects
text that exceeds its allocated width or is clipped outside the canvas. Composition allows
raster cropping, rounded clips, rotation, opacity, shapes and text; it is not a full image
retouching editor. Generated art is still raster and exact pixel fidelity is not guaranteed.

One asset per Chief turn, existing creative permissions, owner authentication, budgets,
rate checks and post approval remain in effect. Benchmarks stay private and require owner
authorization to install. Their depicted prices/results/testimonials are never product facts.

## Validation

Regression tests cover durable reference mapping, same-business ownership, role handling,
benchmark fallback, review pixels, malformed inputs, SVG escaping, bounded resources,
composition retry behavior and download authorization. A real Chromium render checks the
SVG/PNG pair and text overflow. Frontend checks cover composition cards, review prefills,
master downloads and mobile layout. Paid live generation is evaluated separately from
these deterministic checks; creativity still requires the owner's visual judgment.

## Execution and status reliability

Creative generation and composition are exposed as native model tools. Direct creation requests
require a tool response (with an essential-facts clarification escape); legacy tags remain
compatible but cannot duplicate a native creative call. Truncated responses execute no actions.
The existing owner approval ledger, budget and one-asset limits still govern execution.

Creation replies are derived from the returned approval/job state, not the model's pre-execution
narration. Simple image-status follow-ups read owned records and return actual cards without a
model call or new generation. A conversation without a job receipt is explicitly unconfirmed;
older gallery work is labeled as potentially belonging to earlier requests. Uploaded style
benchmarks and chat references are excluded from the generated-work fallback.

The live marketing snapshot includes the founder offer's Stripe amount and billing interval,
monthly credit allowance, seat limit and remaining seats. Failed availability reads produce
unknown availability, never a fabricated full allocation. A lifetime-locked recurring rate must
not be described as a one-time purchase, and prior assistant copy is not evidence for claims.

## Every business (2026-10-05)

The Creative Director is no longer Mission Control only. A practitioner's flyer
build (`submit_work_order` kind `flyer`, or an event with `wants_flyer`) now runs
`design_flyer` instead of one `generate_image` call: plan, draw, check the
finished pixels, repair once. Switch: `PRACTITIONER_CREATIVE_DIRECTOR` (default
on; `off` restores the single call).

- **Words.** The Director prints only `exact_copy`. A flyer order without it asks
  the practitioner "What should the flyer say, word for word?". A workshop
  flyer without it prints the workshop's saved title, date, place and "Free"
  when the price is zero, nothing else.
- **References.** Owned gallery images only (`references: [{id, role, use}]`).
  Unlabelled images: an earlier generated design is the revision target, an
  upload is a photo to feature. A website URL is captured first; its
  screenshot and logo are placed as they are, never redrawn.
- **Facts.** `business_facts()` reads what the business's own site publishes
  (`agent_site.bundle_for`): name, contact, website, booking link only when
  booking is open, offerings with prices only where the price is shown, and
  brand colours. No founder-offer arithmetic for tenants.
- **Limits.** A business job (`director.scope == 'business'`) answers to its own
  daily spend limit and credits, never the platform budget. Jobs without a
  scope are Mission Control's and behave as before.
- **Price.** 30 credits a design: the first render is charged; the repair render
  and the planning/review calls are 0. This applies to Mission Control too.
  Measured cost: a render is $0.04-0.06, a planning or review call about $0.03.
- **Identity.** `design_flyer` uses `generate_image`'s request id, so the build
  step's verify finds the row and a replay never pays twice. A designed flyer
  gets 20 minutes before it is called interrupted (a single image, 10).
- **Controls.** `POST /ai/images/director/{business_id}/{image_id}/remember` and
  `GET .../master` are the business-owner versions of Mission Control's
  Remember this style and layered master download.
- **Sizes.** Image Studio and the Director accept `1088x1920` (phone story) and
  `1920x1088` (widescreen) on the 2.5 models, both checked in a production call
  on 2026-10-05. GPT Image 2 keeps square, portrait and landscape.

`python -m pytest __tests__/test_designed_flyers.py __tests__/test_creative_director.py -q`

## Clip covers (2026-10-05)

`POST /media-library/{business_id}/clips/{asset_id}/cover` with
`{request_id, words?, size?}` (owner only; `clip_covers.py`). It designs a
cover with the same engine as a flyer: the clip's clean frame (`<clip>-frame.jpg`,
taken from the recording at the poster's moment, see `clipper_worker`) is
copied once into the gallery and used as the `subject`; the words default to
the clip's title; the size defaults to `1088x1920` (`1920x1088` for a YouTube
thumbnail). 30 credits, like any design. A remembered style (Remember this
style) gives every cover in a series the same look.

The cover names its clip (`director.clip_id`); the library list reads that
back as `cover_image_id` on each clip (`clip_covers.covers_for`). Nothing is
written to the clip: the `preserve_media_review` trigger makes a clip's
configuration (and an approval, once set) permanent, which is why the first
version, which wrote the id into configuration, failed in production on
2026-10-06 with "The media change could not be confirmed". Clips
made before the clip service took frames (`configuration.frame` false) get a
409 and keep their poster.

`python -m pytest __tests__/test_clip_covers.py -q`

## Likeness (2026-10-06)

Kevin: a cover of a real person must look "over 90 percent" like them; letters
partly covered by the person are fine (a graphic device). So:

- The clip service saves a head-and-shoulders close-up from the recording with
  each clip (`clip_NN_face.jpg` → `<clip>-face.jpg`, `configuration.face`),
  cropped ~3 face-widths at 4:5 and scaled to 1024 tall. The expression comes
  from the frame chosen, so it is the best face in the clip, not the biggest:
  of 14 moments spread across the clip plus five within 1.5 s of the poster,
  the one scoring highest on `size × sure × frontal × sharp`
  (`empty_spots.face_score`: facing the camera from the nose and eye
  landmarks, sharp eyes by Laplacian variance, confidence, size). Profiles and
  tiny faces are never used; a two-person shot looks only around the poster,
  since another moment can be the other person.
- Make cover sends the close-up first ("match this face, beard, hairline and
  hairstyle exactly") and the stage frame second (pose, body, clothes).
- With subject photos, the render prompt adds LIKENESS FIRST, the planner plans
  for likeness, and the checker sees the subject photos and judges
  `likeness_match`; a miss is repaired once (the one-repair ceiling stays, so a
  design always comes out). The checker no longer reports overlapped letters.
- `input_fidelity: "high"` is rejected by GPT Image 2.5 (`invalid_input_fidelity_model`).

## Two shapes, a look to follow, covers with the clips (2026-10-06)

Kevin: "I like the full screen videos covers along with the story size ... can
we figure out a way to have both?" and "an option to create the cover right
along with the video clips".

- **Shapes.** `story` (1088x1920: Reels, Shorts, TikTok) and `wide`
  (1920x1088: a YouTube thumbnail). Make cover takes `sizes: ["story","wide"]`
  and designs both in one tap; each is its own design (30 credits) with its own
  turn id (`clip-cover:{clip}:{request_id}:{shape}`), sharing the speaker's
  pictures. The wide brief keeps the bottom-right corner clear (the video
  length sits there). One shape can fail (credits ran out) while the other
  designs: the response carries `covers` and `errors` by shape. A request with
  only `size` keeps the original turn id, so an older app's retry lands on the
  same design.
- **A look to follow.** `style_image_id` (a picture in this business's
  gallery) joins as a `style` reference: its layout, type, palette, light and
  texture, never its words, people or logos. `note` (300 characters) is the
  owner's own words about the look ("keep it dark, almost black and white").
- **Read back.** `clip_covers.shaped_covers` gives each clip
  `covers: {story, wide}` in the library list; `cover_image_id` stays (story).
- **With the clips.** Find my best clips takes `covers: {sizes, style_image_id?,
  note?}` (owner only; 403 otherwise). The run's options keep it (no `covers`
  key when none was asked for: a JSON null would match the filter). Every 30 s
  `clip_covers.cover_tick` takes completed runs from the last 6 hours that asked
  for covers and designs the missing shapes for the best-scoring clips that
  are not skipped and have a clean frame, at most `CLIP_COVER_LIMIT` (6) clips.
  It acts as the run's owner (`image_studio.build_actor`), so the copied frames
  carry `cost_usd: 0`. Stable turn ids make it safe to repeat. A design that
  cannot start (credits, spend limit, the 20-designs-a-day cap in
  `reserve_image_artwork`) is tried twice; once every missing cover has used
  its tries, the owner gets one Chief notification (marked sent only when it
  is written) and the clips keep Make cover. Make cover skips a shape that
  already has a cover designing (`designing_now`), so a tap while the
  automatic cover is still being drawn never pays twice (409 when every
  asked-for shape is busy).
- **Pricing for the app.** `clip_finder.configuration().covers` =
  `{available, credits_each, clip_limit, shapes}`.

`python -m pytest __tests__/test_clip_covers.py __tests__/test_clip_finder.py -q`

## Close-ups for older clips (2026-10-06)

Kevin's cover for "Don't Judge Rightness By Feelings" was "75 percent me": the
clip was made before close-ups existed, so only the wide stage frame (his face
about 30 px, turned) guided it. Now, when a cover is made for a clip with no
close-up (`configuration.face` unset), `clip_covers.backfill_face` asks the clip
service for one: `POST /faces {source_url, start, end}` reads the clip's
stretch of the recording while it is kept (7 days; otherwise the clip's own
video) with one ffmpeg pass over range requests, runs the same picker as a clip
run (`empty_spots.pick_closeup`), and returns the JPEG, which is saved at
`<clip>-face.jpg`. The clip's configuration is not touched (it is permanent).
A stretch with no usable face answers 404 "No usable face in that stretch" and
is remembered for the process; any other answer is not: a video that could not
be read (expired link, network blip, ffmpeg failure or timeout at 60 s) is 502,
a busy service (two close-ups at a time) is 503, and an older clip service's
plain 404 is asked again later. The API waits at most 75 s for it. Measured on the sermon: 14 frames read in about 4 s, an
86 px face, facing the camera. A clip that had a close-up never has it remade;
since the likeness meter it is only asked for more views (face2, face3).

## The likeness meter (2026-10-06)

Kevin: "we want over 90 percent looks". Upscaling the video face was tried
first and dropped: a faithful upscaler (EDSR) left the face identical
(identity cosine 0.998) and no sharper, because the softness is compression;
face "enhancers" invent detail and change the face. What moves likeness is
seeing the real face, so:

- **More views.** `POST /faces` takes `count` (1-3); with more than one it
  answers JSON `{faces: [{jpeg_b64, size}]}`, best first. A cover gets up to
  three close-ups (`<clip>-face.jpg`, `-face2.jpg`, `-face3.jpg`) plus the
  stage frame; with a style picture, two close-ups, the frame and the style
  (a design takes four pictures). `clip_covers.backfill_faces` asks once per
  clip per process, and only an answer with faces counts as asked.
- **The meter.** After each draw, `creative_director.measure_likeness` sends
  the design and its subject photos to the clip service, `POST /likeness`,
  which scores the largest face against each photo with SFace (OpenCV Zoo,
  Apache-2.0; downloaded at build, pinned by checksum) and answers the best
  cosine. Below `LIKENESS_MIN` (0.72) the verdict fails with a face issue and
  the design takes its one repair; if the face was the only fault and the
  repair came out less like them, the first draft is kept. No face found, no
  clip service, any failure: no grade, never a failing one. The score is on
  the verdict (`review.likeness`) and in `public_state`.
- **Measured** on Kevin's sermon: two moments of the same man 0.55-0.74; the
  "Don't Judge Rightness By Feelings" cover drawn from the wide shot 0.586
  ("75 percent me"); a thumbnail drawn from a close-up 0.931; the close-up
  against itself 1.0.

## The speaker photo and the expression that fits the title (2026-10-06)

Kevin: "does the chief go through the clip to find the best pose that shows
my face and expressions the best that fit the title". Two additions to
`clip_covers.subject_references`:

- **The expression.** The face picker ranks close-ups by size, sharpness and
  facing, not by mood. With two or more close-ups and a title,
  `pick_expression` shows them to the review-lane model (low effort, so
  thinking cannot eat the one-number answer) and asks which expression and
  gesture fit the title. That close-up leads, told to "use this expression
  and gesture". Asked once per clip per process (the story and wide covers
  share it); any failure or an answer that is not one of the numbers keeps
  the face picker's order. Metered with `units=0`, never a design charge.
- **The speaker photo.** A face in a video frame is small and soft; a photo has
  the real detail. `GET/PUT/DELETE /media-library/{business_id}/speaker-photo`
  (owner only) saves one picture from the business's image gallery
  (`/ai/images/upload` first for a new one). It is copied to its own row with
  a fixed id (`speaker_id`, uuid5 of the business), `cost_usd` 0 and no model,
  so it never counts toward the daily design cap, and deleting the original
  never breaks it. Saving checks a face is in it (`POST /likeness`, the photo
  against itself, `face_found`); when the clip service cannot answer, the
  photo is kept. At use, face recognition compares it with the clip's best
  close-up (or the frame), once per clip and photo: at `SPEAKER_SAME_PERSON`
  (0.45) or above it leads as the authority on the face and hair, followed by
  two close-ups and the frame (with a style picture: the photo, one close-up,
  the frame and the style). Below it, a guest speaker's clip, or any failure:
  the cover uses the clip's own pictures. The likeness meter then grades the
  design against all its subject photos, the speaker photo included.

## Chief posts a clip (2026-10-06)

`post_clip` (`chief_clip_actions.py`, class C) posts an approved clip with its cover through `clip_posting.post_clip_for`, the same function as the Post tap, only when the owner asks in chat: unattended runs are held, the clip must already be approved in Video Clips, and the post id comes from the chat turn so a retried turn never posts twice.
