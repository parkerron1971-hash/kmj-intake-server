# Desk: websites

## 1. What it owns

- **A practitioner's or church's own website.** Build → My Site: the Design
  Coach interview, the blueprint, "Build it", the live preview, Edit Mode
  (click a line, change the words), publish on/off, revisions, separate
  pages, and "Use your own domain". Visitors see the site at
  `<slug>.mysolutionist.app` or the church's own domain.
- **Forms and doors on those sites:** contact / prayer / visit forms, the
  booking page, link page, resources page, news posts, the website chat
  (concierge).
- **Hand-built sites** kept in this repo (`sites/<dir>/`), served by the
  same system with no AI spend.
- **The Solutionist's own public pages:** the home page, /pricing,
  /features, /churches and /coaches product pages, /faq, /privacy, /terms,
  plus ChurchSavvy's own site (churchsavvy.app).

## 2. Where the code is

Backend (`kmj-intake-server`):
- `public_site.py` — serves every public page. `/public/site/{slug}[/{page}]`,
  `/public/booking/{slug}`, `/public/link/{slug}`, the marketing routes
  (`/`, `/pricing`, `/churches`, `/coaches`, …) and the `/{path:path}`
  catch-all. Also owner-side `/sites/{business_id}/*` (smart-config,
  set-site-type, generate-multi-page, restore-previous, invalidate…).
  Host handling: `public_host`, `extract_slug_from_host`, `X-Original-Host`.
- `site_composer.py` — `/composer/*`: compose, shuffle, coach/turn,
  coach/finish, directions, refresh, refine-section, revise-sections,
  domain/connect | verify | disconnect, site/visibility. Calls
  `site_kit.build` first, then `builder_v2`.
- `agents/composer/router.py` — a second `/composer` router (diag/spike
  routes); `agents/edit_mode/`, `agents/override_system/` (Edit Mode
  overrides: `override_resolver._apply_text_overrides`), `agents/slot_system/`,
  `agents/director_agent/`, `agents/design_intelligence/`.
- The builder: `builder_v2.py`, `builder_loop.py`, `site_kit.py`,
  `site_kit_church.py`, `site_objects.py`, `site_scenes.py`, `site_layouts.py`,
  `site_pages.py` (`slice_pages`), `site_multipage.py`, `site_modules/`
  (the old assembler, now fallback), `design_coach.py`, `vision_grader.py`,
  `site_check.py` (looks at the LIVE site), `site_llm.py`, `site_concept.py`.
- `studio_*.py` — the older Studio design system / validators and the
  Light Table (`studio_light_table.py`, `/ai/images/studio`).
- Hand-built: `sites/<dir>/build.py` (contract: `SLUG`, `BUSINESS_ID`,
  `render_pages()`, optional `REDIRECTS`) → `site_sync.py` writes the row on
  boot when the hash changes (`site_config.html_source = "manual"`).
- Forms + doors: `website_forms.py`, `site_doors.py`, `site_concierge.py`,
  `site_news.py`, `site_analytics.py`, `public_form_theme.py`,
  `form_page_renderer.py`, `booking_page_renderer.py`,
  `booking_page_router.py` (`/booking-page`), `booking_widget_router.py`,
  `agent_site.py` (`/public/agent/{slug}/…`), `sermons_public.py`.
- Domains: `cloudflare_saas.py` (custom hostnames, fails open without
  `CF_API_TOKEN`), `custom_domain_cache.py` (no shared cache for custom
  domains), `infra/cloudflare_saas_worker.js` (deployed by hand in
  Cloudflare, not by merge).
- Marketing site: `marketing_pages.py` (`_tier_dials`, price cards),
  `marketing_home_v3.py`, `church_site.py` + `church_site/`,
  `coach_site.py` + `coach_site/`, `churchsavvy_site.py` + `churchsavvy_site/`,
  `legal_content.py`, `brand_voice.py`.
- Chief's site verbs (shared with chief): `chief_site_design.py`,
  `chief_site_view.py` (`edit_site_text`, `check_site`).
- Tables: `business_sites` (`site_config`, `html_content`; server-owned:
  only anon read of a published site, no practitioner policy), `site_events`,
  `website_form_messages`. Domain lives in `site_config` (owner-only key).

Frontend (`solutionist-studio`):
- `src/core/components/PractitionerBuild.tsx` (Build tab) → `MySite.tsx`,
  `MySitePhone.tsx`, `ComposedSiteControls.tsx`, `DesignCoach.tsx`,
  `StyleInterview.tsx`, `ChiefInterview.tsx`, `ChiefDesignHandoff.tsx`,
  `SitePublishToggle.tsx`, `SiteRevisionPanel.tsx`, `SitePath.tsx`,
  `CustomDomainPanel.tsx`, `DesignStudio.tsx`, `DesignStudioHost.tsx`.
- `src/features/mysite/` (SlotManagement, `EditMode/iframeBridge.ts`),
  `src/core/lib/siteNews.ts`, `src/core/components/funnel/WebsiteTraffic.tsx`.

## 3. Rules that must not break

- `public_site_router` is registered LAST in `kmj_intake_automation.py`.
  Any new public route (or API path a site page could shadow) goes above
  it. A hand-built page id must never shadow an API path (`/live` is an
  authed API and 401s; `site_sync` refuses it).
- `X-Original-Host` is client-supplied: it may only pick which public site
  answers, never grant anything. Custom-domain responses never get a
  shared CDN cache (`custom_domain_cache.py`).
- Write `business_sites` as the server (`sb_*_as_service`) after an owner
  check; the user JWT reads it back empty and writes silently fail.
