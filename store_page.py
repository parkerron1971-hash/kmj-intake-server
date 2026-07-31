"""
store_page.py — Arc 27 PR2 — hosted storefront HTML renderer.

Deterministic, platform-authored page: brand DNA tokens + product grid +
a self-contained vanilla-JS cart (localStorage, keyed by slug). The cart
sends ONLY {offering_id, quantity} to /payments/store-checkout — all
pricing is recomputed server-side. Same trust model as the motion-module
injections: this JS is ours, never LLM-written.

Template uses @TOKEN@ replacement (not f-strings) so CSS/JS braces stay
literal — the heredoc/brace-escaping trap this file exists to avoid.
"""
from __future__ import annotations

import html as _html
import json as _json
from typing import Any, Dict, List, Optional

import brand_dna


def _esc(v: Any) -> str:
    return _html.escape(str(v or ""))


# Digital delivery — shown on items with a hosted file attached. Inline
# SVG download glyph (this page ships no icon font; emoji is against the
# icon language).
_DL_BADGE = (
    '<span class="st-badge"><svg viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2.5" stroke-linecap="round" '
    'stroke-linejoin="round" aria-hidden="true">'
    '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
    '<polyline points="7 10 12 15 17 10"/>'
    '<line x1="12" y1="15" x2="12" y2="3"/></svg>Instant download</span>')


