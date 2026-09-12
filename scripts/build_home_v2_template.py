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
    j = s.index('    <section class="cmp" id="compare">')   # compare sits under pricing since v16
    s = s[:i] + "{{PRICING}}\n\n" + s[j:]
    s = rep(s, "  /* v8: pricing, the live site's setup */",
            r"""  /* the live price cards (_price_cards_html) and the founding strip (_founder_strip_html), styled in this page's tokens */
  .price-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
  .price-card{position:relative;display:flex;flex-direction:column;gap:12px;padding:26px 24px 24px;border:1px solid var(--line);border-radius:var(--r-lg);background:var(--bg-2);transition:transform .35s var(--spring),border-color .3s}
  .price-card:hover{transform:translateY(-4px);border-color:color-mix(in srgb,var(--accent) 40%,var(--line))}
  .price-card.is-mid{border-color:color-mix(in srgb,var(--accent) 55%,var(--line));box-shadow:0 0 80px -40px var(--accent)}
  .price-card .ribbon{position:absolute;top:-12px;left:24px;font:600 10px var(--mono);letter-spacing:.1em;text-transform:uppercase;padding:4px 10px;border-radius:999px;background:var(--accent);color:#fff}
  .price-name{font:600 15px var(--display);letter-spacing:-.01em}
  .price-fig{display:flex;align-items:baseline;gap:6px}
  .price-fig b{font:600 44px var(--display);letter-spacing:-.04em;line-height:1;font-variant-numeric:tabular-nums;display:inline-block;min-width:3.2ch}
  .price-fig b.roll{animation:numRoll .5s var(--ease)}
  .price-fig span{font:500 13px var(--body);color:var(--muted)}
  .price-billed{font-size:12px;color:var(--dim);margin-top:-8px;min-height:16px;font-variant-numeric:tabular-nums}
  .price-card p{margin:0;font-size:13.5px;color:var(--muted);line-height:1.5}
  .price-facts{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:8px;font-size:13px;color:var(--muted)}
  .price-facts li{display:flex;gap:9px;align-items:flex-start;flex-wrap:wrap}
  .price-facts li::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--accent);margin-top:7px;flex-shrink:0;box-shadow:0 0 8px var(--accent)}
  .price-facts li.credits{color:var(--text);font-weight:600}
  .price-facts li.credits small{flex-basis:100%;padding-left:15px;font-weight:400;color:var(--dim);font-size:11.5px}
  .price-cta{margin-top:auto;display:inline-flex;align-items:center;justify-content:center;gap:8px;height:42px;padding:0 20px;border-radius:999px;font-weight:600;font-size:13px;border:1px solid var(--line-2);background:rgba(13,15,20,.6);color:var(--text);text-decoration:none;transition:background .2s,border-color .2s,transform .2s var(--spring)}
  .price-cta:hover{background:var(--bg-3);transform:translateY(-1px)}
  .price-cta.is-mid{background:var(--accent);border-color:transparent;color:#fff}
  .price-cta.is-mid:hover{filter:brightness(1.08);box-shadow:0 8px 30px -8px var(--accent)}
  .founder{margin:0 0 14px;display:grid;grid-template-columns:auto 1fr auto;gap:22px;align-items:center;padding:18px 24px;border:1px solid color-mix(in srgb,#F3C56B 45%,var(--line));border-radius:var(--r-lg);background:linear-gradient(90deg,color-mix(in srgb,#F3C56B 10%,var(--bg-2)),var(--bg-2) 60%)}
  .founder .seal{font:500 10px var(--mono);letter-spacing:.16em;text-transform:uppercase;color:#F3C56B;padding:5px 12px;border:1px solid color-mix(in srgb,#F3C56B 45%,transparent);border-radius:999px;white-space:nowrap}
  .founder .copy{font-size:13.5px;color:var(--muted);line-height:1.5}
  .founder .copy b{color:var(--text);font-weight:600}
  .founder .meter{height:4px;margin-top:10px;background:rgba(255,255,255,.08);border-radius:2px;overflow:hidden;max-width:420px}
  .founder .meter i{display:block;height:100%;background:#F3C56B;transition:width 1.2s var(--ease)}
  .founder .left{font:400 11px var(--mono);color:#F3C56B;margin-top:6px}
  .founder>a{color:#F3C56B;font-weight:600;font-size:13.5px;text-decoration:none;white-space:nowrap}
  .founder.is-gone{border-color:var(--line);background:transparent}
  .founder.is-gone .seal,.founder.is-gone .left{color:var(--muted);border-color:var(--line-2)}
  .founder.is-gone .meter i{background:var(--muted)}
  @media (max-width:900px){.price-grid{grid-template-columns:1fr}.founder{grid-template-columns:1fr;gap:10px}}

  /* v8: pricing, the live site's setup */""")
    # the count-up and the switch read the live cards' hooks
    s = rep(s, "document.querySelectorAll('.tier .num').forEach((n,i)=>{n.textContent='$0';setTimeout(()=>countTo(n,+n.dataset.monthly,900),120*i)});",
            "document.querySelectorAll('.pc-num').forEach((n,i)=>{n.textContent='$0';setTimeout(()=>countTo(n,+n.dataset.monthly,900),120*i)});")
    s = rep(s, "    document.querySelectorAll('.tier .num').forEach(n=>{n.classList.remove('roll');void n.offsetWidth;n.classList.add('roll');countTo(n,+(annual?n.dataset.annual:n.dataset.monthly),500)});\n    document.querySelectorAll('.tier .billed').forEach(n=>{n.innerHTML=annual?n.dataset.annual:'&nbsp;'});",
            "    document.querySelectorAll('.pc-num').forEach(n=>{n.classList.remove('roll');void n.offsetWidth;n.classList.add('roll');countTo(n,+(annual?n.dataset.annual:n.dataset.monthly),500)});\n    document.querySelectorAll('.price-billed').forEach(n=>{n.innerHTML=annual?n.dataset.annual:'&nbsp;'});")

    # ── compare: the plan differences come from the gate map ──
    i = s.index('<!-- PLAN TABLE -->')
    j = s.index('<!-- /PLAN TABLE -->', i) + len('<!-- /PLAN TABLE -->')
    s = s[:i] + "{{COMPARE_TIERS}}" + s[j:]
    s = rep(s, '<b data-to="79">$79</b><em>/mo</em>', '<b data-to="{{STARTER_PRICE}}">${{STARTER_PRICE}}</b><em>/mo</em>')

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
