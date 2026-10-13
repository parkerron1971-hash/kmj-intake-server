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
  // While the menu is open everything behind it is inert (not focusable,
  // not clickable, not read), and Tab cycles between the close control and
  // the menu's links. Closing returns focus to the toggle.
  var behind = Array.prototype.slice.call(document.querySelectorAll(
    '.skip, [data-ladder], main, .footer, .masthead .brand, .masthead .quick, .masthead .bar-cta'));
  function setMenu(open) {
    root.classList.toggle('menu-open', open);
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (word) word.textContent = open ? 'Close' : 'Menu';
    behind.forEach(function (el) { el.inert = open; });
    if (open) { var first = menu.querySelector('a'); if (first) first.focus({ preventScroll: true }); }
    else toggle.focus({ preventScroll: true });
  }
  if (toggle && menu) {
    toggle.addEventListener('click', function () { setMenu(toggle.getAttribute('aria-expanded') !== 'true'); });
    document.addEventListener('keydown', function (e) {
      if (!root.classList.contains('menu-open')) return;
      if (e.key === 'Escape') { setMenu(false); return; }
      if (e.key !== 'Tab') return;
      var stops = [toggle].concat(Array.prototype.slice.call(menu.querySelectorAll('a[href]')));
      var at = stops.indexOf(document.activeElement);
      if (e.shiftKey && at <= 0) { e.preventDefault(); stops[stops.length - 1].focus(); }
      else if (!e.shiftKey && (at === stops.length - 1 || at === -1)) { e.preventDefault(); stops[0].focus(); }
    });
  }

  // ---- The hero: its letters arrive one by one (each wrapped in a span the
  // CSS staggers), and its tiles wipe through their photos ----
  each('[data-split]', function (el) {
    if (!still) {
      var n = 0;
      Array.prototype.slice.call(el.childNodes).forEach(function (node) {
        if (node.nodeType !== 3) return;
        var frag = document.createDocumentFragment();
        node.textContent.split('').forEach(function (ch) {
          if (ch === ' ') { frag.appendChild(document.createTextNode(' ')); return; }
          var s = document.createElement('span');
          s.className = 'ch'; s.textContent = ch; s.style.setProperty('--c', n++);
          frag.appendChild(s);
        });
        el.replaceChild(frag, node);
      });
    }
    el.classList.add('is-split');
  });
  each('[data-live-tile]', function (tile, t) {
    var imgs = tile.querySelectorAll('img');
    if (still || imgs.length < 2) return;
    var at = 0;
    imgs[0].classList.add('is-on');
    window.setTimeout(function () {
      window.setInterval(function () {
        var next = (at + 1) % imgs.length;
        Array.prototype.forEach.call(imgs, function (im) { im.classList.remove('was-on'); });
        imgs[at].classList.remove('is-on'); imgs[at].classList.add('was-on');
        imgs[next].classList.add('is-on');
        at = next;
      }, 3400);
    }, 1800 + t * 1100);
  });

  // ---- Home's pinned scene: the page holds still while the scroll zooms
  // the photo wall out from the prayer photo, slides the line across, and
  // the lens lights each word as it passes ----
  var scene = still ? null : document.querySelector('[data-scene]');
  var sc = null;
  if (scene) {
    scene.classList.add('scene-live');
    sc = {
      pin: scene.querySelector('.scene-pin'), portal: scene.querySelector('[data-portal]'),
      mark: scene.querySelector('[data-portal-mark]'),
      wall: scene.querySelector('[data-wall]'), line: scene.querySelector('[data-line]'),
      lens: scene.querySelector('[data-lens]'), lit: scene.querySelector('[data-lit]'),
      shade: scene.querySelector('[data-shade]'), end: scene.querySelector('[data-scene-end]')
    };
  }
  var clamp = function (v) { return v < 0 ? 0 : v > 1 ? 1 : v; };
  var ease = function (v) { return 1 - Math.pow(1 - v, 3); };
  function sceneFrame(vh) {
    var r = scene.getBoundingClientRect(), vw = root.clientWidth;
    var p = clamp(-r.top / Math.max(1, r.height - vh));
    // 1. The heart opens (p 0 to .22): the mark grows from a third of the
    // screen until its silhouette holds the whole viewport, slowly at first
    // and then rushing open; the drawn mark fades as it passes the edges.
    var o = clamp(p / 0.22), small = Math.min(vw, vh) * (vw < 700 ? 0.66 : 0.46), big = 1.3 * (vw + vh);
    sc.pin.style.setProperty('--ms', (small + (big - small) * o * o * o).toFixed(1) + 'px');
    sc.portal.classList.toggle('is-open', o >= 1);
    sc.mark.style.opacity = (1 - clamp((o - 0.55) / 0.4)).toFixed(3);
    // 2. The wall pulls back from the church family to all nine photos.
    sc.wall.style.transform = 'scale(' + (3.05 - 2.05 * ease(clamp((p - 0.2) / 0.7))).toFixed(4) + ')';
    // 3. The line crosses, lit in the lens; then "This is who we are."
    var tw = sc.line.scrollWidth, tp = clamp((p - 0.26) / 0.62);
    var x = vw - tp * (vw + tw);
    sc.line.style.transform = 'translate3d(' + x.toFixed(1) + 'px,-50%,0)';
    var lensLeft = sc.lens.getBoundingClientRect().left;
    sc.lit.style.transform = 'translate3d(' + (x - lensLeft).toFixed(1) + 'px,-50%,0)';
    sc.lens.style.opacity = (p > 0.27 && p < 0.86) ? 1 : 0;
    sc.shade.style.opacity = (0.08 + 0.5 * clamp((p - 0.18) / 0.12) - 0.22 * clamp((p - 0.86) / 0.1)).toFixed(3);
    sc.end.style.opacity = clamp((p - 0.88) / 0.09).toFixed(3);
    sc.end.style.transform = 'translateY(' + (24 * (1 - clamp((p - 0.88) / 0.09))).toFixed(1) + 'px)';
  }

  // ---- On scroll: the masthead tucks away going down and returns going
  // up; the C.I.T.Y. L.O.V.E. ladder lights a letter per eighth of the
  // page; photos marked data-drift move a little slower than the page ----
  var hero = still ? null : document.querySelector('[data-hero]');
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
    if (hero) {
      var hr = hero.getBoundingClientRect();
      if (hr.bottom > -50) hero.style.setProperty('--hp', clamp(-hr.top / Math.max(1, hr.height)).toFixed(3));
    }
    if (sc) {
      var sr = scene.getBoundingClientRect();
      if (sr.bottom > -50 && sr.top < vh + 50) sceneFrame(vh);
    }
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
      // Only Sunday names the building: Thursday is "Mid-week Bible study"
      // and nothing more (Kevin's wording), never tied to an address.
      var gatherings = [
        { day: 0, start: 11 * 60, length: 150, what: 'Sunday service', at: '11am', where: ' at 1084 Allen Ave' },
        { day: 4, start: 18 * 60, length: 90, what: 'Mid-week Bible study', at: '6pm', where: '' }
      ];
      var text = '', best = null;
      gatherings.forEach(function (g) {
        if (g.day === today && now >= g.start && now < g.start + g.length) text = 'Happening now: ' + g.what + g.where;
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
