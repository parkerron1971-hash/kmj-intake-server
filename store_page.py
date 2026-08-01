"""
store_page.py — hosted storefront HTML renderer (design-inheritance
rebuild, 2026-08-01; original Arc 27 PR2).

Deterministic, platform-authored page. The design DNA now comes from
store_design.resolve() — composed-site tokens (DRO + language) when the
business has a composed site, brand kit otherwise, neutral default last
— so the store visibly belongs to the same business as the site. The
cart is a self-contained vanilla-JS slide-in panel (localStorage, keyed
by slug) that sends ONLY {offering_id, quantity} to
/payments/store-checkout — all pricing is recomputed server-side. Same
trust model as the motion-module injections: this JS is ours, never
LLM-written.

Template uses @TOKEN@ replacement (not f-strings) so CSS/JS braces stay
literal — the heredoc/brace-escaping trap this file exists to avoid.
"""
from __future__ import annotations

import html as _html
import json as _json
from typing import Any, Dict, List, Optional

import brand_dna
import store_design


def _esc(v: Any) -> str:
    return _html.escape(str(v or ""))


def _js_str(v: str) -> str:
    """JSON string literal safe for inline <script> embedding."""
    return _json.dumps(str(v or "")).replace("<", "\\u003c")


# ─── Inline SVG glyphs (no icon font; emoji is against the icon
#     language). stroke=currentColor so they ride the token inks. ──────

_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" '
        'aria-hidden="true">')

_GLYPH_PRODUCT = (_SVG + '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0'
                  'l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0'
                  'l7-4A2 2 0 0 0 21 16Z"/>'
                  '<path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/></svg>')
_GLYPH_COURSE = (_SVG + '<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>'
                 '<path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>')
_GLYPH_PACKAGE = (_SVG + '<path d="m12 3 8.5 4.5v9L12 21l-8.5-4.5v-9z"/>'
                  '<path d="m3.5 7.5 8.5 4.5 8.5-4.5"/>'
                  '<path d="M12 12v9"/><path d="m7.5 5.2 9 4.8"/></svg>')
_CATEGORY_GLYPHS = {"product": _GLYPH_PRODUCT, "course": _GLYPH_COURSE,
                    "package": _GLYPH_PACKAGE}

_DL_SVG = (_SVG.replace('stroke-width="1.8"', 'stroke-width="2.5"')
           + '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
             '<polyline points="7 10 12 15 17 10"/>'
             '<line x1="12" y1="15" x2="12" y2="3"/></svg>')
_DL_BADGE = f'<span class="st-badge">{_DL_SVG}Instant download</span>'

_ARROW_SVG = (_SVG + '<path d="M7 17 17 7"/><path d="M8 7h9v9"/></svg>')
_CART_SVG = (_SVG + '<circle cx="9" cy="21" r="1.6"/>'
             '<circle cx="19" cy="21" r="1.6"/>'
             '<path d="M2.5 3h2l2.3 12.3a2 2 0 0 0 2 1.7h9.5a2 2 0 0 0 '
             '2-1.6L22 7H6"/></svg>')
_CLOSE_SVG = (_SVG + '<path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>')


# ─── Per-language craft accents (small, scoped, token-driven — the
#     store speaks the composed site's language, it doesn't imitate
#     whole site modules). ─────────────────────────────────────────────

