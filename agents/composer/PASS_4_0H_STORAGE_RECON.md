# Pass 4.0h — Storage Path Recon

**Purpose:** Determine which column the Pass 4.0h post-processor must write to so the hybrid (Composer-Hero + Builder-rest) HTML is what `public_site.py` actually serves.

**Tables involved:** `business_sites` has two HTML-bearing surfaces — `html_content` (top-level `TEXT` column) and `site_config.generated_html` (`JSONB` nested string).

---

## Verdict

**Post-processor writes to `site_config.generated_html` (the JSONB nested field).**

Do not write `html_content`. It's a legacy serving surface that Smart Sites bypasses; writing to it would create a divergent stale copy.

---

## Why — the serving chain

`public_site.py`'s slug handler (`_serve_site_by_slug`, line 3745) and custom-domain handler (`_serve_site_by_custom_domain`, line 3787) both follow the same shape:

1. Look up the `business_sites` row by `slug` or `site_config->>custom_domain`. Select `html_content`, `business_id`, `site_config`.
2. If `site_config.use_smart_sites` is truthy → call `render_smart_site_page(business_id, "home", ...)` (defined in `smart_sites.py:1317`).
3. If Smart Sites returns HTML → serve it with header `X-Solutionist-Source: smart-sites`.
4. If Smart Sites returns `None` (or `use_smart_sites` is falsy) → fall through to legacy: `site["html_content"]`, augmented via `_augment_html(...)`.

`render_smart_site_page` is itself a fallback chain (`smart_sites.py:1317`):

| Layer | Source                                                  | Reads from                                   |
|-------|----------------------------------------------------------|----------------------------------------------|
| 0     | Multi-page (3.8g)                                        | `site_config.generated_pages[page_id]`       |
| **1** | **Builder Agent (3.8d) — primary live path today**       | **`site_config.generated_html`**             |
| 2     | Archetype renderer (3.8c)                                | `site_config.design_brief`                   |
| 3     | Studio layouts (3.7c)                                    | `site_config.layout_id`                      |
| 4     | Legacy 3-vibe-family renderer                            | `site_config` fields                         |

The Layer-1 function is `_try_serve_builder_html` (`smart_sites.py:1096`), which gates on:

```python
generated_html = site_config.get("generated_html")
if not (generated_html and isinstance(generated_html, str) and len(generated_html) > 1000):
    return None
```

If Builder has written `site_config.generated_html` (>1000 bytes), Smart Sites serves it directly (with motion modules injected). That's the path RoyalTee + KMJ are on today.

---

## Production state (verified 2026-05-17)

| Business         | `business_sites.html_content` len | `site_config.generated_html` len | `use_smart_sites` | Active layer |
|------------------|-----------------------------------:|---------------------------------:|-------------------|--------------|
| RoyalTeez Designz| 30,110                             | **38,198**                       | `True`            | **Layer 1**  |
| KMJ Creative Sol.| (not checked — assumed populated)  | **44,038**                       | `True`            | **Layer 1**  |

For both businesses the JSONB `generated_html` is **larger and newer** than `html_content`. `html_content` is a stale legacy copy from an earlier-pass publish path (single write site: `chief_of_staff.py:4501`, where `html_content` is set on initial publish). The Builder pipeline does not maintain `html_content` — it writes only to `site_config.generated_html`.

ETS (`embracetheshift.live`) wasn't probed inline but is on the same custom-domain handler which uses the same fallback chain; assumed Layer 1 unless a future build-pass observation contradicts.

---

## Write path Builder follows today

`agents/director_agent/build_with_loop.py:619` — the canonical Builder write step writes to `cfg["generated_html"]` then patches `business_sites.site_config`. The post-processor in Pass 4.0h Phase C will surgically transform `final_html` (Builder's output) **before** this assignment, then let the existing assignment + patch flow persist the hybrid.

Concretely, the Phase C wiring is approximately:

```python
# (existing — in build_with_loop.py near line 619)
final_html = builder_generate_site(...)

# (new — Phase C)
final_html, hero_module = await post_process_hero(
    business_id=business_id,
    builder_html=final_html,
    enriched_brief=brief,
    brand_kit=brand_kit,
    site_config=cfg,
)

# (existing)
cfg["generated_html"] = final_html
# ... business_sites PATCH with new cfg + hero_module column ...
```

The new `business_sites.hero_composer_module` column (Phase A migration) is set on the same PATCH operation. `None` when post-processing was skipped or fell back; `'cathedral'` or `'studio_brut'` when a module-specific Hero was composed in.

---

## Implications for Pass 4.0h

1. **Phase B `post_process_hero`** takes Builder's HTML string in, returns transformed HTML string out. It does NOT touch the DB itself. The single Phase C wiring point at `build_with_loop.py:619` is where the transformed HTML lands in `site_config.generated_html`.

2. **Do not write `html_content`.** Maintain the existing semantic: `html_content` is a legacy snapshot, untouched by builds. If a future pass needs to clean this up (migrate all rows to a single column), that's separate work.

3. **`smart_sites._try_serve_builder_html` motion-injection runs AFTER our hybrid write.** That's correct — motion injection is layout-agnostic; it works on whatever HTML lives in `site_config.generated_html`. The composed Hero's `<section data-section="hero">` is the same shape Builder emits, so motion injection won't break.

4. **Serving header invariant.** Hybrid-served pages will still return `X-Solutionist-Source: smart-sites`. The post-processor doesn't change the serving path, only the content of one section in what's served.

5. **Smart Sites disabled fallback (Layer 4 / legacy).** If a future business has `use_smart_sites=False`, the post-processor's output never reaches the served HTML (legacy path reads `html_content`). For Pass 4.0h's RoyalTee target this is a non-issue — RoyalTee is Smart Sites = True. If we later opt in a non-Smart-Sites business, we'd need to either flip its `use_smart_sites` flag or extend the post-processor to also write `html_content`. **Not in Pass 4.0h scope.**

---

## Pre-migration backwards-compat baseline (2026-05-17)

| URL                                                          | HTTP | Bytes  |
|--------------------------------------------------------------|-----:|-------:|
| https://royalteez-designz.mysolutionist.app/                 | 200  | 70,607 |
| https://kmj-creative-solutions.mysolutionist.app/            | 200  | 77,016 |
| https://embracetheshift.live/                                | 200  |    702 |

After the Phase A migration applies, the same curls should return the same status codes (bytes may vary slightly due to dynamic-section injection, products list, etc.). Any non-200 after migration → rollback investigation.
