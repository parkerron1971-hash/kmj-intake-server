# __tests__/test_image_optimization.py
#
# Image optimization (2026-08-02) from the site-builder audit.
#
# Measured on a live composed page BEFORE this change: 13 images,
# 12.8 MB, zero srcset. Heroes were 2.4 MB PNGs straight off DALL-E and
# a phone downloaded the full desktop asset every visit. The same page
# through Supabase's transform endpoint: 0.71 MB (95% smaller).

import re

import public_site as ps

SB = "https://brqjgbpzackdihgjsorf.supabase.co/storage/v1"
IMG = f"{SB}/object/public/business-assets/biz/gallery/hero.png"


def _one(tag: str) -> str:
    return ps._optimize_images(f"<html><body>{tag}</body></html>")


def test_supabase_image_is_resized_and_gets_a_srcset():
    out = _one(f'<img src="{IMG}" alt="hero">')
    assert "/render/image/public/" in out
    assert "width=1200" in out
    assert "resize=contain" in out          # without it the image squishes
    assert 'srcset="' in out
    for w in (400, 800, 1200, 1600):
        assert f"{w}w" in out


def test_aspect_ratio_is_preserved_on_every_srcset_entry():
    """resize=contain on the src but not the srcset would ship squished
    images to most viewports — the failure is invisible on desktop."""
    out = _one(f'<img src="{IMG}">')
    urls = re.findall(r"(https://[^\s,\"]+)\s+\d+w", out)
    assert urls, "no srcset urls parsed"
    for u in urls:
        assert "resize=contain" in u


def test_first_image_stays_eager_and_the_rest_go_lazy():
    """The first image is almost always the hero — the LCP element.
    Lazy-loading it makes the page measurably slower, not faster."""
    out = ps._optimize_images(
        f'<img src="{IMG}"><img src="{IMG}"><img src="{IMG}">')
    tags = re.findall(r"<img\b[^>]*>", out)
    assert 'loading="lazy"' not in tags[0]
    assert 'loading="lazy"' in tags[1]
    assert 'loading="lazy"' in tags[2]
    assert all('decoding="async"' in t for t in tags)


def test_existing_attributes_are_never_clobbered():
    out = _one(f'<img src="{IMG}" alt="A portrait" class="hero" loading="eager">')
    assert 'alt="A portrait"' in out
    assert 'class="hero"' in out
    assert 'loading="eager"' in out
    assert out.count("loading=") == 1


def test_non_supabase_images_are_left_alone():
    for src in ("https://images.unsplash.com/photo-123?w=1080",
                "data:image/png;base64,iVBORw0KGgo=",
                "/local/asset.png"):
        out = _one(f'<img src="{src}">')
        assert "render/image" not in out
        assert "srcset" not in out


def test_vectors_and_gifs_are_skipped():
    for ext in (".svg", ".gif", ".ico"):
        src = f"{SB}/object/public/business-assets/biz/mark{ext}"
        out = _one(f'<img src="{src}">')
        assert "render/image" not in out, f"{ext} should not be transformed"


def test_a_tag_that_already_has_srcset_is_untouched():
    tag = f'<img src="{IMG}" srcset="{IMG} 800w">'
    assert _one(tag).count("srcset") == 1


def test_already_transformed_urls_are_not_double_wrapped():
    src = f"{SB}/render/image/public/business-assets/biz/hero.png?width=800"
    out = _one(f'<img src="{src}">')
    assert out.count("render/image") == 1
    assert "srcset" not in out


def test_pages_without_supabase_images_are_returned_unchanged():
    html = "<html><body><p>no images here</p></body></html>"
    assert ps._optimize_images(html) is html


def test_never_raises_on_malformed_markup():
    for junk in ("<img", "<img src=>", "<img src='", "", None):
        try:
            ps._optimize_images(junk if junk is not None else "")
        except Exception as e:
            raise AssertionError(f"raised on {junk!r}: {e}")


def test_ampersands_are_escaped_in_attributes():
    """An unescaped & in an attribute is only safe while no param name
    spells an HTML entity. Escaping means it never can."""
    out = _one(f'<img src="{IMG}">')
    assert "&amp;quality=" in out
    assert "&amp;resize=" in out
    # No bare & survived (every one should be the start of &amp;).
    assert not re.search(r"&(?!amp;)", out)


def test_it_runs_last_in_augment_so_injected_sections_are_covered():
    """Products and gallery sections are injected into the HTML after
    the head work — the rewrite has to come after them or their images
    ship full-size."""
    import inspect
    src = inspect.getsource(ps._augment_html)
    assert src.index("_inject_dynamic_sections") < src.index("_optimize_images")
