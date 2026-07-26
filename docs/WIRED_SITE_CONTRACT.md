# THE WIRED-SITE CONTRACT

*2026-07-26. Kevin's ruling: the old interview had toggles ("BOOKING", …)
so the builder could never forget to wire a connected system into the
site. The Design Coach retired that form — and with it, the contract.
Bring the contract back, better: mirrored from system truth, confirmed
in the owner's words, enforced as law.*

## The principle

Whether the site carries booking (or the store) must never depend on
the builder *inferring* it. Inference forgets. A connection is a
**contract**: the platform knows what is live (`offering_profiles.
business_state()` — booking_enabled, booking_url, store_url), the owner
decides what the site carries, and the builder is *checked* against
that decision the same way it is checked against the coverage law.

## The four layers

### 1. The dossier carries a `capabilities` section

`site_config.discovery_dossier.capabilities` — leaves like
`{booking: {value: "on", source: "asked"}, store: {...}}`, same
provenance rules as every other section (asked > inferred-confirmed >
recon). Rides `dossier_digest` to the Director like world/story/
signature do.

### 2. The coach confirms by mirroring, never asks blind

`design_coach._known_context()` gains a CONNECTED SYSTEMS block built
from `business_state()`: what is actually live, with real URLs. The
coach's territory (inside the existing `truth` station — the working
doors ARE truth) gains one confirm question, pre-filled from that
block: *"Booking is live with your services. Should the site carry a
Book button front and center?"* Saves land as `capabilities.booking` /
`capabilities.store`. The coach never offers a door the platform does
not have.

### 3. The contract is law at build time

- `assemble_real_data()` emits a `CONNECTED SYSTEMS` block with the
  live URLs for every door that is ON (system live AND capability not
  turned off by the owner — a working system unreachable from the site
  is the dead-weight rule violated at platform scale, so silence
  defaults to wired).
- Builder prompt rule: each listed door appears as a real link — in the
  nav and as a devoted moment; never invent a door the block doesn't
  carry.
- `check_connected(html, real_data)`: deterministic — each ON line's
  URL must appear in the document. A missing door is a violation that
  costs a repair round, exactly like a missing image. The spec author's
  COVERAGE LAW gains the matching bullet.

### 4. Chief closes the loop on module creation

`handle_create_offering` (bookable/sellable): after creating, Chief's
label states the site truth — wired ("bookable on your site's Book
flow") or not yet ("your site doesn't carry a Book button yet — say
'wire booking into my site' and I'll set it up"). A new
`set_site_capability` action lets that sentence be answered in chat:
it writes the capability into the dossier (asked provenance) and
points at the refine job that bakes it in. Serve-time injection is NOT
used for canvas pages (canvas-protection rule: designed pages are
never defaced by injections); the door arrives via refine/rebuild,
which the capability makes mandatory.

## What this closes

The "booking verbs" seam from the layer-two audit, from the front: the
site side of every future connected module follows this same contract —
new capability = one more line in `business_state()`, one more mirror
line for the coach, one more ON line in the block, zero new
enforcement code.
