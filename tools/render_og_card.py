"""Render static/brand/solutionist-og.png from solutionist-og-card.html.

    python tools/render_og_card.py

The July card was screenshotted from a page nobody kept, so when the hero
copy changed there was nothing to re-render from. This script and the
card next to the PNG are that missing piece.

Two things it refuses to do quietly:

  * ship a card in the wrong typeface. Inter Tight comes from Google
    Fonts at render time, and a headless browser with no network falls
    back to system-ui and screenshots something that looks almost right.
    The run fails instead.
  * ship a card at the wrong size. og:image:width says 1200x630, so the
    output is asserted to be exactly that.

It renders at 2x and downsamples, because text at 1x in a headless
screenshot is noticeably softer than the same card viewed on a phone.

After running, bump the ?v= on the og:image / twitter:image tags in
marketing_pages.py and legal_content.py or caches keep the old picture.
"""
from __future__ import annotations

import io
import pathlib
import sys

BRAND = pathlib.Path(__file__).resolve().parent.parent / "static" / "brand"
CARD = BRAND / "solutionist-og-card.html"
OUT = BRAND / "solutionist-og.png"
W, H = 1200, 630
SCALE = 2


def main() -> int:
    from playwright.sync_api import sync_playwright
    from PIL import Image

    if not CARD.exists():
        print(f"card source missing: {CARD}")
        return 1

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport={"width": W, "height": H}, device_scale_factor=SCALE
        )
        page.goto(CARD.as_uri())
        page.wait_for_load_state("networkidle")
        page.evaluate("document.fonts.ready")

        # The whole point of the card is the wordmark and the statement.
        # If the webfont did not arrive, this is system-ui wearing the
        # right colours, and it is not obvious in a thumbnail.
        #
        # NOT document.fonts.check(). That returns true for a family the
        # page has never heard of, because it answers "can this text be
        # rendered", and it always can: the stack falls through to a
        # system face. Sabotaging the family name to "Nope Face" still
        # returned true, so the first version of this guard would have
        # waved through the exact failure it was written to catch.
        # FontFace status is the thing that actually knows.
        faces = page.evaluate(
            "[...document.fonts].map(f => f.family + '|' + f.status)"
        )
        missing = [
            fam for fam in ("Inter Tight", "Inter")
            if not any(f.split("|")[0].strip("'\"") == fam
                       and f.endswith("|loaded")
                       for f in faces)
        ]
        if missing:
            browser.close()
            print(f"webfont(s) never loaded: {missing}")
            print(f"font faces present: {faces or '(none)'}")
            print("refusing to render a card in the wrong typeface")
            return 1

        shot = page.screenshot(clip={"x": 0, "y": 0, "width": W, "height": H})
        browser.close()

    img = Image.open(io.BytesIO(shot)).convert("RGB")
    if img.size != (W * SCALE, H * SCALE):
        img = img.resize((W * SCALE, H * SCALE), Image.LANCZOS)
    img = img.resize((W, H), Image.LANCZOS)
    assert img.size == (W, H), img.size
    img.save(OUT, "PNG", optimize=True)

    print(f"wrote {OUT}  {img.size[0]}x{img.size[1]}  "
          f"{OUT.stat().st_size // 1024} KB")
    print("now bump ?v= on og:image / twitter:image in marketing_pages.py "
          "and legal_content.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
