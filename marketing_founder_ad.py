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
  - it waits: on the home, until the visitor reaches the pricing section
    (or thirty seconds); elsewhere, five seconds of reading or the first
    real scroll. Never on arrival, never on top of the film or the
    mobile menu;
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
PRICING_WAIT_MS = 30000  # on the home: the backstop if the visitor never reaches pricing
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
            "next": min(limit, taken + 1),
            "pct": 0 if limit <= 0 else min(100, int(round(100 * taken / limit))),
            "price": prices.get("founder", 0) // 100,
            "list_price": prices.get("professional", 0) // 100,
            "credits": pricing_config.founder_credits(),
        }
    except Exception:
        return None


# ─── the founding ticket ───────────────────────────────────────────────
# Kevin, 2026-09-22: the founding seat is a futuristic TICKET (the offer),
# and the Founding Charter is what a buyer receives after checkout
# (stripe_billing's success page). One ticket, drawn twice: in the
# pricing section (marketing_pages._founder_strip_html) and in this
# popup. Everything on it is live: the next seat's number, the seats
# left, both prices, the AI actions. No script: the barcode and the
# circuit lines are drawn here, the light moves in CSS.

def _barcode(seed: int, bars: int = 34) -> str:
    out, s = [], seed or 1
    for _ in range(bars):
        s = (s * 1103515245 + 12345) & 0x7FFFFFFF
        w = 3 if s % 10 < 3 else (2 if s % 10 < 6 else 1)
        out.append(f'<i style="width:{w}px"></i>')
    return "".join(out)


_CIRCUIT = ('<svg viewBox="0 0 800 300" preserveAspectRatio="none">'
            '<path d="M0 40 H90 L100 56 H240 L250 40 H420 L430 24 H800"/>'
            '<path d="M0 110 H160 L170 94 H330 L340 110 H560 L570 126 H800"/>'
            '<path d="M0 180 H70 L80 196 H300 L310 180 H500 L510 164 H800"/>'
            '<path d="M0 250 H200 L210 266 H380 L390 250 H640 L650 234 H800"/>'
            '</svg>')


def ticket_html(n: dict, *, popup: bool) -> str:
    """The founding ticket for the live numbers `n` (see _numbers)."""
    seat = f"{n['next']:02d}"
    title = ('<h2 class="fst-title" id="founderAdTitle">Founding Seat</h2>' if popup
             else '<h3 class="fst-title">Founding Seat</h3>')
    cta_id = ' id="founderAdCta"' if popup else ""
    later = '<button type="button" class="fst-later" data-fad-close>Not now</button>' if popup else ""
    return f"""<div class="fst{' fst-pop' if popup else ''}">
      <div class="fst-holo" aria-hidden="true"></div><div class="fst-lines" aria-hidden="true">{_CIRCUIT}</div>
      <span class="fst-corner tl" aria-hidden="true"></span><span class="fst-corner bl" aria-hidden="true"></span>
      <div class="fst-main">
        <div class="fst-top"><span>The Solutionist System</span><span class="fst-live"><i></i>Seat {seat} &middot; open</span></div>
        {title}
        <div class="fst-admit">Admit one business &middot; Professional &middot; every room &middot; Chief</div>
        <div class="fst-price"><b>${n['price']}<small>/mo</small></b><s>list ${n['list_price']}</s><span>locked while you hold it</span></div>
        <div class="fst-chips"><span><b>{n['credits']:,}</b> AI actions a month</span><span><b>{n['left']}</b> of {n['limit']} seats left</span><span>Your Founding Charter on claim</span></div>
        <div class="fst-act"><a class="fst-cta"{cta_id} href="/start?plan=founder">Claim seat {seat} &rarr;</a>{later}</div>
      </div>
      <div class="fst-stub" aria-hidden="true"><span class="k">Seat</span><span class="n">{seat}</span><div class="fst-bars">{_barcode(n['next'] * 7919 + n['limit'])}</div><span class="of">N&ordm; {seat} / {n['limit']}</span></div>
    </div>"""


