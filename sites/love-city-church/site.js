(function () {
  // Everything here is an enhancement: without script, or with reduced
  // motion, every word and photo shows and every link works.
  var root = document.documentElement;
  var still = !window.matchMedia || window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var each = function (sel, fn) { Array.prototype.forEach.call(document.querySelectorAll(sel), fn); };

  // ---- The menu: a full-screen panel (the 'js' class that hides it until
  // opened is set in the head) ----
  var toggle = document.querySelector('[data-menu-toggle]');
  var menu = document.querySelector('[data-menu]');
  var word = document.querySelector('[data-menu-word]');
  each('[data-menu] .menu-links a', function (a, i) { a.style.setProperty('--i', i); });
  function setMenu(open) {
    root.classList.toggle('menu-open', open);
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (word) word.textContent = open ? 'Close' : 'Menu';
    if (open) { var first = menu.querySelector('a'); if (first) first.focus({ preventScroll: true }); }
  }
  if (toggle && menu) {
    toggle.addEventListener('click', function () { setMenu(toggle.getAttribute('aria-expanded') !== 'true'); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && root.classList.contains('menu-open')) { setMenu(false); toggle.focus(); }
    });
  }

  // ---- On scroll: the masthead tucks away going down and returns going
  // up; the C.I.T.Y. L.O.V.E. ladder lights a letter per eighth of the
  // page; photos marked data-drift move a little slower than the page ----
  var head = document.querySelector('[data-masthead]');
  var ladder = Array.prototype.slice.call(document.querySelectorAll('[data-ladder] span'));
  var drifters = still ? [] : Array.prototype.slice.call(document.querySelectorAll('[data-drift]'));
  var lastY = window.pageYOffset || 0, ticking = false;
  function frame() {
    var y = window.pageYOffset || 0, vh = window.innerHeight;
    if (head) {
      head.classList.toggle('is-scrolled', y > 8);
      if (root.classList.contains('menu-open') || y < 320 || y < lastY - 6) head.classList.remove('is-tucked');
      else if (y > lastY + 6) head.classList.add('is-tucked');
    }
    lastY = y;
    if (ladder.length) {
      var max = root.scrollHeight - vh, lit = 1;
      if (max > 0) lit = Math.min(ladder.length, 1 + Math.floor((y / max) * ladder.length * 0.9999));
      ladder.forEach(function (s, i) { s.classList.toggle('lit', i < lit); s.classList.toggle('now', i === lit - 1); });
    }
    drifters.forEach(function (el) {
      var r = el.getBoundingClientRect();
      if (r.bottom < -300 || r.top > vh + 300) return;
      var k = parseFloat(el.getAttribute('data-drift')) || 0.06;
      el.style.transform = 'translate3d(0,' + ((r.top + r.height / 2 - vh / 2) * -k).toFixed(1) + 'px,0)';
    });
    ticking = false;
  }
  window.addEventListener('scroll', function () {
    if (!ticking) { ticking = true; window.requestAnimationFrame(frame); }
  }, { passive: true });
  window.addEventListener('resize', frame);
  frame();

  // ---- Reveals: headlines rise out of their lines, photos develop into
  // focus, the culture-key letters arrive one by one. Only hidden once we
  // know they can be revealed again. ----
  if (!still && 'IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
      });
    }, { rootMargin: '0px 0px -10% 0px', threshold: 0.01 });
    each('[data-reveal]', function (el) {
      el.querySelectorAll('.line').forEach(function (l, i) { l.style.setProperty('--n', i); });
      el.classList.add('will-reveal');
      io.observe(el);
    });
  }

  // ---- About: the culture keys as a scroll story. The giant letter in the
  // rail becomes the key being read. ----
  var rail = document.querySelector('[data-scrolly-letter]');
  if (rail && 'IntersectionObserver' in window) {
    var showing = rail.textContent;
    var keyIO = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        var letter = e.target.getAttribute('data-letter');
        if (!e.isIntersecting || letter === showing) return;
        showing = letter;
        rail.textContent = letter;
        if (!still) { rail.classList.remove('flip'); void rail.offsetWidth; rail.classList.add('flip'); }
      });
    }, { rootMargin: '-45% 0px -50% 0px' });
    each('[data-scrolly] [data-letter]', function (k) { keyIO.observe(k); });
  }

  // ---- Muskegon's day and time, whatever the visitor's own time zone ----
  var today = null, now = 0;
  if (window.Intl && Intl.DateTimeFormat) {
    try {
      var parts = {};
      new Intl.DateTimeFormat('en-US', { timeZone: 'America/Detroit', weekday: 'short', hour: 'numeric', minute: 'numeric', hourCycle: 'h23' })
        .formatToParts(new Date()).forEach(function (p) { parts[p.type] = p.value; });
      today = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 }[parts.weekday];
      now = (parseInt(parts.hour, 10) % 24) * 60 + parseInt(parts.minute, 10);
    } catch (e) { today = null; }
  }

  // ---- Events: mark today in the week ----
  if (today !== null) each('[data-week] [data-day="' + today + '"]', function (d) { d.classList.add('today'); });

  // ---- The next gathering. A service is "happening now" for its usual
  // length. ----
  var next = document.querySelector('[data-next]');
  if (next && today !== null) {
    try {
      var names = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
      var gatherings = [
        { day: 0, start: 11 * 60, length: 150, what: 'Sunday service', at: '11am' },
        { day: 4, start: 18 * 60, length: 90, what: 'Mid-week Bible study', at: '6pm' }
      ];
      var text = '', best = null;
      gatherings.forEach(function (g) {
        if (g.day === today && now >= g.start && now < g.start + g.length) text = 'Happening now: ' + g.what + ' at 1084 Allen Ave';
        var wait = ((g.day - today + 7) % 7) * 1440 + g.start - now;
        if (wait <= 0) wait += 7 * 1440;
        if (!best || wait < best.wait) best = { g: g, wait: wait };
      });
      if (!text && best) {
        var days = Math.floor((now + best.wait) / 1440);
        var when = days === 0 ? (best.g.start >= 17 * 60 ? 'tonight' : 'today') : days === 1 ? 'tomorrow' : 'this ' + names[best.g.day];
        text = 'Next: ' + best.g.what + ', ' + when + ' at ' + best.g.at;
      }
      if (text) { next.textContent = text; next.hidden = false; }
    } catch (e) { /* the times above it still say everything */ }
  }
})();