_LANGUAGE_CSS: Dict[str, str] = {
    "mural": """
/* MURAL — conviction: monumental caps, painted underline, solid accent. */
.st-lang-mural .st-id h1{text-transform:uppercase;letter-spacing:-0.01em}
.st-lang-mural .st-sec-title{text-transform:uppercase;letter-spacing:.02em;
  box-shadow:inset 0 -0.16em 0 color-mix(in srgb,var(--sx-accent) 55%,transparent);
  padding-bottom:2px}
.st-lang-mural .st-add{background:var(--sx-accent);color:var(--sx-on-accent);
  border-color:var(--sx-accent)}
.st-lang-mural .st-add:hover{background:var(--sx-accent-strong);
  border-color:var(--sx-accent-strong);color:var(--sx-on-accent)}
.st-lang-mural .st-head{background:
  linear-gradient(120deg,color-mix(in srgb,var(--sx-accent) 14%,var(--sx-bg)),var(--sx-bg) 70%)}
""",
    "monograph": """
/* MONOGRAPH — the frame stays quiet; tracking opens, weights lighten. */
.st-lang-monograph .st-id h1{font-weight:500;letter-spacing:.02em}
.st-lang-monograph .st-sec-title{font-weight:500;letter-spacing:.04em}
.st-lang-monograph .st-eyebrow{letter-spacing:.42em}
.st-lang-monograph .st-card{border-color:color-mix(in srgb,var(--sx-text) 10%,transparent)}
.st-lang-monograph .st-go::after{content:"\\2002\\27F6"}
.st-lang-monograph .st-site-link::after{content:"\\2002\\27F6"}
.st-lang-monograph .st-site-link svg{display:none}
""",
    "ledger": """
/* LEDGER — discipline: hairlines, tabular numerals, fine grid ground. */
.st-lang-ledger .st-eyebrow{letter-spacing:.34em}
.st-lang-ledger .st-price,.st-lang-ledger .st-line-price,
.st-lang-ledger .st-panel-total{font-variant-numeric:tabular-nums}
.st-lang-ledger .st-card{border-width:1px;
  border-color:color-mix(in srgb,var(--sx-accent) 30%,var(--sx-border))}
.st-lang-ledger .st-sec-title{letter-spacing:.01em}
.st-lang-ledger .st-head{background-image:
  linear-gradient(color-mix(in srgb,var(--sx-text) 3%,transparent) 1px,transparent 1px),
  linear-gradient(90deg,color-mix(in srgb,var(--sx-text) 3%,transparent) 1px,transparent 1px);
  background-size:72px 72px}
""",
}


_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>@TITLE@ — @STORENOUN@</title>
<meta name="description" content="@STORENOUN@ — @TITLE@">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="@FONTS@" rel="stylesheet">
<style>
@CSSVARS@
*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--sx-bg);color:var(--sx-text);
  font-family:var(--sx-font-body);line-height:1.6}
img{max-width:100%}
button{font-family:inherit}
:focus-visible{outline:2px solid var(--sx-accent);outline-offset:2px}

/* ── Header ── */
.st-head{border-bottom:1px solid var(--sx-border);background:var(--sx-bg)}
.st-head-inner{max-width:1100px;margin:0 auto;display:flex;align-items:center;
  gap:16px;padding:clamp(22px,4.5vw,44px) clamp(18px,4vw,40px)}
.st-logo{width:56px;height:56px;border-radius:14px;object-fit:cover;flex:none}
.st-id{flex:1;min-width:0}
.st-eyebrow{margin:0 0 4px;font-size:.72rem;font-weight:600;color:var(--sx-muted);
  text-transform:uppercase;letter-spacing:.18em}
.st-id h1{font-family:var(--sx-font-heading);font-weight:var(--sx-heading-weight);
  letter-spacing:var(--sx-letter-tight);font-size:clamp(1.6rem,4.5vw,2.5rem);
  margin:0;line-height:1.12}
.st-tag{color:var(--sx-muted);margin:5px 0 0;font-size:.92rem}
.st-site-link{display:inline-flex;align-items:center;gap:6px;flex:none;
  color:var(--sx-accent);text-decoration:none;font-weight:600;font-size:.9rem;
  padding:10px 14px;min-height:44px;border:1px solid var(--sx-border);
  border-radius:var(--sx-radius-button)}
.st-site-link:hover{border-color:var(--sx-accent);background:var(--sx-accent-soft)}
.st-site-link svg{width:15px;height:15px}

/* ── Sections + grid ── */
.st-wrap{max-width:1100px;margin:0 auto;
  padding:clamp(24px,4.5vw,52px) clamp(18px,4vw,40px) 150px}
