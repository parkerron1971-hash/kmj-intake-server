"""The founding-seat flyer: one designed popup on the public site.

Kevin, 2026-09-06: "some type of ad when someone goes to the website —
the founders seats, a designed flyer that is shown, the deal, like a
popup ad."

What it is: a single dialog that rises once per visitor on the reading
pages of mysolutionist.app (home, about, features, compare, faq,
download, the news index and every post) with the founding-seat deal on it — Professional at the
founding price, locked for the life of the seat, with the LIVE seat
count the pricing strip already reads. One button takes the seat
(`/start?plan=founder`); everything else closes it.

What keeps it from being the popup everyone hates:
  - it waits: five seconds of reading, or the first real scroll —
    never on arrival, never on top of the film or the mobile menu;
  - it remembers: dismissed or clicked, it stays away for two weeks
    (localStorage; a browser that refuses storage sees it once a page
    load and nothing breaks);
  - it is gone when the deal is gone: zero seats left, or no founder
    price configured, or the seat count unreadable — no dialog at all,
    the page is exactly what it was;
  - it stays off the pages where it would be in the way: /start, the
    legal pages, the contact form.

`?ad=founder` on any carrying page shows it at once, storage or not —
so Kevin can look at it, and so a shared link can lead with it.

The numbers all come from the same dials the strip uses
(`pricing_config`, `stripe_billing`), so the flyer and the strip can
never disagree.
"""
from __future__ import annotations

# The pages that carry the flyer. Everything else in the shell — the
# start flow, legal, the contact form — is left alone. The news came in
# on Kevin's ask (2026-09-06, same day): the index and every post, which
# live at /news/{slug} and so match by prefix.
FOUNDER_AD_PATHS = frozenset({"/", "/about", "/features", "/compare", "/faq", "/download", "/news"})
FOUNDER_AD_PREFIXES = ("/news/",)


def carries_the_flyer(path: str) -> bool:
    return path in FOUNDER_AD_PATHS or path.startswith(FOUNDER_AD_PREFIXES)

STORAGE_KEY = "sol_founder_ad"
QUIET_DAYS = 14
SHOW_AFTER_MS = 5000     # the timer
MIN_DWELL_MS = 2500      # a scroll before this still waits this long
FORCE_PARAM = "ad=founder"


def _numbers() -> dict | None:
    """The live shape of the offer, or None when there is no offer to
    show. Reads through marketing_pages so the five-minute seat cache is
    shared with the strip (one query serves both)."""
    import marketing_pages
    import pricing_config
    import stripe_billing
    try:
        if not stripe_billing._founder_price_ids():
            return None
        limit = stripe_billing._founder_seat_limit()
        taken = marketing_pages._founder_seats_taken_sync()
        left = max(0, limit - taken)
        if left <= 0:
            return None
        prices = pricing_config.tier_price_cents()
        return {
            "limit": limit,
            "left": left,
            "pct": 0 if limit <= 0 else min(100, int(round(100 * taken / limit))),
            "price": prices.get("founder", 0) // 100,
            "list_price": prices.get("professional", 0) // 100,
            "credits": pricing_config.founder_credits(),
        }
    except Exception:
        return None