- Every public marketing page passes `__tests__/test_brand_voice.py` (add
  new pages to `_pages()`): no "trade", no "software", Chief is never an
  "AI agent/assistant". Prices, trial and plan words come from the dials
  (`marketing_pages._tier_dials`, `pricing_config`), never typed in.
- Public pages never feature the owner's name, face or signature, nor the
  owner's own church (name, photos, numbers, quotes). Samples use the
  made-up sample church; never a plausible real church name.
- Every sentence on a product page is a promise: check it against the code
  (`test_lit_rooms.py::test_a_room_says_only_what_the_product_does` holds
  retired lines).
- Legal path: ideas yes, code/words/templates/a whole recognizable look no.
  Reference sites feed mood words only (`test_reference_mood_only.py`).
  No GSAP or new animation library in the builder without a license check.
- Kit pages: Edit Mode keys only text-only elements (`site_kit.edit_keys`);
  an edit must never flatten a kit section.
- A new self-metering module (calls `log_api_usage` and the LLM seam) joins
  `llm_call._SELF_METERING` or `test_llm_seam_metering` fails.
- Paid builds and graders run on production's Anthropic key — state the
  cost before running one.

## 4. Traps already hit

- `http://<custom domain>/x` bounced to the Railway host (404): fix the http hop before any cut-over.
- A church with email at the apex needs an ALIAS at `@`, not "CNAME @" — a CNAME kills its mail.
- www without delegated DCV has no certificate; pre-validate both hostnames before DNS moves.
- `Referrer-Policy: no-referrer` makes form POSTs send `Origin: null`; unit tests miss it — check in a real browser.
- Multi-page "Separate pages" slices the home by keyword guess (`site_pages._PAGE_HINTS`): sections misfile, church kit sections match nothing, menus stay #anchors.
- A sliced page runs the home's whole script; a missing element can kill later script (phone menu).
- Kit edit keys are positional (`v2/auto_N`); one new event moved most keys. Words sheet isn't stored.
- Refine-a-section / revision rounds are builder_v2-only (`_is_builder_page`); kit pages 409.
- Real builds feed the kit no ministries/events (`fx_from_ctx`), the cause of thin church pages.
- Re-renders that pass no status left a stale `dro_failure` → Chief advised a paid recompose.
- The grader sees stills only: a fade-in hid a whole scene and still passed. Don't trust it on motion.
- A width check misses text off the phone when the page hides sideways scroll; grid items need `minmax(0,1fr)`.
- anthropic 0.34.2 drops thinking signatures on stream replay (builder loop 400'd) — `_stream` rebuilds blocks.
- Manual sites: an offerings save must not overwrite them (`refresh_if_composed` no-ops on `manual`).
- Composed sites' frozen contact script thanks on ANY JSON reply; new error codes lose messages silently.
- `crypto.randomUUID()` with no fallback silently broke Send on old iOS Safari.
- Build jobs run in-process on web (`asyncio.create_task`); a deploy kills a running build.

## 5. How to check work

- `python -m pytest -q __tests__/test_site_*.py __tests__/test_builder_v2.py __tests__/test_builder_loop.py`
- Public/marketing: `test_brand_voice.py`, `test_lit_rooms.py`, `test_marketing_site_pricing.py`,
  `test_church_site.py`, `test_coach_site.py`, `test_churchsavvy_site.py`, `test_public_site_url.py`.
- Hand-built: `test_site_sync.py`, `test_site_manual_source.py`, `test_site_redirects.py`,
  `test_site_love_city.py` (sends every page through the real routers).
- Domains: `test_custom_domain_cache.py`, `test_custom_domain_www.py`, `test_custom_domain_ctas.py`.
- Forms/edits: `test_website_forms.py`, `test_site_matched_form_routes.py`, `test_edit_site_text.py`,
  `test_published_overrides.py`, `test_slot_override_owner_gate.py`, `test_business_sites_server_owned.py`.
- Kit: `test_site_kit.py`, `test_site_kit_church.py`, `test_site_kit_audit.py`, `test_site_kit_wiring.py`.
- Frontend: `npx tsc -p tsconfig.app.json --noEmit` (no new errors over baseline), `npx vite build`,
  preview `npx vite --port 5181` → `/tests/mysite-preview.html?state=composed&phone=1`.
- Look at pages at 390 and 1440 wide in Playwright; behaviour (forms, motion) in a real browser.
- After deploy: `curl -I https://<domain>/<page>` → `X-Solutionist-Source: manual-site` for hand-built.
- Switches (`SITE_KIT`, `SITE_SCENES`, `SITE_BOLD_OPENING`, `SITE_PHOTOS_FIRST`, `SITE_SYNC`, `SITE_CHECK`,
  `CHURCH_SITE`, `COACH_SITE`): read Railway names before assuming; unset usually means owner-only/off.

## 6. Edges

- **chief:** Chief's site verbs and the "website ask goes to the Coach" routing live in `chief_*` files;
  coordinate before changing `chief_site_design.py` / `chief_site_view.py`.
- **money:** giving forms on sites (`giving_router.fill_give_slots`), price dials and plan words.
- **messaging:** form notifications, `{{BUSINESS_EMAIL}}` comes from the verified sender (email setup).
- **member-app:** `/my` lives under the same host routing; `sermons_public.py` is shared with member-app
  and live-media (watch pages).
- **live-media:** a site's watch page embeds YouTube live or the relay player.
- **system:** router order in `kmj_intake_automation.py`, the Cloudflare Worker, Railway env switches.