.st-sec{margin:0 0 clamp(34px,6vw,60px)}
.st-sec-head{display:flex;align-items:baseline;gap:12px;margin:0 0 18px}
.st-sec-title{font-family:var(--sx-font-heading);font-weight:var(--sx-h2-weight);
  letter-spacing:var(--sx-letter-tight);font-size:clamp(1.2rem,2.6vw,1.6rem);margin:0}
.st-sec-count{color:var(--sx-muted);font-size:.82rem}
.st-grid{display:grid;grid-template-columns:1fr;gap:18px}
@media (min-width:560px){.st-grid{grid-template-columns:repeat(2,1fr);gap:20px}}
@media (min-width:920px){.st-grid{grid-template-columns:repeat(3,1fr)}}

/* ── Cards ── */
.st-card{background:var(--sx-surface);border:1px solid var(--sx-border);
  border-radius:var(--sx-radius-card);overflow:hidden;display:flex;
  flex-direction:column;transition:transform .35s var(--sx-ease),
  border-color .35s var(--sx-ease),box-shadow .35s var(--sx-ease)}
.st-card:hover{transform:translateY(-3px);border-color:var(--sx-accent);
  box-shadow:0 14px 34px -18px color-mix(in srgb,var(--sx-accent) 35%,transparent)}
.st-card.st-sold:hover{transform:none;border-color:var(--sx-border);box-shadow:none}
.st-media{position:relative;aspect-ratio:4/3;overflow:hidden;
  background:var(--sx-surface-2)}
.st-img{width:100%;height:100%;object-fit:cover;display:block;
  transition:transform .6s var(--sx-ease)}
.st-card:hover .st-img{transform:scale(1.035)}
.st-ph{width:100%;height:100%;display:flex;align-items:center;justify-content:center;
  background:linear-gradient(135deg,var(--sx-accent-soft),var(--sx-surface-2))}
.st-ph svg{width:42px;height:42px;color:var(--sx-accent);opacity:.85}
.st-sold .st-media{filter:grayscale(.7);opacity:.6}
.st-card-body{padding:16px 18px 18px;display:flex;flex-direction:column;flex:1;
  gap:var(--sx-space-2)}
.st-card-head{display:flex;justify-content:space-between;gap:12px;align-items:baseline}
.st-card-head h3{font-family:var(--sx-font-heading);font-weight:var(--sx-h3-weight);
  font-size:1.06rem;margin:0;line-height:1.3}
.st-price{color:var(--sx-accent);font-weight:700;white-space:nowrap}
.st-badge{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;
  border-radius:999px;border:1px solid var(--sx-accent);color:var(--sx-accent);
  font-size:.7rem;font-weight:700;letter-spacing:.05em;text-transform:uppercase;
  align-self:flex-start}