def founder_ad_html() -> str:
    """The dialog markup, hidden until the script decides. Empty string
    when there is nothing to offer."""
    n = _numbers()
    if not n:
        return ""
    saving = max(0, n["list_price"] - n["price"])
    return f"""
<!-- The founding-seat flyer. Hidden until the script opens it; absent
     entirely when the seats are gone. See marketing_founder_ad.py. -->
<div class="fad" id="founderAd" role="dialog" aria-modal="true"
     aria-labelledby="founderAdTitle" data-left="{n['left']}" hidden>
  <div class="fad-scrim" data-fad-close></div>
  <div class="fad-card" id="founderAdCard" tabindex="-1">
    <button type="button" class="fad-x" id="founderAdClose" aria-label="Close" data-fad-close>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
    </button>

    <div class="fad-art" aria-hidden="true">
      <div class="fad-glow"></div>
      <div class="fad-ring">
        <svg viewBox="0 0 120 120" class="fad-ring-svg"><circle cx="60" cy="60" r="56" fill="none" stroke="currentColor" stroke-width="1.2" stroke-dasharray="2 5"/><circle cx="60" cy="60" r="47" fill="none" stroke="currentColor" stroke-width="1"/></svg>
        <span class="fad-ring-n">{n['limit']}</span>
        <span class="fad-ring-l">seats<br>only</span>
      </div>
      <div class="fad-was">Professional is ${n['list_price']}</div>
      <div class="fad-figure"><span class="fad-dollar">$</span>{n['price']}<span class="fad-per">/mo</span></div>
      <div class="fad-locked">locked for as long as you keep it</div>
    </div>

    <div class="fad-body">
      <div class="fad-seal">Founding seat</div>
      <h2 id="founderAdTitle" class="fad-title">The first {n['limit']} run the whole system at the founding price. Forever.</h2>
      <ul class="fad-deal">
        <li><b>Everything in Professional</b>: every room, every automation, the Chief.</li>
        <li><b>{n['credits']:,} AI actions a month</b>, every month, in the seat.</li>
        <li><b>${saving} a month less than the list price</b>, and the price never rises while the seat is yours.</li>
      </ul>
      <div class="fad-meter" aria-hidden="true"><i style="width:{n['pct']}%"></i></div>
      <div class="fad-left"><b>{n['left']}</b> of {n['limit']} seats left<span class="fad-left-note"> &middot; after that, the list price is the price</span></div>
      <div class="fad-actions">
        <a class="fad-cta" id="founderAdCta" href="/start?plan=founder">Take a founding seat &rarr;</a>
        <button type="button" class="fad-later" data-fad-close>Not now</button>
      </div>
    </div>
  </div>
</div>"""


