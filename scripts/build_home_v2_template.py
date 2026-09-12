"""Turn the design concept (solutionist-studio/design/bridgemind-hero-concept/
solutionist-hero-concept.html, the artifact Kevin approved cut by cut on
2026-09-11) into marketing_home_v2.html, the template marketing_home_v2.py
renders as the home page.

Run once per concept cut, from the repo root:
    python scripts/build_home_v2_template.py [path/to/solutionist-hero-concept.html]
and commit the template. What it changes on the way in:
  * the embedded film and poster become /assets/film.mp4 and /assets/film-poster.jpg
  * the concept's note bar, Listen control and design-notes table go
  * the concept's own founding-seat flyer goes; the live one
    (marketing_founder_ad) is injected by the renderer
  * the pricing band becomes a placeholder the renderer fills from the
    live dials (the same _founder_strip_html / _price_cards_html the old
    home used, so every pricing test keeps its contract)
  * the plan-difference table becomes a placeholder built from
    _COMPARE_GROUPS + FEATURE_MIN_PLAN, so it can never promise a
    difference the code does not enforce
  * absolute links to mysolutionist.app become root-relative; Log in
    points at the app; the trial length is the sentinel _fill_trial fills
  * head metadata, the pixel and the first-party analytics scripts are
    placeholders the renderer fills the way _render_shell does
"""
from __future__ import annotations

import io
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_SRC = pathlib.Path(r"C:\Users\kmccl\solutionist-studio\solutionist-studio\design\bridgemind-hero-concept\solutionist-hero-concept.html")
OUT = HERE / "marketing_home_v2.html"


def cut(s: str, start: str, end: str, keep_end: bool = True) -> str:
    i = s.index(start)
    j = s.index(end, i)
    return s[:i] + (s[j:] if keep_end else s[j + len(end):])


def rep(s: str, old: str, new: str, count: int = 1) -> str:
    assert s.count(old) == count, (old[:80], s.count(old))
    return s.replace(old, new)