TICKET_CSS = """
  /* ─── the founding ticket (marketing_founder_ad.ticket_html) ─── */
  @property --fsta{syntax:'<angle>';inherits:false;initial-value:0deg}
  @keyframes fstSpin{to{--fsta:360deg}}
  @keyframes fstPulse{50%{opacity:.35}}
  @keyframes fstDrift{0%,100%{background-position:0 0,15% 0}50%{background-position:0 0,85% 0}}
  .fst{--stub:190px;--notch:18px;position:relative;display:grid;grid-template-columns:minmax(0,1fr) var(--stub);border-radius:20px;overflow:hidden;isolation:isolate;text-align:left;
    font-family:var(--body,Inter,system-ui,sans-serif);color:#fff;
    background:linear-gradient(160deg,rgba(18,24,40,.96),rgba(8,11,20,.97));box-shadow:0 40px 90px -30px #000,0 0 80px -30px rgba(46,125,255,.45);
    -webkit-mask:radial-gradient(circle var(--notch) at calc(100% - var(--stub)) 0,#0000 98%,#000) top/100% 51% no-repeat,radial-gradient(circle var(--notch) at calc(100% - var(--stub)) 100%,#0000 98%,#000) bottom/100% 51% no-repeat;
    mask:radial-gradient(circle var(--notch) at calc(100% - var(--stub)) 0,#0000 98%,#000) top/100% 51% no-repeat,radial-gradient(circle var(--notch) at calc(100% - var(--stub)) 100%,#0000 98%,#000) bottom/100% 51% no-repeat}
  .fst::before{content:"";position:absolute;inset:0;border-radius:inherit;padding:1.2px;z-index:3;pointer-events:none;
    background:conic-gradient(from var(--fsta),#22D3EE,#2E7DFF,#7C5CFF,#E040FB,#F3C56B,#22D3EE);
    -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;mask-composite:exclude;animation:fstSpin 8s linear infinite;opacity:.9}
  .fst-holo{position:absolute;inset:0;z-index:0;pointer-events:none;mix-blend-mode:screen;opacity:.55;
    background:radial-gradient(40% 60% at 70% 20%,rgba(224,64,251,.2),transparent 70%),linear-gradient(115deg,transparent 25%,rgba(34,211,238,.12) 40%,rgba(224,64,251,.14) 50%,rgba(46,125,255,.12) 60%,transparent 75%);
    background-size:100% 100%,260% 100%;animation:fstDrift 14s ease-in-out infinite}
  .fst-lines{position:absolute;inset:0;z-index:0;pointer-events:none;opacity:.5}
  .fst-lines svg{width:100%;height:100%;display:block;fill:none;stroke:rgba(34,211,238,.18);stroke-width:.8}
  .fst-corner{position:absolute;width:22px;height:22px;border:1.5px solid #22D3EE;z-index:2;opacity:.85;pointer-events:none}
  .fst-corner.tl{left:14px;top:14px;border-right:0;border-bottom:0}.fst-corner.bl{left:14px;bottom:14px;border-right:0;border-top:0}
  .fst-main{position:relative;z-index:1;padding:28px 34px 26px;display:flex;flex-direction:column;gap:12px;min-width:0}
  .fst-top{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;font:600 10.5px var(--mono,'JetBrains Mono',ui-monospace,monospace);letter-spacing:.2em;text-transform:uppercase;color:#7f8aa3}
  .fst-live{display:inline-flex;align-items:center;gap:8px;color:#22D3EE}
  .fst-live i{width:7px;height:7px;border-radius:50%;background:#22D3EE;box-shadow:0 0 10px #22D3EE;animation:fstPulse 1.8s ease-in-out infinite}
  .fst-title{margin:0;padding-bottom:.12em;font:600 clamp(30px,3.6vw,46px)/.95 var(--display,'Inter Tight',Inter,system-ui,sans-serif);letter-spacing:-.035em;background:linear-gradient(180deg,#fff 20%,#9fe9f7 60%,#5a8dff 100%);-webkit-background-clip:text;background-clip:text;color:transparent}
  .fst-admit{font:600 10.5px var(--mono,'JetBrains Mono',ui-monospace,monospace);letter-spacing:.26em;text-transform:uppercase;color:#9fe9f7}
  .fst-price{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap}
  .fst-price b{font:700 clamp(52px,6vw,72px)/.9 var(--display,'Inter Tight',Inter,system-ui,sans-serif);letter-spacing:-.05em;background:linear-gradient(180deg,#FFF1C8,#F3C56B 60%,#c9973f);-webkit-background-clip:text;background-clip:text;color:transparent}
  .fst-price b small{font-size:.34em;letter-spacing:0;-webkit-text-fill-color:#aeb7ca}
  .fst-price s{font:600 14px var(--mono,'JetBrains Mono',ui-monospace,monospace);color:#6f7b95;text-decoration-color:#E040FB;text-decoration-thickness:2px}
  .fst-price span{font:600 10.5px var(--mono,'JetBrains Mono',ui-monospace,monospace);letter-spacing:.2em;text-transform:uppercase;color:#22D3EE}
  .fst-chips{display:flex;flex-wrap:wrap;gap:8px}
  .fst-chips span{font:600 11px var(--mono,'JetBrains Mono',ui-monospace,monospace);color:#dfe7f5;border:1px solid rgba(120,160,255,.22);border-radius:999px;padding:5px 11px;background:rgba(10,14,26,.6)}
  .fst-chips span b{color:#F3C56B;font-weight:700}
  .fst-act{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-top:4px}
  .fst-cta{display:inline-flex;align-items:center;justify-content:center;height:48px;padding:0 22px;border-radius:999px;font:700 14px var(--body,Inter,system-ui,sans-serif);color:#05060a;text-decoration:none;white-space:nowrap;
    background:linear-gradient(90deg,#22D3EE,#7fb2ff 50%,#E040FB);box-shadow:0 10px 34px -10px #22D3EE;transition:transform .2s,filter .2s}
  .fst-cta:hover{transform:translateY(-2px);filter:brightness(1.08)}
  .fst-cta:focus-visible,.fst-later:focus-visible{outline:2px solid #22D3EE;outline-offset:3px}
  .fst-later{background:none;border:0;color:#7f8aa3;font:500 13px var(--body,Inter,system-ui,sans-serif);cursor:pointer;padding:8px 6px}
  .fst-later:hover{color:#fff}
  .fst-stub{position:relative;z-index:1;border-left:2px dashed rgba(159,233,247,.35);padding:26px 18px 22px;display:flex;flex-direction:column;align-items:center;justify-content:space-between;gap:10px;text-align:center;background:linear-gradient(180deg,rgba(34,211,238,.06),rgba(224,64,251,.06))}
  .fst-stub .k{font:600 10px var(--mono,'JetBrains Mono',ui-monospace,monospace);letter-spacing:.3em;color:#7f8aa3;text-transform:uppercase}
  .fst-stub .n{font:700 76px/.85 var(--display,'Inter Tight',Inter,system-ui,sans-serif);letter-spacing:-.05em;background:linear-gradient(180deg,#fff,#9fe9f7 55%,#5a8dff);-webkit-background-clip:text;background-clip:text;color:transparent}
  .fst-bars{width:100%;height:46px;display:flex;align-items:stretch;justify-content:center;gap:2px}
  .fst-bars i{display:block;background:#dff8ff;opacity:.85}
  .fst-stub .of{font:600 10px var(--mono,'JetBrains Mono',ui-monospace,monospace);letter-spacing:.2em;color:#F3C56B}
  @media (max-width:760px){
    .fst{--stubh:150px;--notch:16px;grid-template-columns:1fr;
      -webkit-mask:radial-gradient(circle var(--notch) at 0 calc(100% - var(--stubh)),#0000 98%,#000) left/51% 100% no-repeat,radial-gradient(circle var(--notch) at 100% calc(100% - var(--stubh)),#0000 98%,#000) right/51% 100% no-repeat;
      mask:radial-gradient(circle var(--notch) at 0 calc(100% - var(--stubh)),#0000 98%,#000) left/51% 100% no-repeat,radial-gradient(circle var(--notch) at 100% calc(100% - var(--stubh)),#0000 98%,#000) right/51% 100% no-repeat}
    .fst-main{padding:30px 22px 22px}
    .fst-top{justify-content:center;text-align:center}
    .fst-stub{height:var(--stubh);border-left:0;border-top:2px dashed rgba(159,233,247,.35);flex-direction:row;justify-content:space-around;padding:16px 20px}
    .fst-stub .n{font-size:58px}
    .fst-bars{width:120px;height:56px}
    .fst-cta{width:100%}
    .fst-later{width:100%;min-height:44px}
  }
  @media (prefers-reduced-motion:reduce){.fst::before,.fst-holo,.fst-live i{animation:none}}
  /* in the pricing section */
  .fst-strip{margin:30px 0 22px}
"""