FOUNDER_AD_CSS = """
  /* ─── the founding-seat flyer ─── */
  .fad{position:fixed;inset:0;z-index:210;display:flex;align-items:center;justify-content:center;
    padding:24px;}
  .fad[hidden]{display:none;}
  .fad-scrim{position:absolute;inset:0;background:rgba(4,5,8,.78);
    -webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px);
    opacity:0;transition:opacity .28s ease;}
  .fad-card{position:relative;display:grid;grid-template-columns:300px 1fr;
    width:min(820px,100%);max-height:calc(100dvh - 48px);overflow:auto;
    border-radius:18px;border:1px solid color-mix(in srgb, #F3C56B 42%, var(--border-strong));
    background:var(--bg-2);box-shadow:0 60px 140px rgba(0,0,0,.75), 0 0 0 1px rgba(0,0,0,.4);
    opacity:0;transform:translateY(18px) scale(.985);
    transition:opacity .32s ease, transform .32s cubic-bezier(.2,.8,.2,1);outline:none;}
  .fad.is-in .fad-scrim{opacity:1;}
  .fad.is-in .fad-card{opacity:1;transform:none;}
  .fad-x{position:absolute;top:12px;right:12px;z-index:3;width:38px;height:38px;border-radius:50%;
    display:inline-flex;align-items:center;justify-content:center;cursor:pointer;
    color:var(--text-primary);background:rgba(10,12,16,.72);border:1px solid var(--border-strong);
    transition:background .16s, border-color .16s;}
  .fad-x svg{width:16px;height:16px;}
  .fad-x:hover{background:rgba(10,12,16,.92);border-color:color-mix(in srgb, #F3C56B 60%, transparent);}
  .fad-x:focus-visible,.fad-cta:focus-visible,.fad-later:focus-visible{outline:2px solid #F3C56B;outline-offset:2px;}

  /* the left panel: the price, on a dark gold-lit field */
  .fad-art{position:relative;overflow:hidden;display:flex;flex-direction:column;justify-content:center;
    padding:36px 28px;color:#F3C56B;
    background:linear-gradient(180deg, #14110A 0%, #0B0D12 100%);
    border-right:1px solid color-mix(in srgb, #F3C56B 22%, transparent);}
  .fad-glow{position:absolute;inset:-40% -30% auto -30%;height:120%;
    background:radial-gradient(closest-side, rgba(243,197,107,.28), rgba(243,197,107,0) 70%);
    pointer-events:none;}
  .fad-ring{position:relative;width:118px;height:118px;margin:0 0 22px;display:grid;place-items:center;}
  .fad-ring-svg{position:absolute;inset:0;width:100%;height:100%;color:#F3C56B;opacity:.9;}
  .fad-ring-n{position:relative;font-family:var(--font-heading);font-weight:700;font-size:40px;line-height:1;
    letter-spacing:-0.04em;color:var(--text-primary);margin-top:-14px;}
  .fad-ring-l{position:absolute;bottom:22px;font-family:var(--font-mono, monospace);font-size:9.5px;
    letter-spacing:.16em;text-transform:uppercase;line-height:1.2;text-align:center;}
  .fad-was{position:relative;font-family:var(--font-mono, monospace);font-size:11px;letter-spacing:.12em;
    text-transform:uppercase;color:var(--text-muted);text-decoration:line-through;
    text-decoration-color:#F3C56B;text-decoration-thickness:1.5px;}
  .fad-figure{position:relative;font-family:var(--font-heading);font-weight:700;font-size:74px;line-height:1;
    letter-spacing:-0.05em;color:var(--text-primary);margin:6px 0 4px;display:flex;align-items:flex-start;}
  .fad-dollar{font-size:30px;margin-top:8px;margin-right:2px;color:#F3C56B;}
  .fad-per{font-size:18px;letter-spacing:0;color:var(--text-muted);align-self:flex-end;margin:0 0 12px 4px;font-weight:600;}
  .fad-locked{position:relative;font-size:12.5px;color:#F3C56B;font-weight:600;letter-spacing:.01em;}

  /* the right panel: the deal */
  .fad-body{padding:38px 40px 34px 36px;display:flex;flex-direction:column;}
  .fad-seal{display:inline-flex;align-self:flex-start;align-items:center;gap:8px;padding:5px 12px;
    font-family:var(--font-mono, monospace);font-size:10px;letter-spacing:.16em;text-transform:uppercase;
    color:#F3C56B;border:1px solid color-mix(in srgb, #F3C56B 45%, transparent);
    background:color-mix(in srgb, #F3C56B 9%, transparent);border-radius:999px;margin-bottom:16px;}
  .fad-title{font-size:clamp(24px, 2.6vw, 30px);line-height:1.1;letter-spacing:-0.03em;margin:0 0 18px;
    color:var(--text-primary);}
  .fad-deal{list-style:none;margin:0 0 20px;padding:0;display:grid;gap:9px;}
  .fad-deal li{position:relative;padding-left:22px;font-size:14.5px;line-height:1.5;color:var(--text-secondary);}
  .fad-deal li::before{content:"";position:absolute;left:0;top:9px;width:10px;height:10px;border-radius:50%;
    background:#F3C56B;box-shadow:0 0 0 4px color-mix(in srgb, #F3C56B 18%, transparent);}
  .fad-deal b{color:var(--text-primary);font-weight:600;}
  .fad-meter{height:4px;background:rgba(255,255,255,.08);border-radius:2px;overflow:hidden;}
  .fad-meter i{display:block;height:100%;background:#F3C56B;}
  .fad-left{font-family:var(--font-mono, monospace);font-size:11px;color:var(--text-muted);margin:8px 0 22px;}
  .fad-left b{color:#F3C56B;font-weight:500;}
  .fad-actions{display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin-top:auto;}
  .fad-cta{display:inline-flex;align-items:center;gap:8px;padding:14px 24px;border-radius:10px;
    font:700 14px var(--font-body);color:#0B0D12;background:#F3C56B;
    box-shadow:0 8px 28px rgba(243,197,107,.28);transition:transform .15s, box-shadow .15s, background .15s;}
  .fad-cta:hover{transform:translateY(-2px);background:#F8D17E;box-shadow:0 12px 36px rgba(243,197,107,.4);}
  .fad-later{background:none;border:none;cursor:pointer;font:500 13px var(--font-body);
    color:var(--text-muted);padding:8px 4px;}
  .fad-later:hover{color:var(--text-primary);}

  @media (max-width:720px){
    .fad{padding:0;align-items:flex-end;}
    .fad-card{grid-template-columns:1fr;width:100%;max-height:calc(100dvh - 24px);
      border-radius:22px 22px 0 0;border-bottom:none;transform:translateY(40px);}
    .fad-art{display:grid;grid-template-columns:92px 1fr;column-gap:18px;align-items:center;
      padding:24px 22px 20px;
      border-right:none;border-bottom:1px solid color-mix(in srgb, #F3C56B 22%, transparent);}
    .fad-ring{width:92px;height:92px;margin:0;grid-row:1 / span 3;}
    .fad-ring-n{font-size:30px;margin-top:-10px;}
    .fad-ring-l{bottom:16px;font-size:8px;}
    .fad-figure{font-size:52px;margin:2px 0;}
    .fad-dollar{font-size:22px;margin-top:6px;}
    .fad-per{margin-bottom:8px;}
    .fad-body{padding:22px 22px 26px;}
    .fad-title{font-size:22px;}
    .fad-deal li{font-size:14px;}
    .fad-left-note{display:block;}
    .fad-x{width:44px;height:44px;top:10px;right:10px;}
    .fad-cta{width:100%;justify-content:center;min-height:48px;}
    .fad-actions{gap:6px;}
    .fad-later{width:100%;text-align:center;min-height:44px;}
  }
  @media (prefers-reduced-motion: reduce){
    .fad-scrim,.fad-card,.fad-cta{transition:none !important;}
    .fad-card{transform:none;}
  }
"""