def build(src: pathlib.Path) -> str:
    s = io.open(src, encoding="utf-8").read()

    # ── the film lives at /assets, not in the page ──
    s = re.sub(r"const FILM='data:video/mp4;base64,[A-Za-z0-9+/=]+';", "const FILM='/assets/film.mp4?v=2';", s)
    s = re.sub(r'poster="data:image/jpeg;base64,[A-Za-z0-9+/=]+"', 'poster="/assets/film-poster.jpg?v=2"', s)
    assert "base64," not in s, "an embedded asset survived"

    # ── concept-only furniture ──
    s = cut(s, '  <div class="note">', "  <nav class=\"top reveal\"")
    s = cut(s, "  /* ---------- Listen ---------- */", "})();\n</script>")
    s = cut(s, '    <details class="notes" id="notes">', "  </main>")
    # the concept's founding flyer (markup, css, script): the live one is injected
    s = cut(s, '  <div class="fad" id="founderAd"', '  <button type="button" id="askFab"')
    s = cut(s, "  /* v8: the founding-seat flyer (marketing_founder_ad.py, in this page's tokens) */", "  /* v9: every screen, real frames, nothing tilted */")
    s = cut(s, "  /* v8: the founding-seat flyer — five seconds of reading", "  /* v9: the prices count.")
    s = rep(s, '  <button type="button" id="askFab"', '{{FOUNDER_AD_MARKUP}}\n  <button type="button" id="askFab"')
    # the live flyer's CSS reads the shell's token names; alias them
    s = rep(s, "  /* v8: the film */\n  .hero-pill",
            "  /* the live founding flyer (marketing_founder_ad) reads the shell's token names */\n"
            "  :root{--text-primary:var(--text);--text-secondary:var(--muted);--text-muted:var(--dim);--text-dim:var(--dim);--border:var(--line);--border-strong:var(--line-2);--font-heading:var(--display);--font-body:var(--body);--font-mono:var(--mono);--surface:var(--bg-2);--accent-2:#22D3EE;--ink-on-accent:#fff}\n"
            "{{FOUNDER_AD_CSS}}\n  /* v8: the film */\n  .hero-pill")

    # ── pricing: the live cards and strip, in the concept's frame ──
    i = s.index('    <section class="pricing chapter" id="pricing">')
    j = s.index('    <section class="plans" id="plans">')   # the plan matrix follows pricing since v17
    s = s[:i] + "{{PRICING}}\n\n" + s[j:]
    # v18: the pricing stylesheet and the count-up/switch hooks (.pc-num, .price-billed) now live in the concept itself
    assert "  /* v18: pricing." in s and ".pc-num" in s, "the concept's v18 pricing block is missing"

    # ── compare: the plan differences come from the gate map ──
    i = s.index('<!-- PLAN TABLE -->')
    j = s.index('<!-- /PLAN TABLE -->', i) + len('<!-- /PLAN TABLE -->')
    s = s[:i] + "{{COMPARE_TIERS}}" + s[j:]
    s = rep(s, '<b data-to="79">$79</b><em>/mo</em>', '<b data-to="{{STARTER_PRICE}}">${{STARTER_PRICE}}</b><em>/mo</em>')
    s = rep(s, '<span class="pl">Starter<b>$79</b></span><span class="pl hot">Professional<b>$149</b><i>most chosen</i></span><span class="pl">Solutionist<b>$299</b></span>',
            '<span class="pl">Starter<b>${{STARTER_PRICE}}</b></span><span class="pl hot">Professional<b>${{PRO_PRICE}}</b><i>most chosen</i></span><span class="pl">Solutionist<b>${{SOL_PRICE}}</b></span>')

    # ── links ──
    s = s.replace('href="https://system.mysolutionist.app/"', 'href="{{APP_URL}}"')
    s = s.replace('href="https://mysolutionist.app/', 'href="/')
    s = s.replace("href=\"https://mysolutionist.app/assets/film.mp4?v=2\" target=\"_blank\" rel=\"noopener\"", "href=\"/assets/film.mp4?v=2\" target=\"_blank\" rel=\"noopener\"")
    assert "mysolutionist.app/" not in s.replace("mysolutionist.app/compare", "").replace("https://mysolutionist.app/'", ""), "an absolute link survived"
    s = rep(s, "7 days free · every action logged and reversible", "__TRIAL_FREE__ · every action logged and reversible")
    s = rep(s, "7 days free on every plan.", "__TRIAL_FREE__ on every plan.", 0) if "7 days free on every plan." in s else s

    # ── every trial promise is the sentinel, so a zero-day trial never reads "0 days free" ──
    s = rep(s, "Seven days free. Every action logged and reversible. Say what you do and start.", "__TRIAL_FREE__. Every action logged and reversible. Say what you do and start.")
    s = rep(s, "<summary>What does the free week include?</summary><p>The whole room, on the plan you pick, for seven days. No card charged until the week is up, and you can leave before then with nothing owed.</p>",
            "<summary>What does the free trial include?</summary><p>The whole room, on the plan you pick. __TRIAL_FREE__, no card charged until the trial ends, and you can leave before then with nothing owed.</p>")
    assert "days free" not in s.replace("__TRIAL_FREE__", ""), "a hard-coded trial promise survived"

    # ── the film's live note is no longer needed ──
    s = cut(s, '      <div class="live">Live, this is', "    </div>\n  </div>\n\n{{FOUNDER_AD_MARKUP}}")

    # ── head: the shell's metadata, the pixel; tail: the analytics ──
    s = rep(s, "<title>Solutionist Hero, Bridgemind Cut</title>",
            "<title>Every problem has a solution &middot; The Solutionist System</title>\n"
            "<meta name=\"description\" content=\"{{DESCRIPTION}}\">\n"
            "<meta property=\"og:title\" content=\"Every problem has a solution &middot; The Solutionist System\">\n"
            "<meta property=\"og:description\" content=\"{{DESCRIPTION}}\">\n"
            "<meta property=\"og:url\" content=\"https://mysolutionist.app/\">\n"
            "<link rel=\"canonical\" href=\"https://mysolutionist.app/\">\n"
            "<meta property=\"og:type\" content=\"website\">\n"
            "<meta property=\"og:site_name\" content=\"The Solutionist System\">\n"
            "<meta property=\"og:image\" content=\"https://mysolutionist.app/assets/og.png?v=4\">\n"
            "<meta property=\"og:image:width\" content=\"1200\">\n"
            "<meta property=\"og:image:height\" content=\"630\">\n"
            "<meta name=\"twitter:card\" content=\"summary_large_image\">\n"
            "<meta name=\"twitter:image\" content=\"https://mysolutionist.app/assets/og.png?v=4\">\n"
            "<link rel=\"icon\" type=\"image/png\" href=\"/favicon.png\">\n"
            "<link rel=\"apple-touch-icon\" href=\"/favicon.png\">\n"
            "{{PIXEL}}")
    # the concept is an artifact fragment (no html/head/body); the site serves a document
    s = ('<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8">\n'
         '<meta name="viewport" content="width=device-width,initial-scale=1.0">\n' + s)
    s = rep(s, "</style>\n", "</style>\n</head>\n<body>\n")
    s = s.rstrip() + "\n{{ANALYTICS}}\n</body>\n</html>\n"

    # ── the footer reaches the FAQ page and the contact address ──
    s = rep(s, '<a href="#faq">Questions</a>', '<a href="#faq">Questions</a><a href="/faq">All questions</a>')
    s = rep(s, '<a href="/privacy">Privacy</a></div>', '<a href="/privacy">Privacy</a><a href="mailto:__CONTACT_EMAIL__">Contact</a></div>')
    # ── the sample copy names no place (test_about_page: the site no longer says where it was made) ──
    s = s.replace(" · Grand Rapids, MI", " · in person and online").replace(" · Grand Rapids", " · walk-ins welcome")
    s = s.replace("we build it to last through Michigan winters", "we build it to last through hard winters")
    assert "Michigan" not in s and "Grand Rapids" not in s

    # ── footer fine print ──
    s = re.sub(r"© The Solutionist System · [A-Za-z]+ cut of the concept · the room runs on sample data · prices are the live ones",
               "&copy; {{YEAR}} The Solutionist System LLC · the room above runs on sample data", s)
    s = re.sub(r"<div class=\"fine\"[^\n]*", "", s)  # no leftover note bar
    return s


if __name__ == "__main__":
    src = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC
    out = build(src)
    io.open(OUT, "w", encoding="utf-8", newline="\n").write(out)
    print(f"wrote {OUT} ({len(out):,} chars)")