.st-badge svg{width:11px;height:11px}
.st-desc{color:var(--sx-muted);font-size:.9rem;margin:0;display:-webkit-box;
  -webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.st-card-foot{margin-top:auto;padding-top:12px;display:flex;
  justify-content:space-between;align-items:center;gap:10px}
.st-out{color:var(--sx-muted);font-size:.85rem;font-weight:700}
.st-low{color:var(--sx-accent);font-size:.8rem;font-weight:700}
.st-add{margin-left:auto;padding:10px 20px;min-height:44px;
  border-radius:var(--sx-radius-button);border:1.5px solid var(--sx-accent);
  background:transparent;color:var(--sx-accent);font-weight:700;font-size:.87rem;
  cursor:pointer;transition:background .25s,color .25s}
.st-add:hover{background:var(--sx-accent);color:var(--sx-on-accent)}

.st-foot{margin-top:36px;color:var(--sx-muted);font-size:.8rem;display:flex;
  justify-content:space-between;flex-wrap:wrap;gap:10px}
.st-foot a{color:var(--sx-muted)}

/* ── Cart: floating button + slide-in panel ── */
.st-fab{position:fixed;right:18px;bottom:18px;z-index:60;display:none;
  align-items:center;gap:10px;padding:14px 20px;min-height:52px;border:none;
  border-radius:999px;background:var(--sx-accent);color:var(--sx-on-accent);
  font-weight:800;font-size:.95rem;cursor:pointer;
  box-shadow:0 12px 30px -10px color-mix(in srgb,var(--sx-accent) 60%,#000)}
.st-fab.on{display:inline-flex}
.st-fab svg{width:19px;height:19px}
.st-scrim{position:fixed;inset:0;background:rgba(8,8,10,.45);z-index:70;
  opacity:0;pointer-events:none;transition:opacity .3s}
.st-scrim.on{opacity:1;pointer-events:auto}
.st-panel{position:fixed;z-index:80;background:var(--sx-surface);
  border-left:1px solid var(--sx-border);display:flex;flex-direction:column;
  top:0;bottom:0;right:0;width:min(420px,100vw);
  transform:translateX(102%);transition:transform .38s var(--sx-ease)}
.st-panel.on{transform:none}
@media (max-width:560px){
  .st-panel{top:auto;left:0;right:0;bottom:0;width:auto;max-height:82vh;
    border-left:none;border-top:1px solid var(--sx-border);
    border-radius:calc(var(--sx-radius-card)) calc(var(--sx-radius-card)) 0 0;
    transform:translateY(102%)}
  .st-panel.on{transform:none}
}
.st-panel-head{display:flex;align-items:center;justify-content:space-between;
  padding:18px 20px;border-bottom:1px solid var(--sx-border)}
.st-panel-head h2{font-family:var(--sx-font-heading);font-size:1.15rem;margin:0}
.st-x{background:none;border:none;color:var(--sx-muted);cursor:pointer;
  width:44px;height:44px;display:inline-flex;align-items:center;
  justify-content:center;border-radius:50%}
.st-x:hover{color:var(--sx-text);background:var(--sx-surface-2)}
.st-x svg{width:18px;height:18px}
.st-lines{flex:1;overflow-y:auto;padding:8px 20px}
.st-line{display:flex;align-items:center;gap:12px;padding:14px 0;
  border-bottom:1px solid var(--sx-border)}
.st-line:last-child{border-bottom:none}
.st-line-info{flex:1;min-width:0}
.st-line-name{font-weight:600;font-size:.92rem;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.st-line-price{color:var(--sx-muted);font-size:.82rem;margin-top:2px}
.st-qty{display:flex;align-items:center;gap:2px;flex:none}
.st-qty button{width:44px;height:44px;border:1px solid var(--sx-border);
  background:transparent;color:var(--sx-text);font-size:1.05rem;cursor:pointer;
  border-radius:10px;line-height:1}
.st-qty button:hover{border-color:var(--sx-accent);color:var(--sx-accent)}
.st-qty span{min-width:28px;text-align:center;font-weight:700;font-size:.95rem}
.st-empty{color:var(--sx-muted);text-align:center;padding:38px 8px;font-size:.92rem}
.st-panel-foot{border-top:1px solid var(--sx-border);
  padding:16px 20px calc(16px + env(safe-area-inset-bottom,0px))}
.st-panel-row{display:flex;justify-content:space-between;align-items:baseline;
  margin-bottom:6px}
.st-panel-row .lbl{color:var(--sx-muted);font-size:.9rem}
.st-panel-total{font-weight:800;color:var(--sx-accent);font-size:1.15rem}
.st-notes{color:var(--sx-muted);font-size:.76rem;margin:0 0 12px}
.st-go{width:100%;padding:15px 26px;min-height:52px;
  border-radius:var(--sx-radius-button);border:none;background:var(--sx-accent);
  color:var(--sx-on-accent);font-weight:800;font-size:1rem;cursor:pointer}
.st-go:hover{background:var(--sx-accent-strong)}
.st-go:disabled{opacity:.65;cursor:default}
.st-clear{display:block;margin:10px auto 0;background:none;border:none;
  color:var(--sx-muted);font-size:.8rem;cursor:pointer;text-decoration:underline;
  min-height:44px;padding:0 12px}
.st-err{position:fixed;left:50%;transform:translateX(-50%);bottom:88px;
  background:#7f1d1d;color:#fff;padding:10px 18px;border-radius:10px;
  font-size:.85rem;display:none;z-index:90;max-width:min(92vw,480px);
  text-align:center}
@media (prefers-reduced-motion:reduce){
  .st-card,.st-img,.st-panel,.st-scrim{transition:none}
}
@LANGCSS@
</style>
</head>
<body class="@LANGCLASS@">
<!-- design source: @SOURCE@ -->
<header class="st-head">
  <div class="st-head-inner">
    @LOGO@
    <div class="st-id">
      <p class="st-eyebrow">@STORENOUN@</p>
      <h1>@TITLE@</h1>
      @TAGLINE@
    </div>
    @SITELINK@
  </div>
</header>
<main class="st-wrap">
  @SECTIONS@
  <footer class="st-foot"><span>&copy; @TITLE@</span>
    <a href="https://mysolutionist.app/" target="_blank" rel="noopener">Powered by Solutionist</a></footer>
</main>
<button class="st-fab" id="fab" aria-haspopup="dialog" aria-controls="panel">
  @CARTSVG@<span id="fab-label"></span></button>
<div class="st-scrim" id="scrim"></div>
<aside class="st-panel" id="panel" role="dialog" aria-modal="true" aria-label="Your cart">
  <div class="st-panel-head"><h2>Your cart</h2>
    <button class="st-x" id="close" aria-label="Close cart">@CLOSESVG@</button></div>
  <div class="st-lines" id="lines"></div>
  <div class="st-panel-foot">
    <div class="st-panel-row"><span class="lbl">Subtotal</span>
      <span class="st-panel-total" id="total"></span></div>
    @NOTES@
    <button class="st-go" id="go">Checkout</button>
    <button class="st-clear" id="clear">Clear cart</button>
  </div>
</aside>
<div class="st-err" id="err" role="alert"></div>
<script>
(function() {
  var SLUG = @SLUG@;
  var KEY = 'sx-cart-' + SLUG;
  var cart = {};
  try { cart = JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch (e) {}
  var meta = {};
  document.querySelectorAll('.st-add').forEach(function(b) {
    meta[b.dataset.id] = { name: b.dataset.name, price: parseFloat(b.dataset.price) };
    b.addEventListener('click', function() {
      cart[b.dataset.id] = (cart[b.dataset.id] || 0) + 1;
      save(); render();
      b.textContent = 'Added \\u2713';
      setTimeout(function() { b.textContent = 'Add to cart'; }, 900);
    });
  });
  Object.keys(cart).forEach(function(id) { if (!meta[id]) delete cart[id]; });
  function save() { try { localStorage.setItem(KEY, JSON.stringify(cart)); } catch (e) {} }

  var fab = document.getElementById('fab');
  var scrim = document.getElementById('scrim');
  var panel = document.getElementById('panel');
  function openPanel() { panel.classList.add('on'); scrim.classList.add('on'); }
  function closePanel() { panel.classList.remove('on'); scrim.classList.remove('on'); }
  fab.addEventListener('click', openPanel);
  scrim.addEventListener('click', closePanel);
  document.getElementById('close').addEventListener('click', closePanel);
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') closePanel();
  });

  function qtyBtn(label, aria, fn) {
    var b = document.createElement('button');
    b.textContent = label; b.setAttribute('aria-label', aria);
    b.addEventListener('click', fn);
    return b;
  }
  function render() {
    var n = 0, t = 0;
    var lines = document.getElementById('lines');
    lines.textContent = '';
    Object.keys(cart).forEach(function(id) {
      var q = cart[id], m = meta[id];
      n += q; t += q * m.price;
      var row = document.createElement('div'); row.className = 'st-line';
      var info = document.createElement('div'); info.className = 'st-line-info';
      var nm = document.createElement('div'); nm.className = 'st-line-name';
      nm.textContent = m.name;
      var pr = document.createElement('div'); pr.className = 'st-line-price';
      pr.textContent = '$' + m.price.toFixed(2) + ' \\u00d7 ' + q +
        ' \\u2014 $' + (m.price * q).toFixed(2);
      info.appendChild(nm); info.appendChild(pr);
      var qty = document.createElement('div'); qty.className = 'st-qty';
      qty.appendChild(qtyBtn('\\u2212', 'Remove one ' + m.name, function() {
        cart[id] -= 1;
        if (cart[id] <= 0) delete cart[id];
        save(); render();
      }));
      var count = document.createElement('span'); count.textContent = q;
      qty.appendChild(count);
      qty.appendChild(qtyBtn('+', 'Add one ' + m.name, function() {
        cart[id] += 1; save(); render();
      }));
      row.appendChild(info); row.appendChild(qty);
      lines.appendChild(row);
    });
    if (n === 0) {
      var empty = document.createElement('p'); empty.className = 'st-empty';
      empty.textContent = 'Your cart is empty.';
      lines.appendChild(empty);
      closePanel();
    }
    fab.classList.toggle('on', n > 0);
    document.getElementById('fab-label').textContent =
      n + (n === 1 ? ' item' : ' items') + ' \\u00b7 $' + t.toFixed(2);
    document.getElementById('total').textContent = '$' + t.toFixed(2);
    document.getElementById('go').disabled = n === 0;
  }
  document.getElementById('clear').addEventListener('click', function() {
    cart = {}; save(); render();
  });
  function fail(msg) {
    var el = document.getElementById('err');
    el.textContent = msg; el.style.display = 'block';
    setTimeout(function() { el.style.display = 'none'; }, 5000);
  }
  document.getElementById('go').addEventListener('click', function() {
    var items = Object.keys(cart).map(function(id) { return { offering_id: id, quantity: cart[id] }; });
    if (!items.length) return;
    var go = document.getElementById('go');
    go.disabled = true; go.textContent = 'One moment\\u2026';
    fetch('/payments/store-checkout', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slug: SLUG, items: items })
    }).then(function(r) { return r.json().then(function(j) { return { ok: r.ok, j: j }; }); })
      .then(function(res) {
        if (res.ok && res.j && res.j.checkout_url) {
          cart = {}; save();
          window.location = res.j.checkout_url;
        } else {
          var d = res.j && res.j.detail;
          fail(typeof d === 'string' ? d : 'Checkout failed \\u2014 please try again.');
          go.disabled = false; go.textContent = 'Checkout';
        }
      }).catch(function() {
        fail('Network error \\u2014 please try again.');
        go.disabled = false; go.textContent = 'Checkout';
      });
  });
  render();
})();
</script>
</body>
</html>"""


_CATEGORY_ORDER = ("product", "course", "package")


def _card(o: Dict[str, Any]) -> str:
    category = str(o.get("category") or "product")
    if str(o.get("image_url") or "").startswith("http"):
        media = f'<img class="st-img" src="{_esc(o.get("image_url"))}" alt="" loading="lazy">'
    else:
        glyph = _CATEGORY_GLYPHS.get(category, _GLYPH_PRODUCT)
        media = f'<div class="st-ph">{glyph}</div>'
    price = float(o.get("current_price") or 0)
    if not o.get("in_stock"):
        stock = '<span class="st-out">Sold out</span>'
    elif o.get("units_left"):
        stock = f'<span class="st-low">Only {int(o["units_left"])} left</span>'
    else:
        stock = ""
    btn = (f'<button class="st-add" data-id="{_esc(o["id"])}" '
           f'data-name="{_esc(o["name"])}" data-price="{price:.2f}">Add to cart</button>'
           if o.get("in_stock") else "")
    desc = _esc(o.get("description") or "")
    desc_html = f'<p class="st-desc">{desc}</p>' if desc else ""
    badge = _DL_BADGE if o.get("instant_download") else ""
    sold = "" if o.get("in_stock") else " st-sold"
    return (f'<article class="st-card{sold}">'
            f'<div class="st-media">{media}</div>'
            f'<div class="st-card-body">'
            f'<div class="st-card-head"><h3>{_esc(o["name"])}</h3>'
            f'<span class="st-price">${price:,.2f}</span></div>'
            f'{badge}{desc_html}'
            f'<div class="st-card-foot">{stock}{btn}</div></div></article>')


def _sections(items: List[Dict[str, Any]], business_type: Optional[str]) -> str:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for o in items:
        groups.setdefault(str(o.get("category") or "product"), []).append(o)
    ordered = [c for c in _CATEGORY_ORDER if c in groups] + \
              [c for c in groups if c not in _CATEGORY_ORDER]
    if not ordered:
        return ('<section class="st-sec"><p class="st-empty">'
                'Nothing here yet — check back soon.</p></section>')
    out = []
    show_headings = len(ordered) > 1
    for cat in ordered:
        cards = "".join(_card(o) for o in groups[cat])
        head = ""
        if show_headings:
            n = len(groups[cat])
            head = (f'<div class="st-sec-head">'
                    f'<h2 class="st-sec-title">'
                    f'{_esc(store_design.category_heading(cat, business_type))}</h2>'
                    f'<span class="st-sec-count">{n}</span></div>')
        out.append(f'<section class="st-sec">{head}'
                   f'<div class="st-grid">{cards}</div></section>')
    return "".join(out)


def render_store_page(slug: str, biz: Dict[str, Any],
                      items: List[Dict[str, Any]], ss: Dict[str, Any],
                      site: Optional[Dict[str, Any]] = None) -> str:
    ctx = store_design.resolve(site, biz)
    dna = ctx["dna"]
    business_type = biz.get("type")
    noun = store_design.store_noun(business_type)

    kit = ((biz.get("settings") or {}).get("brand_kit")) or {}
    logo_url = str(kit.get("logo_url") or kit.get("logo") or "").strip()
    logo = (f'<img class="st-logo" src="{_esc(logo_url)}" alt="">'
            if logo_url.startswith("http") else "")
    tagline = (f'<p class="st-tag">{_esc(ctx["tagline"])}</p>'
               if ctx.get("tagline") else "")
    site_link = ""
    if ctx.get("site_url"):
        site_link = (f'<a class="st-site-link" href="{_esc(ctx["site_url"])}">'
                     f'Visit site{_ARROW_SVG}</a>')

    notes = []
    if ss.get("tax_rate_pct"):
        notes.append(f"Sales tax ({ss['tax_rate_pct']:g}%) added at checkout.")
    if ss.get("flat_shipping_cents"):
        notes.append(f"Flat shipping ${ss['flat_shipping_cents'] / 100:,.2f} on physical items.")
    notes_html = (f'<p class="st-notes">{_esc(" ".join(notes))}</p>'
                  if notes else "")

    lang = ctx.get("language_key")
    return (_PAGE
            .replace("@CSSVARS@", brand_dna.css_variables(dna))
            .replace("@FONTS@", brand_dna.google_fonts_url(dna))
            .replace("@LANGCSS@", _LANGUAGE_CSS.get(lang or "", ""))
            .replace("@LANGCLASS@", f"st-lang-{lang}" if lang else "")
            .replace("@SOURCE@", _esc(ctx.get("source") or ""))
            .replace("@STORENOUN@", _esc(noun))
            .replace("@TITLE@", _esc(biz.get("name") or "Store"))
            .replace("@LOGO@", logo)
            .replace("@TAGLINE@", tagline)
            .replace("@SITELINK@", site_link)
            .replace("@SECTIONS@", _sections(items, business_type))
            .replace("@NOTES@", notes_html)
            .replace("@CARTSVG@", _CART_SVG)
            .replace("@CLOSESVG@", _CLOSE_SVG)
            .replace("@SLUG@", _js_str(slug)))


# ─── Thank-you page ───────────────────────────────────────────────────

_THANKS = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Order confirmed — @TITLE@</title>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="@FONTS@" rel="stylesheet">
<style>
@CSSVARS@
*,*::before,*::after{box-sizing:border-box}
body{margin:0;background:var(--sx-bg);color:var(--sx-text);
  font-family:var(--sx-font-body);line-height:1.6;display:flex;
  align-items:center;justify-content:center;min-height:100vh;padding:24px}
.card{max-width:460px;width:100%;text-align:center;background:var(--sx-surface);
  border:1px solid var(--sx-border);border-radius:var(--sx-radius-card);
  padding:clamp(28px,6vw,44px) clamp(20px,5vw,36px)}
h1{font-family:var(--sx-font-heading);font-weight:var(--sx-heading-weight);
  letter-spacing:var(--sx-letter-tight);font-size:1.75rem;margin:0 0 12px}
p{color:var(--sx-muted)}
.ref{color:var(--sx-accent);font-weight:700}
a{color:var(--sx-accent)}
.dl{display:block;margin:10px auto 0;max-width:320px;padding:13px 22px;
  min-height:48px;border-radius:var(--sx-radius-button);background:var(--sx-accent);
  color:var(--sx-on-accent);font-weight:800;text-decoration:none;font-size:.95rem}
.dl:hover{background:var(--sx-accent-strong)}
.dl-wrap{margin:20px 0 8px}
.finalizing{margin:20px 0 8px;padding:14px 18px;border:1px solid var(--sx-accent);
  border-radius:12px;font-size:.9rem;color:var(--sx-text)}
.spin{display:inline-block;width:12px;height:12px;border:2px solid var(--sx-accent);
border-top-color:transparent;border-radius:50%;vertical-align:-2px;
margin-right:8px;animation:sp 1s linear infinite}
@keyframes sp{to{transform:rotate(360deg)}}
.small{font-size:.75rem;opacity:.75}</style></head>
<body><div class="card">
<h1>Order confirmed \U0001F389</h1>
<p>Thank you@REF@! A receipt is on its way to your email.</p>
@DIGITAL@
<p><a href="/public/store/@SLUG@/page">Back to @NOUN@</a></p>
<p class="small">Powered by Solutionist</p>
</div>@REFRESH@</body></html>"""

