"""Pass 4.0d PART 1 — Site content override system.

Render-time content override layer that swaps Builder-generated text /
palette-role colors / slot images for practitioner-specified overrides
WITHOUT rebuilding the HTML. Backed by the site_content_overrides
Supabase table (see supabase/site-content-overrides-migration.sql in
the solutionist-studio frontend repo).

Modules:
  override_storage  — CRUD against site_content_overrides via Supabase REST.
  override_resolver — pure-function HTML transform; runs after the slot
                      resolver in the render pipeline at smart_sites.py.
  router            — /chief/override endpoint (POST upsert, GET list,
                      DELETE revert).

Resolution priority at render time (PART 5 spec):
  custom_url > override_value > generated_value > placeholder

Owner gating: NONE at this layer (matches single-tenant-anon pattern
across slot_system, voice_depth, public_site, etc.). Per-business JWT
retrofit planned for a later pass.
"""