def founder_ad_html() -> str:
    """The dialog markup, hidden until the script decides. Empty string
    when there is nothing to offer."""
    n = _numbers()
    if not n:
        return ""
    return f"""
<!-- The founding-seat flyer: the founding ticket in a dialog. Hidden
     until the script opens it; absent entirely when the seats are gone.
     See marketing_founder_ad.py. -->
<div class="fad" id="founderAd" role="dialog" aria-modal="true"
     aria-labelledby="founderAdTitle" data-left="{n['left']}" hidden>
  <div class="fad-scrim" data-fad-close></div>
  <div class="fad-card" id="founderAdCard" tabindex="-1">
    <button type="button" class="fad-x" id="founderAdClose" aria-label="Close" data-fad-close>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
    </button>
    {ticket_html(n, popup=True)}
  </div>
</div>"""


FOUNDER_AD_CSS = """
  /* ─── the founding-seat flyer: a dialog that holds the founding ticket ─── */
  .fad{position:fixed;inset:0;z-index:210;display:flex;align-items:center;justify-content:center;
    padding:24px;}
  .fad[hidden]{display:none;}
  .fad-scrim{position:absolute;inset:0;background:rgba(4,5,8,.8);
    -webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px);
    opacity:0;transition:opacity .28s ease;}
  .fad-card{position:relative;width:min(920px,100%);max-height:calc(100dvh - 48px);
    border-radius:20px;box-shadow:0 60px 140px rgba(0,0,0,.75);
    opacity:0;transform:translateY(18px) scale(.985);
    transition:opacity .32s ease, transform .32s cubic-bezier(.2,.8,.2,1);outline:none;}
  .fad.is-in .fad-scrim{opacity:1;}
  .fad.is-in .fad-card{opacity:1;transform:none;}
  .fad-x{position:absolute;top:-18px;right:-18px;z-index:6;width:38px;height:38px;border-radius:50%;
    display:inline-flex;align-items:center;justify-content:center;cursor:pointer;
    color:#fff;background:rgba(10,12,16,.95);border:1px solid rgba(255,255,255,.18);
    transition:background .16s, border-color .16s;}
  .fad-x svg{width:16px;height:16px;}
  .fad-x:hover{border-color:#22D3EE;}
  .fad-x:focus-visible{outline:2px solid #22D3EE;outline-offset:2px;}
  @media (max-width:720px){
    .fad{padding:70px 0 0;align-items:flex-end;overflow-y:auto;}
    .fad-card{width:100%;max-height:none;margin-top:auto;border-radius:22px 22px 0 0;transform:translateY(40px);}
    .fad-card .fst{border-radius:22px 22px 0 0;}
    .fad-x{width:44px;height:44px;top:-54px;right:10px;}
  }
  @media (prefers-reduced-motion: reduce){
    .fad-scrim,.fad-card{transition:none !important;}
    .fad-card{transform:none;}
  }
""" + TICKET_CSS


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

  /* On a page with the pricing section (the home), the flyer waits for
     the visitor to reach it on their own, or %(pricing_wait)d ms; the home's
     own motion (the room opening) never counts as reading. */
  var pricing = document.getElementById('pricing');
  if (pricing && 'IntersectionObserver' in window) {
    var backstop = setTimeout(open, %(pricing_wait)d);
    var seen = new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        if (!e.isIntersecting) return;
        seen.disconnect(); clearTimeout(backstop); setTimeout(open, %(min_dwell)d);
      });
    }, { threshold: 0.35 });
    seen.observe(pricing);
    return;
  }

  /* everywhere else: five seconds of reading, or the first real scroll
     after a short dwell, whichever comes first. Never on arrival. */
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
       "show_after": SHOW_AFTER_MS, "min_dwell": MIN_DWELL_MS,
       "pricing_wait": PRICING_WAIT_MS}


def founder_ad_bundle(path: str) -> tuple[str, str]:
    """(extra_css, extra_markup) for the shell: both empty when this
    page does not carry the flyer or there is no offer to show."""
    if not carries_the_flyer(path):
        return "", ""
    html = founder_ad_html()
    if not html:
        return "", ""
    return FOUNDER_AD_CSS, html + FOUNDER_AD_SCRIPT
