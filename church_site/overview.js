/* The church overview: the closing window, the move and the size picker. */
(function () {
  'use strict';
  var NS = 'http://www.w3.org/2000/svg';
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  var ROOMS = {
    people: { name: 'People and Care', line: 'Every member family can have a shepherd', slug: 'people-and-care', t: ['#5EEAD4', '#14B8A6', '#0F766E'] },
    giving: { name: 'Giving', line: 'Your own Stripe, no cut of giving', slug: 'giving', t: ['#86EFAC', '#22C55E', '#15803D'] },
    kids: { name: 'Kids and Youth', line: 'Check-in, tags and safe pickup', slug: 'kids-and-youth', t: ['#FDBA74', '#F97316', '#C2410C'] },
    groups: { name: 'Groups and Classes', line: "This week's study, from Sunday's message", slug: 'groups-and-classes', t: ['#93C5FD', '#3B82F6', '#1D4ED8'] },
    app: { name: 'Member App', line: 'The church in every pocket', slug: 'member-app', t: ['#F9A8D4', '#EC4899', '#BE185D'] },
    web: { name: 'Website and Sermons', line: 'Your front door, always open', slug: 'website-and-sermons', t: ['#FDE68A', '#EAB308', '#A16207'] },
    office: { name: 'Office and Books', line: 'The books, and who sees giving', slug: 'office-and-books', t: ['#E2E8F0', '#94A3B8', '#475569'] }
  };
  var ORDER = ['people', 'giving', 'kids', 'groups', 'app', 'web', 'office'];
  var HEAD = ['#2E1065', '#3B1A7A', '#4C1D95', '#5B21B6', '#6D28D9', '#7C5CFF'];

  function rng(seed) { return function () { seed |= 0; seed = seed + 0x6D2B79F5 | 0; var t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
  function el(name, attrs, parent) { var e = document.createElementNS(NS, name); for (var k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; }

  /* ---------- geometry of the window (viewBox 0 0 400 640) ---------- */
  function lancet(x0, x1, ys, yb, r) {
    var half = (x1 - x0) / 2, ax = (x0 + x1) / 2, ay = ys - Math.sqrt(r * r - (r - half) * (r - half));
    return { x0: x0, x1: x1, ys: ys, yb: yb, r: r, cl: [x0 + r, ys], cr: [x1 - r, ys], ax: ax, ay: ay,
      d: 'M' + x0 + ',' + yb + ' L' + x0 + ',' + ys + ' A' + r + ',' + r + ' 0 0 1 ' + ax + ',' + ay.toFixed(1) + ' A' + r + ',' + r + ' 0 0 1 ' + x1 + ',' + ys + ' L' + x1 + ',' + yb + ' Z' };
  }
  function inside(L, x, y) {
    if (y > L.yb || x < L.x0 || x > L.x1) return false;
    if (y >= L.ys) return true;
    return Math.hypot(x - L.cl[0], y - L.cl[1]) <= L.r && Math.hypot(x - L.cr[0], y - L.cr[1]) <= L.r;
  }
  function edgeDist(L, x, y) {
    if (y >= L.ys) return Math.min(x - L.x0, L.x1 - x, L.yb - y);
    return Math.min(L.r - Math.hypot(x - L.cl[0], y - L.cl[1]), L.r - Math.hypot(x - L.cr[0], y - L.cr[1]), L.yb - y);
  }
  var OUTER = lancet(16, 384, 250, 634, 250);
  var INNER = lancet(28, 372, 250, 622, 238);
  var LEFT = lancet(42, 192, 338, 608, 116);
  var RIGHT = lancet(208, 358, 338, 608, 116);
  var ROSE = { cx: 200, cy: 130, r: 60 };

  function buildWindow(svg, mini) {
    var uid = mini ? 'm' : 'w';
    var R = rng(mini ? 77 : 2026);
    var defs = el('defs', {}, svg);
    // the S mark's own gradient, kept inside this drawing
    var lg = el('linearGradient', { id: uid + 'mk', x1: 0, y1: 0, x2: 1, y2: 1 }, defs);
    el('stop', { offset: 0, 'stop-color': '#E040FB' }, lg); el('stop', { offset: .55, 'stop-color': '#7C5CFF' }, lg); el('stop', { offset: 1, 'stop-color': '#22D3EE' }, lg);
    ORDER.forEach(function (k) {
      var g = el('radialGradient', { id: uid + 'p-' + k, cx: ROSE.cx, cy: ROSE.cy, r: ROSE.r, gradientUnits: 'userSpaceOnUse' }, defs);
      el('stop', { offset: .3, 'stop-color': ROOMS[k].t[2] }, g); el('stop', { offset: 1, 'stop-color': ROOMS[k].t[0] }, g);
    });
    var sun = el('radialGradient', { id: uid + 'sun', cx: 210, cy: 250, r: 330, gradientUnits: 'userSpaceOnUse' }, defs);
    el('stop', { offset: 0, 'stop-color': '#FFFFFF', 'stop-opacity': .34 }, sun); el('stop', { offset: .55, 'stop-color': '#FFFFFF', 'stop-opacity': .06 }, sun); el('stop', { offset: 1, 'stop-color': '#FFFFFF', 'stop-opacity': 0 }, sun);
    [['cin', INNER], ['cl', LEFT], ['cr', RIGHT]].forEach(function (c) { var cp = el('clipPath', { id: uid + c[0] }, defs); el('path', { d: c[1].d }, cp); });
    if (!mini) {
      var f = el('filter', { id: uid + 'tex', x: 0, y: 0, width: '100%', height: '100%' }, defs);
      el('feTurbulence', { type: 'fractalNoise', baseFrequency: '.85', numOctaves: 2, seed: 4 }, f);
      el('feColorMatrix', { values: '0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 1.4 -.55' }, f);
    }

    // the backing: dark stone behind everything
    el('path', { d: OUTER.d, fill: '#12141B' }, svg);

    // a jittered mesh of glass over the whole opening
    var cell = mini ? 50 : 38, x0 = 28, x1 = 372, y0 = 8, y1 = 622;
    var cols = Math.ceil((x1 - x0) / cell), rows = Math.ceil((y1 - y0) / cell);
    var cw = (x1 - x0) / cols, ch = (y1 - y0) / rows, P = [];
    for (var j = 0; j <= rows; j++) {
      P[j] = [];
      for (var i = 0; i <= cols; i++) {
        var jx = (i === 0 || i === cols) ? 0 : (R() - .5) * cw * .62, jy = (j === 0 || j === rows) ? 0 : (R() - .5) * ch * .62;
        P[j][i] = [x0 + i * cw + jx, y0 + j * ch + jy];
      }
    }
    var tris = [];
    for (j = 0; j < rows; j++) for (i = 0; i < cols; i++) {
      var a = P[j][i], b = P[j][i + 1], c = P[j + 1][i + 1], d = P[j + 1][i];
      if (R() < .5) { tris.push([a, b, c]); tris.push([a, c, d]); } else { tris.push([a, b, d]); tris.push([b, c, d]); }
    }
    function pts(t) { return t.map(function (p) { return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join(' '); }
    function cen(t) { return [(t[0][0] + t[1][0] + t[2][0]) / 3, (t[0][1] + t[1][1] + t[2][1]) / 3]; }
    var lw = mini ? 3.2 : 2.3;

    // the head: deep violet glass around the rose, with a few jewels of the mark's magenta and cyan
    var head = el('g', { 'clip-path': 'url(#' + uid + 'cin)', class: 'gb' }, svg);
    tris.forEach(function (t) {
      var m = cen(t), r = R(), fill;
      if (r < .07) fill = '#E040FB'; else if (r < .14) fill = '#22D3EE'; else if (r < .2) fill = '#C4B5FD';
      else { var near = 1 - Math.min(1, Math.hypot(m[0] - ROSE.cx, m[1] - ROSE.cy) / 230); fill = HEAD[Math.max(0, Math.min(HEAD.length - 1, Math.round(near * 4 + R() * 2.2)))]; }
      el('polygon', { points: pts(t), fill: fill, stroke: '#0A0B10', 'stroke-width': lw, 'stroke-linejoin': 'round' }, head);
    });

    // the two tall lights: three rooms each, flowing bottom to top, with the office as their clear border
    function lightFor(L, seq) {
      var wrap = el('g', { 'clip-path': 'url(#' + uid + (L === LEFT ? 'cl' : 'cr') + ')' }, svg);
      var groups = {};
      seq.concat(['office']).forEach(function (k) { groups[k] = el('g', { class: 'gr g-' + k, 'data-room': k }, wrap); });
      tris.forEach(function (t) {
        var m = cen(t);
        var touches = t.some(function (p) { return p[0] >= L.x0 - 2 && p[0] <= L.x1 + 2 && p[1] >= L.ay - 2; });
        if (!touches) return;
        var k;
        if (!inside(L, m[0], m[1]) || edgeDist(L, m[0], m[1]) < (mini ? 15 : 13)) k = 'office';
        else {
          var u = (L.yb - m[1]) / (L.yb - L.ay) + (R() - .5) * .16 + .05 * Math.sin(m[0] * .07 + (L === LEFT ? 0 : 2));
          k = seq[u < .36 ? 0 : u < .68 ? 1 : 2];
        }
        var tint = ROOMS[k].t, r = R();
        el('polygon', { points: pts(t), fill: r < .52 ? tint[1] : r < .82 ? tint[0] : tint[2], stroke: '#0A0B10', 'stroke-width': lw, 'stroke-linejoin': 'round' }, groups[k]);
      });
    }
    lightFor(LEFT, ['kids', 'web', 'giving']);
    lightFor(RIGHT, ['app', 'groups', 'people']);

    // the rose: seven petals, one for each part of church life, around the mark
    var rose = el('g', {}, svg);
    el('circle', { cx: ROSE.cx, cy: ROSE.cy, r: ROSE.r + 2, fill: '#0A0B10' }, rose);
    var n = ORDER.length, rin = 21, rout = ROSE.r - 3;
    ORDER.forEach(function (k, idx) {
      var a0 = -Math.PI / 2 + (idx - .5) * 2 * Math.PI / n + .05, a1 = -Math.PI / 2 + (idx + .5) * 2 * Math.PI / n - .05;
      var p = function (rr, aa) { return (ROSE.cx + rr * Math.cos(aa)).toFixed(1) + ',' + (ROSE.cy + rr * Math.sin(aa)).toFixed(1); };
      var g = el('g', { class: 'gr g-' + k, 'data-room': k }, rose);
      el('path', { d: 'M' + p(rin, a0) + ' L' + p(rout, a0) + ' A' + rout + ',' + rout + ' 0 0 1 ' + p(rout, a1) + ' L' + p(rin, a1) + ' A' + rin + ',' + rin + ' 0 0 0 ' + p(rin, a0) + ' Z',
        fill: 'url(#' + uid + 'p-' + k + ')', stroke: '#0A0B10', 'stroke-width': mini ? 4 : 2.6, 'stroke-linejoin': 'round' }, g);
      if (!mini) { var am = (a0 + a1) / 2; el('circle', { cx: (ROSE.cx + 46 * Math.cos(am)).toFixed(1), cy: (ROSE.cy + 46 * Math.sin(am)).toFixed(1), r: 3.2, fill: ROOMS[k].t[0], stroke: '#0A0B10', 'stroke-width': 1.6 }, g); }
    });
    el('circle', { cx: ROSE.cx, cy: ROSE.cy, r: rin - 1, fill: '#0B0C11', stroke: '#2A2E3A', 'stroke-width': 1 }, rose);
    var mk = el('svg', { x: ROSE.cx - 14, y: ROSE.cy - 12, width: 28, height: 24, viewBox: '8 36 496 424' }, rose);
    var mg = el('g', { fill: 'url(#' + uid + 'mk)', stroke: '#fff', 'stroke-width': 14, 'stroke-opacity': .95 }, mk);
    ['18,46 175,232 237,231 133,98 376,99 356,131 412,167 494,49', '205,138 338,241 232,391 274,449 435,221 319,137', '264,274 149,279 201,359'].forEach(function (pp) { el('polygon', { points: pp }, mg); });

    // light from behind, and the glass's own grain
    el('path', { d: INNER.d, fill: 'url(#' + uid + 'sun)', style: 'mix-blend-mode:screen;pointer-events:none' }, svg);
    if (!mini) el('rect', { x: 28, y: 8, width: 344, height: 614, filter: 'url(#' + uid + 'tex)', opacity: .16, 'clip-path': 'url(#' + uid + 'cin)', style: 'mix-blend-mode:overlay;pointer-events:none' }, svg);

    // the stone: frame, mullion, the lights' arches, the rose's ring, the sill
    var stone = el('g', { fill: 'none', stroke: '#1C1F29', 'stroke-linejoin': 'round', style: 'pointer-events:none' }, svg);
    el('path', { d: LEFT.d, 'stroke-width': mini ? 12 : 9 }, stone);
    el('path', { d: RIGHT.d, 'stroke-width': mini ? 12 : 9 }, stone);
    el('rect', { x: 192, y: 338, width: 16, height: 284, fill: '#1C1F29', stroke: 'none' }, stone);
    el('circle', { cx: ROSE.cx, cy: ROSE.cy, r: ROSE.r + 1, 'stroke-width': mini ? 12 : 9 }, stone);
    el('path', { d: INNER.d, 'stroke-width': mini ? 30 : 24 }, stone);
    el('path', { d: OUTER.d, 'stroke-width': 1.5, stroke: '#3A3F52' }, stone);
    el('path', { d: INNER.d, 'stroke-width': 1, stroke: 'rgba(255,255,255,.10)' }, stone);
    el('rect', { x: 4, y: 612, width: 392, height: 26, rx: 4, fill: '#1C1F29', stroke: '#3A3F52', 'stroke-width': 1.2 }, stone);
    el('rect', { x: 10, y: 613, width: 380, height: 2, fill: 'rgba(255,255,255,.10)', stroke: 'none' }, stone);
    return svg;
  }

  // the small window over the closing
  document.querySelectorAll('svg[data-mini]').forEach(function (s) { buildWindow(s, true); });

  // the closing window's light
  var sb = document.getElementById('beams-start'), start = document.getElementById('start');
  if (sb) ['people', 'kids', 'groups', 'app', 'giving'].forEach(function (k, i) {
    var b = document.createElement('i'); b.style.setProperty('--bc', ROOMS[k].t[1]); b.style.setProperty('--bw', (150 + i * 20) + 'px');
    b.style.setProperty('--ba', (-24 + i * 12) + 'deg'); b.className = 'on'; b.style.opacity = '.32'; sb.appendChild(b);
  });
  function placeStart() {
    if (!sb || !start) return;
    var s = start.querySelector('svg[data-mini]'); if (!s) return;
    var r0 = start.getBoundingClientRect(), r1 = s.getBoundingClientRect();
    sb.style.setProperty('--wx', (r1.left - r0.left + r1.width / 2) + 'px'); sb.style.setProperty('--wy', (r1.top - r0.top + r1.height * .6) + 'px');
  }

  var rt; function relayout() { placeStart(); }
  window.addEventListener('resize', function () { clearTimeout(rt); rt = setTimeout(function () { relayout(); drawRoom(true); }, 120); });
  relayout();
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(relayout);
  window.addEventListener('load', relayout);

  /* ---------- the move ---------- */
  var DD = {
    'Subsplash': '<b>Subsplash keeps a new person for every form a visitor fills in.</b> We bring each person over once, and a parent and child who share a name stay two people.',
    'A spreadsheet': '<b>Spreadsheets drift: one family on three tabs.</b> We bring each person over once, and a parent and child who share a name stay two people.',
    '_': '<b>If your old system has someone twice, they come over once.</b> A parent and child who share a name stay two people.'
  };
  document.querySelectorAll('.mv-chips button').forEach(function (b) {
    b.addEventListener('click', function () {
      document.querySelectorAll('.mv-chips button').forEach(function (o) { o.setAttribute('aria-checked', String(o === b)); });
      var f = b.getAttribute('data-from');
      document.getElementById('mv-from').textContent = f;
      document.getElementById('mv-dd-t').innerHTML = DD[f] || DD._;
    });
  });
  var dd = document.getElementById('mv-dd');
  if (dd) { if (reduce) dd.classList.add('merged'); else setInterval(function () { dd.classList.toggle('merged'); }, 2600); }

  /* ---------- how many on a Sunday ---------- */
  // The plans, their prices and what each holds come from the page (church_site._picker), drawn from the same
  // dials checkout reads. No picker on the page (the plans by size switched off) means nothing to do.
  var PK = null; try { PK = JSON.parse(document.getElementById('pk-data').textContent); } catch (e) { PK = null; }
  var PLANS = PK ? PK.plans : [], SEG = PK ? PK.seg : [], TOP = PK ? PK.top : 0, MULTI = PK ? PK.multi : null;
  function fill(ul, items) { ul.textContent = ''; items.forEach(function (t) { var li = document.createElement('li'); li.textContent = t; ul.appendChild(li); }); }
  function peopleOf(v) {
    if (v > 980) return TOP + 1;
    for (var s = 0; s < SEG.length; s++) { var g = SEG[s]; if (v <= g[1]) { var p = g[2] + (v - g[0]) / (g[1] - g[0]) * (g[3] - g[2]); return p < 100 ? Math.round(p / 5) * 5 : p < 500 ? Math.round(p / 10) * 10 : Math.round(p / 50) * 50; } }
    return TOP;
  }
  function vOf(p) {
    if (p > TOP) return 1000;
    for (var s = 0; s < SEG.length; s++) { var g = SEG[s]; if (p <= g[3]) return Math.round(g[0] + (Math.max(p, g[2]) - g[2]) / (g[3] - g[2]) * (g[1] - g[0])); }
    return 980;
  }
  function planOf(p) { for (var i = 0; i < PLANS.length; i++) if (p <= PLANS[i].max) return i; return -1; }
  var range = PLANS.length ? document.getElementById('pk-range') : null, yearly = false, people = 160;
  var cards = range ? document.querySelectorAll('.plans.four .pc') : [];
  cards.forEach(function (c) { var s = document.createElement('span'); s.className = 'you'; s.textContent = 'Your size'; c.insertBefore(s, c.firstChild); });
  function showPlan() {
    var i = planOf(people), out = document.getElementById('pk-out');
    out.textContent = people > TOP ? TOP.toLocaleString('en-US') + '+' : people.toLocaleString('en-US');
    var nm = document.getElementById('pk-name'), pr = document.getElementById('pk-price'), per = document.getElementById('pk-per'), ul = document.getElementById('pk-list'), go = document.getElementById('pk-go');
    if (i < 0) {
      nm.textContent = MULTI.name; pr.textContent = MULTI.price; per.textContent = MULTI.per;
      fill(ul, MULTI.items);
      go.hidden = true;
    } else {
      var P = PLANS[i];
      nm.textContent = P.name; pr.textContent = yearly ? P.y : P.m; per.textContent = yearly ? 'a year' : 'a month';
      fill(ul, P.items);
      go.hidden = false; go.textContent = 'Start free';
    }
    cards.forEach(function (c, ci) { c.classList.toggle('is-you', ci === i); });
    var cap = document.getElementById('pk-cap');
    cap.textContent = ''; var cb = document.createElement('b'); cb.textContent = i < 0 ? MULTI.name : PLANS[i].name; cap.appendChild(cb);
    cap.appendChild(document.createTextNode(i < 0 ? ' · more than one room' : ' · room for ' + PLANS[i].max.toLocaleString('en-US')));
    drawRoom(false);
  }
  if (range) {
    range.value = vOf(people);
    range.addEventListener('input', function () { people = peopleOf(+range.value); showPlan(); });
  }
  document.querySelectorAll('[data-billing] button[data-period]').forEach(function (b) {
    b.addEventListener('click', function () { yearly = b.getAttribute('data-period') === 'yearly'; showPlan(); });
  });

  // the sanctuary, drawn as seats
  var cv = document.getElementById('pk-canvas'), cx = cv ? cv.getContext('2d') : null, shown = 0, anim = null, layoutKey = '';
  var seats = [], geo = null;
  function layout(cap, W, H) {
    var rows = Math.max(5, Math.round(Math.sqrt(cap / 3.1))), per = Math.ceil(cap / rows); if (per % 2) per++;
    var yTop = H * .30, yBot = H * .93, list = [];
    var pw = W * .86;
    for (var r = 0; r < rows; r++) {
      var t = rows === 1 ? 1 : r / (rows - 1), s = .66 + .34 * t, y = yTop + (yBot - yTop) * t;
      var width = pw * s, aisle = 22 * s, side = (width - aisle) / 2, n = per / 2, sp = side / n;
      for (var k = 0; k < n; k++) {
        list.push({ r: r, k: k, x: W / 2 - aisle / 2 - sp * (k + .5), y: y, s: s, sp: sp });
        list.push({ r: r, k: k, x: W / 2 + aisle / 2 + sp * (k + .5), y: y, s: s, sp: sp });
      }
    }
    list.sort(function (a, b) { return a.r - b.r || a.k - b.k; });
    var rowGap = (yBot - yTop) / Math.max(1, rows - 1);
    return { seats: list, rows: rows, per: per, rowGap: rowGap, yTop: yTop, yBot: yBot, pw: pw };
  }
  function paint(n, col) {
    var W = cv.clientWidth, H = cv.clientHeight, d = Math.min(2, window.devicePixelRatio || 1);
    if (cv.width !== Math.round(W * d) || cv.height !== Math.round(H * d)) { cv.width = Math.round(W * d); cv.height = Math.round(H * d); }
    cx.setTransform(d, 0, 0, d, 0, 0);
    var bg = cx.createLinearGradient(0, 0, 0, H); bg.addColorStop(0, '#0E1019'); bg.addColorStop(1, '#07080B');
    cx.fillStyle = bg; cx.fillRect(0, 0, W, H);
    // the back wall: a small window, two screens, the platform
    var wx = W / 2, wy = H * .05, ww = Math.min(30, W * .05), wh = ww * 1.6;
    var beam = cx.createLinearGradient(0, wy, 0, H); beam.addColorStop(0, 'rgba(255,236,200,.16)'); beam.addColorStop(1, 'rgba(255,236,200,0)');
    cx.fillStyle = beam; cx.beginPath(); cx.moveTo(wx - ww * .4, wy + wh); cx.lineTo(wx + ww * .4, wy + wh); cx.lineTo(wx + W * .26, H); cx.lineTo(wx - W * .26, H); cx.closePath(); cx.fill();
    cx.save(); cx.beginPath(); cx.moveTo(wx - ww / 2, wy + wh); cx.lineTo(wx - ww / 2, wy + ww * .5); cx.quadraticCurveTo(wx - ww / 2, wy, wx, wy - ww * .15); cx.quadraticCurveTo(wx + ww / 2, wy, wx + ww / 2, wy + ww * .5); cx.lineTo(wx + ww / 2, wy + wh); cx.closePath();
    cx.shadowColor = 'rgba(167,139,250,.8)'; cx.shadowBlur = 18; cx.fillStyle = '#0A0B10'; cx.fill(); cx.clip(); cx.shadowBlur = 0;
    var cols7 = ['#F97316', '#EAB308', '#22C55E', '#14B8A6', '#3B82F6', '#EC4899', '#94A3B8'];
    for (var c = 0; c < 7; c++) { cx.fillStyle = cols7[c]; cx.fillRect(wx - ww / 2 + c * ww / 7 + .6, wy - ww, ww / 7 - 1.2, wh + ww * 1.2); }
    cx.restore();
    [[-1], [1]].forEach(function (sd) { var sx = wx + sd[0] * W * .27, sw = W * .12, sh = sw * .56, sy = H * .07; cx.fillStyle = '#141826'; cx.strokeStyle = '#2A2F3F'; cx.lineWidth = 1; roundRect(sx - sw / 2, sy, sw, sh, 3); cx.fill(); cx.stroke(); cx.fillStyle = 'rgba(167,139,250,.22)'; roundRect(sx - sw / 2 + 3, sy + 3, sw - 6, sh - 6, 2); cx.fill(); });
    var py = H * .2; cx.fillStyle = '#151826'; roundRect(W * .26, py, W * .48, H * .05, 6); cx.fill(); cx.fillStyle = 'rgba(255,255,255,.07)'; cx.fillRect(W * .26 + 6, py, W * .48 - 12, 1.5);
    cx.fillStyle = '#20253A'; roundRect(wx - 9, py - 16, 18, 20, 3); cx.fill();
    // the pews and the people
    var g = geo; if (!g) return;
    var R = Math.max(1.1, Math.min(g.seats[0].sp * .31 / g.seats[0].s, g.rowGap * .27));
    for (var r = 0; r < g.rows; r++) {
      var t = g.rows === 1 ? 1 : r / (g.rows - 1), s = .66 + .34 * t, y = g.yTop + (g.yBot - g.yTop) * t, width = g.pw * s, aisle = 22 * s, side = (width - aisle) / 2;
      cx.fillStyle = '#1A1E2B';
      roundRect(W / 2 - aisle / 2 - side, y + R * s * .9, side, Math.max(1.5, R * s * .9), 2); cx.fill();
      roundRect(W / 2 + aisle / 2, y + R * s * .9, side, Math.max(1.5, R * s * .9), 2); cx.fill();
    }
    cx.globalCompositeOperation = 'lighter';
    for (var i = 0; i < n && i < g.seats.length; i++) { var p = g.seats[i]; cx.fillStyle = hexA(col, .13); cx.beginPath(); cx.arc(p.x, p.y, R * p.s * 2.6, 0, 6.283); cx.fill(); }
    cx.globalCompositeOperation = 'source-over';
    for (i = 0; i < g.seats.length; i++) {
      var q = g.seats[i]; cx.beginPath(); cx.arc(q.x, q.y, R * q.s, 0, 6.283);
      cx.fillStyle = i < n ? '#FFEBCB' : '#2A2F3E'; cx.fill();
    }
  }
  function hexA(h, a) { var n = parseInt(h.slice(1), 16); return 'rgba(' + (n >> 16) + ',' + (n >> 8 & 255) + ',' + (n & 255) + ',' + a + ')'; }
  function roundRect(x, y, w, h, r) { cx.beginPath(); cx.moveTo(x + r, y); cx.arcTo(x + w, y, x + w, y + h, r); cx.arcTo(x + w, y + h, x, y + h, r); cx.arcTo(x, y + h, x, y, r); cx.arcTo(x, y, x + w, y, r); cx.closePath(); }
  function drawRoom(force) {
    if (!cv || !cx || !cv.clientWidth) return;
    var i = planOf(people), P = i < 0 ? PLANS[3] : PLANS[i], cap = P.max, target = Math.min(people, cap);
    var key = cap + 'x' + cv.clientWidth + 'x' + cv.clientHeight;
    if (key !== layoutKey || force) { geo = layout(cap, cv.clientWidth, cv.clientHeight); layoutKey = key; shown = Math.min(shown, target); }
    cancelAnimationFrame(anim);
    if (reduce) { shown = target; paint(shown, P.col); return; }
    (function step() {
      shown += (target - shown) * .28; if (Math.abs(target - shown) < .6) shown = target;
      paint(Math.round(shown), P.col);
      if (shown !== target) anim = requestAnimationFrame(step);
    })();
  }
  if (range) showPlan();
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { drawRoom(true); });
})();
/* WHY WE EXIST: the statement lights word by word as it's read; the rose at the centre is built from the four
   parts' glass; thin lead lines carry its light out to every feature, a slow pulse at a time. */
(function () {
  'use strict';
  var sec = document.getElementById('mission');
  if (!sec) return;
  var NS = 'http://www.w3.org/2000/svg', reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  function el(n, a, p) { var e = document.createElementNS(NS, n); for (var k in a) e.setAttribute(k, a[k]); if (p) p.appendChild(e); return e; }

  /* ---------- the statement, lit as it's read ---------- */
  var say = document.getElementById('msn-say'), read = document.getElementById('msn-read'), units = [];
  (function split(node) {
    Array.prototype.slice.call(node.childNodes).forEach(function (n) {
      if (n.nodeType === 3) {
        var parts = n.textContent.split(/(\s+)/), frag = document.createDocumentFragment();
        parts.forEach(function (w) { if (!w) return; if (/^\s+$/.test(w)) { frag.appendChild(document.createTextNode(w)); return; } var s = document.createElement('span'); s.className = 'u'; s.textContent = w; frag.appendChild(s); });
        n.parentNode.replaceChild(frag, n);
      } else if (n.nodeType === 1 && n.classList.contains('kw')) n.classList.add('u');
      else if (n.nodeType === 1) split(n);
    });
  })(say);
  units = Array.prototype.slice.call(read.querySelectorAll('.msn-say .u'));
  Array.prototype.slice.call(read.querySelectorAll('.vp')).forEach(function (v) { v.classList.add('u'); units.push(v); });
  var ticking = false;
  function light() {
    ticking = false;
    var r = read.getBoundingClientRect(), vh = window.innerHeight || 800;
    if (!r.height) return;
    var start = vh * .86, end = vh * .5, p = (start - r.top) / (r.height + start - end);
    var n = Math.round(Math.max(0, Math.min(1, p)) * units.length * 1.05);
    for (var i = 0; i < units.length; i++) units[i].classList.toggle('lit', i < n);
  }
  if (!reduce) {
    sec.classList.add('armed'); light();
    window.addEventListener('scroll', function () { if (!ticking) { ticking = true; requestAnimationFrame(light); } }, { passive: true });
    window.addEventListener('resize', light);
  }

  /* ---------- the rose: four parts' glass around the mark ---------- */
  var PARTS = [
    { k: 'faith', a0: 180, c: ['#EAB308', '#F6C66B', '#CA8A04'] },
    { k: 'community', a0: 270, c: ['#14B8A6', '#5EEAD4', '#0F9488'] },
    { k: 'stewardship', a0: 0, c: ['#22C55E', '#86EFAC', '#16A34A'] },
    { k: 'serving', a0: 90, c: ['#F97316', '#FDBA74', '#EA580C'] }
  ];
  function pt(r, a) { var t = a * Math.PI / 180; return (r * Math.cos(t)).toFixed(2) + ' ' + (r * Math.sin(t)).toFixed(2); }
  function sector(r0, r1, a0, a1) { return 'M' + pt(r1, a0) + 'A' + r1 + ' ' + r1 + ' 0 0 1 ' + pt(r1, a1) + 'L' + pt(r0, a1) + 'A' + r0 + ' ' + r0 + ' 0 0 0 ' + pt(r0, a0) + 'Z'; }
  var rose = document.getElementById('msn-rose');
  var defs = el('defs', {}, rose);
  var hl = el('radialGradient', { id: 'msnhl', cx: '30%', cy: '25%', r: '80%' }, defs);
  el('stop', { offset: 0, 'stop-color': '#fff', 'stop-opacity': '.38' }, hl); el('stop', { offset: '.55', 'stop-color': '#fff', 'stop-opacity': '.04' }, hl); el('stop', { offset: 1, 'stop-color': '#fff', 'stop-opacity': '0' }, hl);
  var mg = el('linearGradient', { id: 'msnmk', x1: 0, y1: 0, x2: 1, y2: 1 }, defs);
  el('stop', { offset: 0, 'stop-color': '#E040FB' }, mg); el('stop', { offset: '.55', 'stop-color': '#7C5CFF' }, mg); el('stop', { offset: 1, 'stop-color': '#22D3EE' }, mg);
  el('circle', { r: 127, fill: '#0A0B10', stroke: '#2A2E3A', 'stroke-width': 5 }, rose);
  PARTS.forEach(function (p) {
    var g = el('g', { class: 'pc ' + p.k }, rose), a = p.a0;
    // outer ring: three pieces; inner ring: two
    [[a + 2, a + 30], [a + 30, a + 60], [a + 60, a + 88]].forEach(function (s, i) { el('path', { d: sector(80, 121, s[0], s[1]), fill: p.c[i === 1 ? 1 : i === 0 ? 0 : 2], 'fill-opacity': i === 1 ? .95 : .85, stroke: '#06070A', 'stroke-width': 3, 'stroke-linejoin': 'round' }, g); });
    [[a + 3, a + 45], [a + 45, a + 87]].forEach(function (s, i) { el('path', { d: sector(44, 80, s[0], s[1]), fill: p.c[i ? 0 : 2], 'fill-opacity': .78, stroke: '#06070A', 'stroke-width': 3, 'stroke-linejoin': 'round' }, g); });
    // a small round jewel where the rings meet
    el('circle', { cx: pt(80, a + 45).split(' ')[0], cy: pt(80, a + 45).split(' ')[1], r: 6.5, fill: p.c[1], stroke: '#06070A', 'stroke-width': 2.5 }, g);
  });
  el('circle', { r: 121, fill: 'url(#msnhl)', style: 'mix-blend-mode:screen;pointer-events:none' }, rose);
  el('circle', { r: 40, fill: '#0A0B10', stroke: 'url(#msnmk)', 'stroke-width': 2.5 }, rose);
  var mk = el('svg', { x: -24, y: -21, width: 48, height: 42, viewBox: '8 36 496 424' }, rose), mkg = el('g', { fill: 'url(#msnmk)', stroke: '#fff', 'stroke-width': 14 }, mk);
  ['18,46 175,232 237,231 133,98 376,99 356,131 412,167 494,49', '205,138 338,241 232,391 274,449 435,221 319,137', '264,274 149,279 201,359'].forEach(function (pts) { el('polygon', { points: pts }, mkg); });

  /* ---------- the lead lines: from the rose out to every feature ---------- */
  var map = document.getElementById('msn-map'), svg = document.getElementById('msn-lines');
  function draw() {
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    if (getComputedStyle(svg).display === 'none') return;
    var mr = map.getBoundingClientRect(); if (!mr.width) return;
    svg.setAttribute('viewBox', '0 0 ' + mr.width + ' ' + mr.height);
    var rr = rose.getBoundingClientRect(), cx = rr.left - mr.left + rr.width / 2, cy = rr.top - mr.top + rr.height / 2, R = rr.width / 2 * (124 / 130);
    var n = 0;
    map.querySelectorAll('.msn-grp').forEach(function (grp) {
      var k = grp.getAttribute('data-p'), left = grp.classList.contains('left'), col = getComputedStyle(grp).getPropertyValue('--c').trim();
      grp.querySelectorAll('li').forEach(function (li) {
        var b = li.getBoundingClientRect(), ex = (left ? b.right + 6 : b.left - 6) - mr.left, ey = b.top - mr.top + b.height / 2;
        var ang = Math.atan2(ey - cy, ex - cx), sx = cx + R * Math.cos(ang), sy = cy + R * Math.sin(ang);
        var dx = ex - sx, d = 'M' + sx.toFixed(1) + ' ' + sy.toFixed(1) + 'C' + (sx + Math.cos(ang) * 40).toFixed(1) + ' ' + (sy + Math.sin(ang) * 40).toFixed(1) + ' ' + (ex - dx * .45).toFixed(1) + ' ' + ey.toFixed(1) + ' ' + ex.toFixed(1) + ' ' + ey.toFixed(1);
        el('path', { d: d, class: 'ln ' + k, style: '--c:' + col }, svg);
        if (!reduce && n % 2 === 0) {
          var pl = el('path', { d: d, class: 'pl ' + k }, svg), L = Math.ceil(pl.getTotalLength());
          pl.setAttribute('style', '--c:' + col + ';stroke-dasharray:18 ' + (L * 2) + ';stroke-dashoffset:' + (L * 2 + 18));
          // the offset runs from the full pattern down to 0: the light leaves the rose, travels out, then rests two lengths
          pl.animate([{ strokeDashoffset: L * 2 + 18 }, { strokeDashoffset: 0 }], { duration: (8 + (n % 5)) * 1000, iterations: Infinity, delay: -((n * 1700) % 9000) });
        }
        n++;
      });
    });
  }
  map.querySelectorAll('.msn-grp').forEach(function (g) {
    var k = g.getAttribute('data-p');
    g.addEventListener('mouseenter', function () { map.setAttribute('data-hot', k); });
    g.addEventListener('mouseleave', function () { map.removeAttribute('data-hot'); });
    g.tabIndex = 0;
    g.addEventListener('focus', function () { map.setAttribute('data-hot', k); });
    g.addEventListener('blur', function () { map.removeAttribute('data-hot'); });
  });
  var rt; function redraw() { clearTimeout(rt); rt = setTimeout(draw, 80); }
  if ('ResizeObserver' in window) new ResizeObserver(redraw).observe(map); else window.addEventListener('resize', redraw);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(redraw);
  redraw();
  // rest the pulses while the map is off screen
  if ('IntersectionObserver' in window) new IntersectionObserver(function (es) {
    var on = es[0].isIntersecting; sec.classList.toggle('still', !on);
    svg.querySelectorAll('.pl').forEach(function (p) { p.getAnimations().forEach(function (a) { if (on) a.play(); else a.pause(); }); });
  }).observe(map);
})();

/* ===== Hero, take three: the intro plays once, the hold loops; the window is the map of the rooms ===== */
(function () {
  'use strict';
  var reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  var phone = function () { return innerWidth <= 760; };
  var intro = document.getElementById('hxIntro'), hold = document.getElementById('hxHold');
  var kind = phone() ? 'square' : 'wide', size = phone() ? 720 : (innerWidth * (devicePixelRatio || 1) > 1500 ? 1920 : 1280);
  var base = '/assets/home/hero3-' + kind + '-';
  hold.poster = base + 'poster.jpg';
  hold.src = base + 'hold-' + size + '.mp4';
  function play(v) { var p = v.play(); if (p && p.catch) p.catch(function () {}); }
  var still = document.getElementById('slStill'), stillIn = document.getElementById('slStillIn');
  function fit() {
    if (!still || !still.clientWidth) return;
    if (innerWidth <= 560) { stillIn.style.transform = 'scale(' + (still.clientWidth / 330) + ') translateX(-362px)'; return; }
    stillIn.style.transform = 'scale(' + (still.clientWidth / 700) + ')';
  }
  fit(); addEventListener('resize', fit);
  var objs = [].slice.call(document.querySelectorAll('#hxDevices .hx-rv')), notes = [].slice.call(document.querySelectorAll('#hxDevices .sl-notes li')), tiles = document.querySelector('#hxDevices .sl-tiles');
  function arrive(now) {
    var at = now ? [0, 0, 0] : [0, 300, 700];
    objs.forEach(function (o, i) { setTimeout(function () { o.classList.add('on'); }, at[i] || 0); });
    notes.forEach(function (li, i) { setTimeout(function () { li.classList.add('on'); }, now ? 0 : 1100 + i * 420); });
    if (tiles) setTimeout(function () { tiles.classList.add('on'); }, now ? 0 : 2400);
  }
  if (reduce) { intro.remove(); intro = null; arrive(true); }
  else {
    intro.src = base + 'intro-' + size + '.mp4';
    hold.load();
    var started = false;
    intro.addEventListener('ended', function () { hold.currentTime = 0; play(hold); requestAnimationFrame(function () { intro.style.opacity = '0'; }); });
    intro.addEventListener('playing', function () { if (started) return; started = true; setTimeout(function () { arrive(false); }, 2600); });
    // if the intro can't play (autoplay refused, slow network), show the held window and the devices anyway
    setTimeout(function () { if (!started) { intro.style.opacity = '0'; play(hold); arrive(true); started = true; } }, 4500);
    play(intro);
  }
  if ('IntersectionObserver' in window && !reduce) new IntersectionObserver(function (e) {
    if (intro && !intro.ended && intro.style.opacity !== '0') return;
    if (e[0].isIntersecting) play(hold); else hold.pause();
  }).observe(hold);

  /* ── the map: each petal of the window is a room. The words in the sentence name them, in the same order. ── */
  var ROOMS = [['People and care', 'people-and-care', '#14B8A6'], ['Kids', 'kids-and-youth', '#F97316'], ['Giving', 'giving', '#22C55E'], ['Groups', 'groups-and-classes', '#3B82F6'],
    ['Member app', 'member-app', '#EC4899'], ['Website', 'website-and-sermons', '#EAB308'], ['Office', 'office-and-books', '#94A3B8'], ['Chief', '', '#7C5CFF']];
  // the camera the window was filmed with (src/OneLight/heroLoop.ts, frameHeroIntro), so the petals land exactly
  var CAM = kind === 'wide' ? { look: [-0.27, -0.06, -1], tan: 0.45, asp: 16 / 9 } : { look: [0, -0.085, -1], tan: 0.43, asp: 1 };
  var Ri = 0.335, RH = 0.17, TIP = 0.72, TH = Math.PI / 4;
  function nrm(v) { var l = Math.hypot(v[0], v[1], v[2]); return [v[0] / l, v[1] / l, v[2] / l]; }
  function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
  function cross(a, b) { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
  var f0 = nrm(CAM.look), rt = nrm(cross(f0, [0, 1, 0])), u0 = cross(rt, f0);
  function petalR(p) { return RH + (TIP - RH) * Math.pow(Math.max(0, 1 - Math.pow(Math.abs(p), 1.3)), 0.72); }
  function polar(k, p, r) { var a = Math.PI / 2 - k * TH - p * TH / 2; return [Math.cos(a) * r, Math.sin(a) * r]; }
  function proj(X, Y) { var d = [X * Ri, Y * Ri, -1], z = dot(d, f0); return [0.5 + dot(d, rt) / (z * CAM.tan * CAM.asp) * 0.5, 0.5 - dot(d, u0) / (z * CAM.tan) * 0.5]; }
  var media = document.querySelector('.hx-media'), NS = 'http://www.w3.org/2000/svg';
  var map = document.createElementNS(NS, 'svg'); map.setAttribute('class', 'hx-map'); map.setAttribute('aria-hidden', 'true');
  // a soft dark pool behind each name, so the serif reads on yellow and grey glass as well as on blue
  map.innerHTML = '<defs><filter id="hxPool" x="-40%" y="-80%" width="180%" height="260%"><feMorphology in="SourceAlpha" operator="dilate" radius="2.5" result="d"/>' +
    '<feGaussianBlur in="d" stdDeviation="5.5" result="b"/><feFlood flood-color="#06070A" flood-opacity=".78"/><feComposite in2="b" operator="in" result="sh"/>' +
    '<feMerge><feMergeNode in="sh"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>';
  media.appendChild(map);
  var keys = [].slice.call(document.querySelectorAll('.hx-sub .rk')), petals = [];
  ROOMS.forEach(function (r, k) {
    var a = document.createElementNS(NS, 'a'); a.setAttribute('href', r[1] ? '/churches/' + r[1] : '#chief'); a.setAttribute('tabindex', '-1');
    a.style.setProperty('--c', r[2]);
    var p = document.createElementNS(NS, 'path'), t = document.createElementNS(NS, 'text'); t.setAttribute('text-anchor', 'middle'); t.setAttribute('dominant-baseline', 'central'); t.textContent = r[0];
    a.appendChild(p); a.appendChild(t); map.appendChild(a); petals.push(a);
    a.addEventListener('mouseenter', function () { hover = k; }); a.addEventListener('mouseleave', function () { hover = -1; });
  });
  keys.forEach(function (el, k) {
    el.addEventListener('mouseenter', function () { hover = k; }); el.addEventListener('mouseleave', function () { hover = -1; });
    el.addEventListener('focus', function () { hover = k; }); el.addEventListener('blur', function () { hover = -1; });
  });
  function draw() {
    var W = media.clientWidth, H = media.clientHeight; if (!W || !H) return;
    var A = CAM.asp, dw, dh; if (W / H > A) { dw = W; dh = W / A; } else { dh = H; dw = H * A; }
    var pos = (getComputedStyle(hold).objectPosition || '50% 50%').split(' ').map(function (s) { return parseFloat(s) / 100; });
    var ox = (W - dw) * (isNaN(pos[0]) ? 0.5 : pos[0]), oy = (H - dh) * (isNaN(pos[1]) ? 0.5 : pos[1]);
    function pt(X, Y) { var s = proj(X, Y); return [ox + s[0] * dw, oy + s[1] * dh]; }
    map.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    petals.forEach(function (a, k) {
      var d = '', i, q;
      for (i = 0; i <= 40; i++) { var ph = -1 + i / 20; q = polar(k, ph, petalR(ph)); q = pt(q[0], q[1]); d += (i ? 'L' : 'M') + q[0].toFixed(1) + ' ' + q[1].toFixed(1); }
      for (i = 1; i < 8; i++) { q = polar(k, 1 - i / 4, RH); q = pt(q[0], q[1]); d += 'L' + q[0].toFixed(1) + ' ' + q[1].toFixed(1); }
      a.firstChild.setAttribute('d', d + 'Z');
      q = polar(k, 0, (RH + TIP) / 2 + 0.06); q = pt(q[0], q[1]);
      a.lastChild.setAttribute('x', q[0].toFixed(1)); a.lastChild.setAttribute('y', q[1].toFixed(1));
    });
  }
  draw(); addEventListener('resize', draw);
  // the light walks the petals: as it crosses one, its name lights in the sentence. For the first two
  // trips round the window, the name also shows on the glass; after that the light walks quietly.
  var hover = -1, last = '', laps = 0, prevK = -1, NAMED_LAPS = 2;
  function sm(x) { x = Math.max(0, Math.min(1, x)); return x * x * x * (x * (x * 6 - 15) + 10); }
  function tick() {
    var k = -1, glass = -1;
    if (intro && intro.style.opacity !== '0' && !intro.paused) { var u = 8 * sm((intro.currentTime - 1.0) / 2.4); k = u > 0 && u < 8 ? Math.floor(u) : -1; }
    else if (!hold.paused && hold.currentTime > 0) {
      k = Math.floor(8 * ((hold.currentTime % 16) / 16)) % 8;
      if (prevK === 7 && k === 0) laps++;
      prevK = k;
      if (laps < NAMED_LAPS) glass = k;
    }
    var show = hover >= 0 ? hover : k, key = show + '|' + hover + '|' + glass;
    if (key !== last) {
      last = key;
      keys.forEach(function (el, i) { el.classList.toggle('lit', i === show); });
      petals.forEach(function (a, i) { a.classList.toggle('on', hover >= 0 && i === hover); a.classList.toggle('named', hover < 0 && i === glass); });
    }
    if (heroOn) requestAnimationFrame(tick); else ticking = false;
  }
  // the walk only runs while the window is on screen (the browser already rests it in a hidden tab)
  var heroOn = true, ticking = false;
  function startTick() { if (!ticking) { ticking = true; requestAnimationFrame(tick); } }
  if (!reduce) {
    startTick();
    if ('IntersectionObserver' in window) new IntersectionObserver(function (e) { heroOn = e[0].isIntersecting; if (heroOn) startTick(); }).observe(media);
  }
  else keys.forEach(function (el, k) { el.addEventListener('mouseenter', function () { petals[k].classList.add('on'); }); el.addEventListener('mouseleave', function () { petals[k].classList.remove('on'); }); });

  var lb = document.getElementById('hxLb'), film = document.getElementById('hxFilm'), x = document.getElementById('hxX');
  function open() { film.src = '/assets/home/church-film.mp4'; lb.hidden = false; document.body.style.overflow = 'hidden'; play(film); x.focus(); }
  function close() { film.pause(); lb.hidden = true; document.body.style.overflow = ''; }
  [].forEach.call(document.querySelectorAll('[data-film]'), function (b) { b.addEventListener('click', open); });
  x.addEventListener('click', close);
  lb.addEventListener('click', function (e) { if (e.target === lb) close(); });
  addEventListener('keydown', function (e) { if (e.key === 'Escape' && !lb.hidden) close(); });
  var menu = document.getElementById('lvMenu');
  if (menu) menu.addEventListener('click', function (e) { if (e.target.closest('a')) menu.open = false; });
})();

/* ===== The rooms tour: the window is the map. A pane or a tab opens its room; it walks on by itself until you choose ===== */
(function () {
  'use strict';
  var sec = document.getElementById('products'); if (!sec || !sec.classList.contains('tour')) return;
  var ROOMS = JSON.parse(document.getElementById('tourData').textContent);
  var reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  var tabs = [].slice.call(sec.querySelectorAll('.tour-tab')), panels = [].slice.call(sec.querySelectorAll('.tour-panel')), shots = [].slice.call(sec.querySelectorAll('.tour-shot'));
  var stage = document.getElementById('tourStage'), rose = document.getElementById('tourRose'), NS = 'http://www.w3.org/2000/svg';

  /* the window, flat: the same petal shape as the hero's glass (src/OneLight/window.ts), in the rooms' colours */
  var RH = 0.17, TIP = 0.72, TH = Math.PI / 4;
  function petalR(p) { return RH + (TIP - RH) * Math.pow(Math.max(0, 1 - Math.pow(Math.abs(p), 1.3)), 0.72); }
  function polar(k, p, r) { var a = Math.PI / 2 - k * TH - p * TH / 2; return [Math.cos(a) * r, -Math.sin(a) * r]; }
  function f(n) { return n.toFixed(4); }
  function petalPath(k) {
    var d = '', i, q;
    for (i = 0; i <= 40; i++) { var ph = -1 + i / 20; q = polar(k, ph, petalR(ph)); d += (i ? 'L' : 'M') + f(q[0]) + ' ' + f(q[1]); }
    for (i = 1; i < 8; i++) { q = polar(k, 1 - i / 4, RH); d += 'L' + f(q[0]) + ' ' + f(q[1]); }
    return d + 'Z';
  }
  var svg = '<defs><filter id="tourGlow" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur in="SourceGraphic" stdDeviation=".05" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>' +
    '<radialGradient id="tourHub"><stop offset="0" stop-color="#FFF4D6"/><stop offset=".55" stop-color="#F3C77A"/><stop offset="1" stop-color="#B07A26"/></radialGradient>' +
    '<radialGradient id="tourSp"><stop offset=".2" stop-color="#0F1536"/><stop offset="1" stop-color="#17113A"/></radialGradient>';
  ROOMS.forEach(function (r, k) {
    var a = polar(k, 0, RH), b = polar(k, 0, TIP);
    svg += '<linearGradient id="tourP' + k + '" gradientUnits="userSpaceOnUse" x1="' + f(a[0]) + '" y1="' + f(a[1]) + '" x2="' + f(b[0]) + '" y2="' + f(b[1]) + '">' +
      '<stop offset="0" stop-color="' + r.t[0] + '"/><stop offset=".55" stop-color="' + r.t[1] + '"/><stop offset="1" stop-color="' + r.t[2] + '"/></linearGradient>';
  });
  svg += '</defs>';
  // the frame: the outer ring of small panes, then the deep glass the petals sit in
  svg += '<circle r="1" fill="#0B0C12" stroke="rgba(255,255,255,.16)" stroke-width=".014"/>';
  for (var j = 0; j < 24; j++) {
    var a0 = j / 24 * Math.PI * 2, a1 = (j + 1) / 24 * Math.PI * 2, r0 = 0.8, r1 = 0.95;
    var p = function (a, r) { return f(Math.cos(a) * r) + ' ' + f(Math.sin(a) * r); };
    svg += '<path d="M' + p(a0, r0) + 'L' + p(a0, r1) + 'A' + r1 + ' ' + r1 + ' 0 0 1 ' + p(a1, r1) + 'L' + p(a1, r0) + 'A' + r0 + ' ' + r0 + ' 0 0 0 ' + p(a0, r0) + 'Z" fill="' + ROOMS[(j * 3) % 8].c + '" fill-opacity=".22" stroke="rgba(255,255,255,.16)" stroke-width=".01"/>';
  }
  svg += '<circle r=".79" fill="url(#tourSp)" stroke="rgba(255,255,255,.2)" stroke-width=".012"/>';
  ROOMS.forEach(function (r, k) {
    var d = petalPath(k), c = polar(k, 0, RH + 0.02), t = polar(k, 0, TIP - 0.03), m1 = polar(k, -0.55, 0.42), m2 = polar(k, 0.55, 0.42);
    svg += '<g class="pt" data-k="' + k + '"><path d="' + d + '" fill="url(#tourP' + k + ')"/>' +
      '<path class="vein" d="M' + f(c[0]) + ' ' + f(c[1]) + 'L' + f(t[0]) + ' ' + f(t[1]) + 'M' + f(m1[0]) + ' ' + f(m1[1]) + 'L' + f(t[0] * 0.78) + ' ' + f(t[1] * 0.78) + 'L' + f(m2[0]) + ' ' + f(m2[1]) + '"/>' +
      '<path class="lead" d="' + d + '"/></g>';
  });
  svg += '<circle r=".17" fill="url(#tourHub)" stroke="rgba(255,255,255,.5)" stroke-width=".012"/>';
  for (var h = 0; h < 8; h++) { var e = polar(h, 1, 0.17); svg += '<path class="vein" d="M0 0L' + f(e[0]) + ' ' + f(e[1]) + '" style="stroke:rgba(120,80,20,.35)"/>'; }
  svg += '<circle r=".05" fill="#FFF8E6"/>';
  rose.innerHTML = svg;
  var pts = [].slice.call(rose.querySelectorAll('.pt'));
  // each pane names its room on hover (made here, so the page's markup carries one title only)
  pts.forEach(function (p, k) { var t = document.createElementNS(NS, 'title'); t.textContent = ROOMS[k].tab; p.insertBefore(t, p.firstChild); });

  var cur = 0, DUR = 7000, timer = null, chosen = false, inView = false, hover = false, started = false;
  function show(i, fromUser) {
    cur = (i + ROOMS.length) % ROOMS.length;
    tabs.forEach(function (t, n) { var on = n === cur; t.classList.toggle('on', on); t.setAttribute('aria-selected', on ? 'true' : 'false'); t.tabIndex = on ? 0 : -1; });
    panels.forEach(function (p, n) { var on = n === cur; p.classList.toggle('on', on); if (on) p.removeAttribute('inert'); else p.setAttribute('inert', ''); });
    shots.forEach(function (s, n) { s.classList.toggle('on', n === cur); });
    pts.forEach(function (p, n) { p.classList.toggle('on', n === cur); });
    sec.style.setProperty('--tc', ROOMS[cur].c);
    if (fromUser) { chosen = true; stop(); }
    else restartBar();
    // on phones the names scroll sideways: keep the room that's showing in view (the strip only, never the page)
    var strip = tabs[0].parentNode;
    if (strip.scrollWidth > strip.clientWidth + 4 && started) {
      var pad = parseFloat(getComputedStyle(strip).paddingLeft) || 0, tr = tabs[cur].getBoundingClientRect(), sr = strip.getBoundingClientRect();
      strip.scrollTo({ left: strip.scrollLeft + tr.left - sr.left - pad, behavior: reduce ? 'auto' : 'smooth' });
    }
    started = true;
    // fetch the next room's screen early, so the crossfade never waits on the network
    var nx = shots[(cur + 1) % shots.length].querySelector('img'); if (nx && nx.loading === 'lazy') nx.loading = 'eager';
  }
  function restartBar() { var b = tabs[cur].querySelector('.tour-bar'); b.style.animation = 'none'; void b.offsetWidth; b.style.animation = ''; }
  var narrow = window.matchMedia ? matchMedia('(max-width: 760px)') : { matches: false };
  function playing() { return !reduce && !narrow.matches && !chosen && inView && !hover && !document.hidden; }
  function tick() { timer = null; if (playing()) { show(cur + 1); schedule(); } }
  function schedule() { clearTimeout(timer); timer = playing() ? setTimeout(tick, DUR) : null; sec.classList.toggle('playing', !reduce && !narrow.matches && !chosen); sec.classList.toggle('paused', !playing()); }
  function stop() { clearTimeout(timer); timer = null; sec.classList.remove('playing'); sec.classList.remove('paused'); }
  sec.style.setProperty('--dur', DUR + 'ms');

  tabs.forEach(function (t, n) {
    t.addEventListener('click', function () { show(n, true); });
    t.addEventListener('keydown', function (e) {
      var to = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? cur + 1 : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? cur - 1 : e.key === 'Home' ? 0 : e.key === 'End' ? ROOMS.length - 1 : null;
      if (to === null) return; e.preventDefault(); show(to, true); tabs[cur].focus();
    });
  });
  pts.forEach(function (p, n) { p.addEventListener('click', function () { show(n, true); }); });
  [stage, sec.querySelector('.tour-tabs')].forEach(function (el) {
    el.addEventListener('mouseenter', function () { hover = true; schedule(); });
    el.addEventListener('mouseleave', function () { hover = false; schedule(); });
  });
  sec.addEventListener('focusin', function () { if (!chosen) { hover = true; schedule(); } });
  sec.addEventListener('focusout', function () { hover = false; schedule(); });
  document.addEventListener('visibilitychange', schedule);
  if ('IntersectionObserver' in window) new IntersectionObserver(function (es) { inView = es[0].isIntersecting; schedule(); }, { threshold: 0.45 }).observe(stage);
  show(0); schedule();
})();

/* ===== The week in seven windows: it walks the days by itself until someone opens one ===== */
(function () {
  'use strict';
  var sec = document.getElementById('week'); if (!sec || !sec.classList.contains('lw')) return;
  var reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  var narrow = window.matchMedia ? matchMedia('(max-width: 900px)') : { matches: false };
  var panes = [].slice.call(sec.querySelectorAll('.lwp')), tabs = panes.map(function (p) { return p.querySelector('.lwp-tab'); }), list = sec.querySelector('.lw-row');
  var cur = 0, DUR = 7000, timer = null, chosen = false, inView = false, hover = false;
  sec.style.setProperty('--dur', DUR + 'ms');
  function show(i, user) {
    cur = (i + panes.length) % panes.length;
    panes.forEach(function (p, n) {
      var on = n === cur, panel = p.querySelector('.lwp-panel');
      p.classList.toggle('on', on); tabs[n].setAttribute('aria-selected', on ? 'true' : 'false'); tabs[n].tabIndex = on ? 0 : -1;
      if (on) panel.removeAttribute('inert'); else panel.setAttribute('inert', '');
    });
    if (user) { chosen = true; clearTimeout(timer); timer = null; sec.classList.remove('playing', 'paused'); }
    else { var b = panes[cur].querySelector('.lwp-bar'); b.style.animation = 'none'; void b.offsetWidth; b.style.animation = ''; }
  }
  function playing() { return !reduce && !narrow.matches && !chosen && inView && !hover && !document.hidden; }
  function schedule() {
    clearTimeout(timer); timer = playing() ? setTimeout(function () { timer = null; if (playing()) { show(cur + 1); schedule(); } }, DUR) : null;
    sec.classList.toggle('playing', !reduce && !narrow.matches && !chosen); sec.classList.toggle('paused', !playing());
  }
  tabs.forEach(function (t, n) {
    t.addEventListener('click', function () { if (n !== cur || !chosen) show(n, true); });
    t.addEventListener('keydown', function (e) {
      var to = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? cur + 1 : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? cur - 1 : e.key === 'Home' ? 0 : e.key === 'End' ? panes.length - 1 : null;
      if (to === null) return; e.preventDefault(); show(to, true); tabs[cur].focus();
    });
  });
  list.addEventListener('mouseenter', function () { hover = true; schedule(); });
  list.addEventListener('mouseleave', function () { hover = false; schedule(); });
  sec.addEventListener('focusin', function () { hover = true; schedule(); });
  sec.addEventListener('focusout', function () { hover = false; schedule(); });
  document.addEventListener('visibilitychange', schedule);
  if ('IntersectionObserver' in window) new IntersectionObserver(function (es) { inView = es[0].isIntersecting; schedule(); }, { threshold: 0.4 }).observe(list);
  show(0); schedule();
})();