FOUNDER_AD_SCRIPT = """
<script>
(function () {
  var ad = document.getElementById('founderAd');
  if (!ad) return;
  var card  = document.getElementById('founderAdCard');
  var xBtn  = document.getElementById('founderAdClose');
  var cta   = document.getElementById('founderAdCta');
  var KEY = '%(key)s', QUIET_MS = %(quiet_days)d * 24 * 60 * 60 * 1000;
  var forced = (location.search + '').indexOf('%(force)s') !== -1;

  function seenRecently() {
    try {
      var raw = localStorage.getItem(KEY);
      if (!raw) return false;
      var t = parseInt(raw, 10);
      return !isNaN(t) && (Date.now() - t) < QUIET_MS;
    } catch (e) { return false; }
  }
  function remember() {
    try { localStorage.setItem(KEY, String(Date.now())); } catch (e) {}
  }
  if (!forced && seenRecently()) return;

  var lastFocus = null, opened = false, closed = false;

  function somethingElseIsOpen() {
    var film = document.getElementById('videoModal');
    var menu = document.getElementById('mobileMenu');
    return (film && film.hasAttribute('open')) || (menu && !menu.hidden);
  }

  function open() {
    if (opened || closed) return;
    if (somethingElseIsOpen()) { setTimeout(open, 2000); return; }
    opened = true;
    lastFocus = document.activeElement;
    ad.hidden = false;
    document.body.style.overflow = 'hidden';
    /* a timer, not requestAnimationFrame: a tab in the background gets
       no frames, and a flyer half-opened there would lock the scroll
       behind an invisible card until the tab came back */
    setTimeout(function () {
      ad.classList.add('is-in');
      card.focus({ preventScroll: true });
    }, 30);
  }

  function close() {
    if (!opened || closed) return;
    closed = true;
    remember();
    ad.classList.remove('is-in');
    document.body.style.overflow = '';
    setTimeout(function () { ad.hidden = true; }, 320);
    var back = (lastFocus && lastFocus.focus && lastFocus !== document.body) ? lastFocus : null;
    if (back) back.focus();
  }

  /* the seat taken: remember, and let the link go */
  cta.addEventListener('click', remember);

  var closers = ad.querySelectorAll('[data-fad-close]');
  for (var i = 0; i < closers.length; i++) closers[i].addEventListener('click', close);
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && opened && !closed) close();
  });

  /* keep the tab ring inside the flyer while it is open */
  ad.addEventListener('keydown', function (e) {
    if (e.key !== 'Tab') return;
    var f = ad.querySelectorAll('button, a[href]');
    var first = f[0], last = f[f.length - 1];
    if (e.shiftKey && (document.activeElement === first || document.activeElement === card)) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });

  if (forced) { open(); return; }

  /* five seconds of reading, or the first real scroll after a short
     dwell — whichever comes first. Never on arrival. */
  var arrived = Date.now();
  var timer = setTimeout(open, %(show_after)d);
  function onScroll() {
    if (window.scrollY < window.innerHeight * 0.35) return;
    window.removeEventListener('scroll', onScroll);
    var wait = Math.max(0, %(min_dwell)d - (Date.now() - arrived));
    clearTimeout(timer);
    setTimeout(open, wait);
  }
  window.addEventListener('scroll', onScroll, { passive: true });
})();
</script>
""" % {"key": STORAGE_KEY, "quiet_days": QUIET_DAYS, "force": FORCE_PARAM,
       "show_after": SHOW_AFTER_MS, "min_dwell": MIN_DWELL_MS}


def founder_ad_bundle(path: str) -> tuple[str, str]:
    """(extra_css, extra_markup) for the shell: both empty when this
    page does not carry the flyer or there is no offer to show."""
    if not carries_the_flyer(path):
        return "", ""
    html = founder_ad_html()
    if not html:
        return "", ""
    return FOUNDER_AD_CSS, html + FOUNDER_AD_SCRIPT
