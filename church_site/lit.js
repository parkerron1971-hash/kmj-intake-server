/* lit.js: the lit rooms kit's moving parts, shared by every church product page (2026-11-04).
   Lit.loop runs a timed scene only while it's on screen; Lit.tap leaves a finger's ring on what it presses;
   Lit.count ticks a number; stories (.lit-path) light the step in the middle of the screen; [data-lit-once]
   gets "on" the first time it's seen. Reduced motion shows each scene's end state and nothing moves. */
window.Lit = (function () {
  var reduce = !!(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches);
  function fmt(n, el) {
    if (el.hasAttribute('data-k')) return '$' + n.toFixed(1) + 'k';
    var s = Math.round(n).toLocaleString('en-US');
    return (el.hasAttribute('data-money') ? '$' : '') + s + (el.getAttribute('data-suffix') || '');
  }
  function count(el, ms) {
    var from = parseFloat(el.getAttribute('data-from')), to = parseFloat(el.getAttribute('data-to'));
    if (reduce) { el.textContent = fmt(to, el); return; }
    var t0 = performance.now();
    (function step(t) {
      var p = Math.min(1, (t - t0) / (ms || 900)), e = 1 - Math.pow(1 - p, 3);
      el.textContent = fmt(from + (to - from) * e, el);
      if (p < 1) requestAnimationFrame(step);
    })(t0);
  }
  function reset(el) { el.textContent = fmt(parseFloat(el.getAttribute('data-from')), el); }
  function tap(box, target) {
    var ring = box && box.querySelector('.lit-tap');
    if (!ring || !target || reduce) return;
    var s = box.getBoundingClientRect(), r = target.getBoundingClientRect();
    ring.style.left = (r.left - s.left + r.width / 2 - 23) + 'px';
    ring.style.top = (r.top - s.top + r.height / 2 - 23) + 'px';
    ring.style.animation = 'none'; void ring.offsetWidth; ring.style.animation = 'lit-tapit .6s ease-out';
  }
  function loop(el, steps, period, end) {
    if (!el) return;
    if (reduce) { if (end) end(); return; }
    var timers = [], running = false;
    function run() {
      steps.forEach(function (s) { timers.push(setTimeout(s[1], s[0])); });
      timers.push(setTimeout(run, period));
    }
    new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        if (e.isIntersecting && !running) { running = true; run(); }
        else if (!e.isIntersecting && running) { running = false; timers.forEach(clearTimeout); timers = []; }
      });
    }, { threshold: 0.35 }).observe(el);
  }
  function once(el, fn) {
    if (!el) return;
    new IntersectionObserver(function (es, o) {
      es.forEach(function (e) { if (e.isIntersecting) { el.classList.add('on'); if (fn) fn(el); o.disconnect(); } });
    }, { threshold: 0.3 }).observe(el);
  }
  function story(path) {
    var stage = path.querySelector('.lit-stage'), steps = path.querySelectorAll('.lit-step'), rail = path.querySelector('.lit-rail');
    if (!steps.length) return;
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        if (!e.isIntersecting) return;
        var n = +e.target.getAttribute('data-step');
        steps.forEach(function (s) {
          var m = +s.getAttribute('data-step');
          s.classList.toggle('on', m === n); s.classList.toggle('done', m < n);
        });
        if (stage) stage.setAttribute('data-step', n);
        if (rail) rail.style.setProperty('--fill', ((n - 1) / Math.max(1, steps.length - 1) * 100) + '%');
        path.dispatchEvent(new CustomEvent('lit-step', { detail: n }));
      });
    }, { rootMargin: '-45% 0px -50% 0px' });
    steps.forEach(function (s) { io.observe(s); });
    steps[0].classList.add('on');
  }
  function boot() {
    document.querySelectorAll('.lit-path').forEach(story);
    document.querySelectorAll('[data-lit-once]').forEach(function (el) {
      once(el, function () { el.querySelectorAll('[data-to]').forEach(function (n) { count(n, 1600); }); });
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
  return { reduce: reduce, count: count, reset: reset, tap: tap, loop: loop, once: once };
})();
