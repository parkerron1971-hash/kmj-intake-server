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
