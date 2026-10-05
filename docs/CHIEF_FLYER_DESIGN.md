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

The cover's id is saved as `configuration.cover_image_id` on the clip.
Configuration is part of the clip's approval fingerprint, so a new cover after
approval asks for a fresh approval: the cover goes out with the clip. Clips
made before the clip service took frames (`configuration.frame` false) get a
409 and keep their poster.

`python -m pytest __tests__/test_clip_covers.py -q`