# Webhook race — the buyer can land here before Stripe's webhook flips
# the order to paid. Reload gently (5s, capped by ?r= so a stuck order
# never reloads forever); the email link is the durable fallback.
_REFRESH_JS = """<script>
(function(){
  var p = new URLSearchParams(location.search);
  var n = parseInt(p.get('r') || '0', 10) || 0;
  if (n >= 24) return;
  setTimeout(function(){
    p.set('r', String(n + 1));
    location.replace(location.pathname + '?' + p.toString());
  }, 5000);
})();
</script>"""


def render_thank_you(slug: str, biz: Dict[str, Any], order_id: str = "",
                     downloads: Optional[List[Dict[str, Any]]] = None,
                     digital_pending: bool = False,
                     site: Optional[Dict[str, Any]] = None) -> str:
    try:
        ctx = store_design.resolve(site, biz)
        dna = ctx["dna"]
    except Exception:
        dna = brand_dna.build_brand_dna(str(biz.get("id") or "x"), {
            "design": {}, "voice": {}, "business": {"settings": {}}})
    ref = (f' — order <span class="ref">#{_esc(order_id[:8].upper())}</span>'
           if order_id else "")
    digital = ""
    refresh = ""
    if downloads:
        links = "".join(
            f'<a class="dl" href="{_esc(d.get("url"))}">'
            f'Download {_esc(d.get("name"))}</a>' for d in downloads)
        digital = (f'<div class="dl-wrap"><p style="margin:0 0 4px">'
                   f'Your files are ready:</p>{links}'
                   f'<p class="small" style="margin-top:10px">'
                   f'These links are also in your receipt email.</p></div>')
    elif digital_pending:
        digital = ('<div class="finalizing"><span class="spin"></span>'
                   'Finalizing your order — your download link is on its '
                   'way to your email. This page will refresh in a moment.'
                   '</div>')
        refresh = _REFRESH_JS
    noun = store_design.store_noun(biz.get("type"))
    back = "the store" if noun == "Store" else noun.lower()
    return (_THANKS
            .replace("@CSSVARS@", brand_dna.css_variables(dna))
            .replace("@FONTS@", brand_dna.google_fonts_url(dna))
            .replace("@TITLE@", _esc(biz.get("name") or ""))
            .replace("@NOUN@", _esc(back))
            .replace("@REF@", ref)
            .replace("@DIGITAL@", digital)
            .replace("@REFRESH@", refresh)
            .replace("@SLUG@", _esc(slug)))