_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>@TITLE@ — Store</title>
<link href="@FONTS@" rel="stylesheet">
<style>
@CSSVARS@
*,*::before,*::after{box-sizing:border-box}
body{margin:0;background:var(--sx-bg);color:var(--sx-text);font-family:var(--sx-font-body);line-height:1.6}
.st-wrap{max-width:1100px;margin:0 auto;padding:clamp(28px,5vw,56px) clamp(18px,4vw,40px) 140px}
h1{font-family:var(--sx-font-heading);font-weight:var(--sx-heading-weight);font-size:clamp(2rem,5vw,3.2rem);margin:0 0 6px}
.st-sub{color:var(--sx-muted);margin:0 0 34px;font-size:.95rem}
.st-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:20px}
.st-card{background:var(--sx-surface);border:1px solid var(--sx-border);border-radius:var(--sx-radius-card);overflow:hidden;display:flex;flex-direction:column}
.st-img{width:100%;aspect-ratio:4/3;object-fit:cover;display:block}
.st-img-ph{background:linear-gradient(135deg,var(--sx-accent-soft),var(--sx-surface-2))}
.st-card-body{padding:18px;display:flex;flex-direction:column;flex:1}
.st-card-head{display:flex;justify-content:space-between;gap:10px;align-items:baseline}
.st-card-head h3{font-family:var(--sx-font-heading);font-size:1.08rem;margin:0}
.st-price{color:var(--sx-accent);font-weight:700;white-space:nowrap}
.st-badge{display:inline-flex;align-items:center;gap:6px;margin-top:8px;padding:3px 10px;border-radius:999px;border:1px solid var(--sx-accent);color:var(--sx-accent);font-size:.72rem;font-weight:700;letter-spacing:.04em;text-transform:uppercase;align-self:flex-start}
.st-badge svg{width:12px;height:12px}
.st-desc{color:var(--sx-muted);font-size:.9rem;margin:8px 0 0}
.st-card-foot{margin-top:auto;padding-top:14px;display:flex;justify-content:flex-end;align-items:center;gap:10px}
.st-out{color:var(--sx-muted);font-size:.85rem;font-weight:700}
.st-low{color:var(--sx-accent);font-size:.8rem;font-weight:700}
.st-add{padding:9px 18px;border-radius:var(--sx-radius-button);border:1.5px solid var(--sx-accent);background:transparent;color:var(--sx-accent);font-weight:700;font-size:.85rem;cursor:pointer}
.st-add:hover{background:var(--sx-accent);color:var(--sx-on-accent)}
.st-bar{position:fixed;left:0;right:0;bottom:0;background:var(--sx-surface);border-top:1px solid var(--sx-border);padding:14px clamp(18px,4vw,40px);display:none;align-items:center;gap:16px;z-index:50}
.st-bar.on{display:flex}
.st-bar-count{flex:1;font-size:.95rem}
.st-bar-total{font-weight:800;color:var(--sx-accent);font-size:1.05rem}
.st-go{padding:12px 26px;border-radius:var(--sx-radius-button);border:none;background:var(--sx-accent);color:var(--sx-on-accent);font-weight:800;font-size:.95rem;cursor:pointer}
.st-clear{background:none;border:none;color:var(--sx-muted);font-size:.8rem;cursor:pointer;text-decoration:underline}
.st-err{position:fixed;left:50%;transform:translateX(-50%);bottom:84px;background:#7f1d1d;color:#fff;padding:10px 18px;border-radius:10px;font-size:.85rem;display:none;z-index:60}
.st-foot{margin-top:48px;color:var(--sx-muted);font-size:.8rem;display:flex;justify-content:space-between;flex-wrap:wrap;gap:10px}
.st-foot a{color:var(--sx-muted)}
</style>
</head>
<body>
<div class="st-wrap">
  <h1>@TITLE@</h1>
  <p class="st-sub">@NOTES@</p>
  <div class="st-grid">@CARDS@</div>
  <div class="st-foot"><span>&copy; @TITLE@</span>
    <a href="https://mysolutionist.app/" target="_blank" rel="noopener">Powered by Solutionist</a></div>
</div>
<div class="st-bar" id="bar">
  <span class="st-bar-count" id="count"></span>
  <button class="st-clear" id="clear">Clear</button>
  <span class="st-bar-total" id="total"></span>
  <button class="st-go" id="go">Checkout</button>
</div>
<div class="st-err" id="err"></div>
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
  function render() {
    var n = 0, t = 0;
    Object.keys(cart).forEach(function(id) { n += cart[id]; t += cart[id] * meta[id].price; });
    var bar = document.getElementById('bar');
    if (n > 0) { bar.classList.add('on'); } else { bar.classList.remove('on'); }
    document.getElementById('count').textContent = n + (n === 1 ? ' item' : ' items');
    document.getElementById('total').textContent = '$' + t.toFixed(2);
  }
  document.getElementById('clear').addEventListener('click', function() { cart = {}; save(); render(); });
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
          fail(typeof d === 'string' ? d : 'Checkout failed — please try again.');
          go.disabled = false; go.textContent = 'Checkout';
        }
      }).catch(function() {
        fail('Network error — please try again.');
        go.disabled = false; go.textContent = 'Checkout';
      });
  });
  render();
})();
</script>
</body>
</html>"""

_THANKS = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Order confirmed — @TITLE@</title>
<style>body{margin:0;background:@BG@;color:@TEXT@;font-family:system-ui,sans-serif;
display:flex;align-items:center;justify-content:center;min-height:100vh;text-align:center;padding:24px}
.card{max-width:420px} h1{font-size:1.8rem;margin:0 0 12px}
p{opacity:.85;line-height:1.6} .ref{color:@ACCENT@;font-weight:700}
a{color:@ACCENT@}
.dl{display:block;margin:10px auto 0;max-width:320px;padding:12px 22px;
border-radius:10px;background:@ACCENT@;color:@BG@;font-weight:800;
text-decoration:none;font-size:.95rem}
.dl-wrap{margin:20px 0 8px}
.finalizing{margin:20px 0 8px;padding:14px 18px;border:1px solid @ACCENT@;
border-radius:10px;font-size:.9rem;opacity:.9}
.spin{display:inline-block;width:12px;height:12px;border:2px solid @ACCENT@;
border-top-color:transparent;border-radius:50%;vertical-align:-2px;
margin-right:8px;animation:sp 1s linear infinite}
@keyframes sp{to{transform:rotate(360deg)}}</style></head>
<body><div class="card">
<h1>Order confirmed \U0001F389</h1>
<p>Thank you@REF@! A receipt is on its way to your email.</p>
@DIGITAL@
<p><a href="/public/store/@SLUG@/page">Back to the store</a></p>
<p style="font-size:.75rem;opacity:.6">Powered by Solutionist</p>
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


def _dna_from_biz(biz: Dict[str, Any]) -> Dict[str, Any]:
    """Derive DNA from the business row's brand_kit directly — we already
    hold the row, so no extra bundle fetch (and it works offline/in tests)."""
    kit = ((biz.get("settings") or {}).get("brand_kit")) or {}
    bundle_lite = {
        "design": {k: kit.get(k) for k in (
            "primary_color", "secondary_color", "accent_color",
            "background_color", "text_color", "font_heading", "font_body")},
        "voice": {"tone_words": kit.get("tone_words") or []},
        "business": {"settings": biz.get("settings") or {}},
    }
    return brand_dna.build_brand_dna(str(biz.get("id") or "x"), bundle_lite)


def render_store_page(slug: str, biz: Dict[str, Any],
                      items: List[Dict[str, Any]], ss: Dict[str, Any]) -> str:
    dna = _dna_from_biz(biz)
    cards = []
    for o in items:
        img = (f'<img class="st-img" src="{_esc(o.get("image_url"))}" alt="">'
               if str(o.get("image_url") or "").startswith("http")
               else '<div class="st-img st-img-ph"></div>')
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
        badge = (_DL_BADGE if o.get("instant_download") else "")
        cards.append(
            f'<div class="st-card">{img}<div class="st-card-body">'
            f'<div class="st-card-head"><h3>{_esc(o["name"])}</h3>'
            f'<span class="st-price">${price:,.2f}</span></div>'
            f'{badge}{desc_html}'
            f'<div class="st-card-foot">{stock}{btn}</div></div></div>')

    notes = []
    if ss.get("tax_rate_pct"):
        notes.append(f"Sales tax ({ss['tax_rate_pct']:g}%) added at checkout.")
    if ss.get("flat_shipping_cents"):
        notes.append(f"Flat shipping ${ss['flat_shipping_cents'] / 100:,.2f} on physical items.")

    return (_PAGE
            .replace("@CSSVARS@", brand_dna.css_variables(dna))
            .replace("@FONTS@", brand_dna.google_fonts_url(dna))
            .replace("@TITLE@", _esc(biz.get("name") or "Store"))
            .replace("@NOTES@", " ".join(notes))
            .replace("@CARDS@", "".join(cards))
            .replace("@SLUG@", _json.dumps(slug)))


def render_thank_you(slug: str, biz: Dict[str, Any], order_id: str = "",
                     downloads: Optional[List[Dict[str, Any]]] = None,
                     digital_pending: bool = False) -> str:
    try:
        palette = _dna_from_biz(biz)["palette"]
    except Exception:
        palette = {"bg": "#0a0a0a", "text": "#f4f4f4", "accent": "#c9a84c"}
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
                   f'<p style="font-size:.8rem;opacity:.7;margin-top:10px">'
                   f'These links are also in your receipt email.</p></div>')
    elif digital_pending:
        digital = ('<div class="finalizing"><span class="spin"></span>'
                   'Finalizing your order — your download link is on its '
                   'way to your email. This page will refresh in a moment.'
                   '</div>')
        refresh = _REFRESH_JS
    return (_THANKS
            .replace("@TITLE@", _esc(biz.get("name") or ""))
            .replace("@BG@", palette["bg"])
            .replace("@TEXT@", palette["text"])
            .replace("@ACCENT@", palette["accent"])
            .replace("@REF@", ref)
            .replace("@DIGITAL@", digital)
            .replace("@REFRESH@", refresh)
            .replace("@SLUG@", _esc(slug)))
