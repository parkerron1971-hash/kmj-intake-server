/* ===== Sunday Light: the window, its light, the still life ===== */

(function () {
  'use strict';
  if (!document.getElementById('hero-v3')) return;
  var NS = 'http://www.w3.org/2000/svg', reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  function el(n, a, p) { var e = document.createElementNS(NS, n); for (var k in a) e.setAttribute(k, a[k]); if (p) p.appendChild(e); return e; }
  function rng(s) { return function () { s |= 0; s = s + 0x6D2B79F5 | 0; var t = Math.imul(s ^ s >>> 15, 1 | s); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
  /* ---------- the window: a tall lancet with two lights and a rose, leaded quarry glass at sunrise ---------- */
  function lancet(x0, x1, ys, yb, r) { var h = (x1 - x0) / 2, ax = (x0 + x1) / 2, ay = ys - Math.sqrt(r * r - (r - h) * (r - h)); return { d: 'M' + x0 + ',' + yb + ' L' + x0 + ',' + ys + ' A' + r + ',' + r + ' 0 0 1 ' + ax + ',' + ay + ' A' + r + ',' + r + ' 0 0 1 ' + x1 + ',' + ys + ' L' + x1 + ',' + yb + ' Z', ay: ay }; }
  var OUT = lancet(14, 586, 420, 1100, 430), L = lancet(52, 292, 560, 1100, 250), R = lancet(308, 548, 560, 1100, 250);
  var ROSE = { cx: 300, cy: 232, r: 118 };
  // dawn palette, top to bottom: violet night, rose, gold sun low in the glass
  var SKY = ['#3B1A7A', '#5B21B6', '#7C5CFF', '#6D28D9', '#3B82F6', '#22D3EE', '#14B8A6', '#EC4899', '#F472B6', '#F97316', '#F6C66B', '#FDE68A'];
  function build(svg, bloom) {
    var R0 = rng(31), defs = el('defs', {}, svg), id = bloom ? 'slb' : 'slg';
    [['o', OUT], ['l', L], ['r', R]].forEach(function (c) { var cp = el('clipPath', { id: id + c[0] }, defs); el('path', { d: c[1].d }, cp); });
    var lg = el('linearGradient', { id: id + 'mk', x1: 0, y1: 0, x2: 1, y2: 1 }, defs); el('stop', { offset: 0, 'stop-color': '#E040FB' }, lg); el('stop', { offset: .55, 'stop-color': '#7C5CFF' }, lg); el('stop', { offset: 1, 'stop-color': '#22D3EE' }, lg);
    el('path', { d: OUT.d, fill: '#0C0B14' }, svg);
    // the head around the rose: small deep panes
    var head = el('g', { 'clip-path': 'url(#' + id + 'o)' }, svg);
    for (var y = 0; y < 600; y += 34) for (var x = 0; x < 600; x += 34) {
      var p = (y / 600) * 4 + R0() * 3, c = SKY[Math.min(SKY.length - 1, Math.floor(p))];
      el('rect', { x: x + (y / 34 % 2) * 17, y: y, width: 33, height: 33, fill: c, stroke: '#0A0B10', 'stroke-width': bloom ? 0 : 3, transform: 'rotate(45 ' + (x + 17) + ' ' + (y + 17) + ')', class: 'pane' }, head);
    }
    // the two lights: diamond quarries, night at the top and sun at the bottom
    [['l', L], ['r', R]].forEach(function (c, side) {
      var g = el('g', { 'clip-path': 'url(#' + id + c[0] + ')' }, svg);
      for (var yy = 300; yy < 1110; yy += 44) for (var xx = 0; xx < 620; xx += 52) {
        var off = ((yy - 300) / 44) % 2 ? 26 : 0, cx = xx + off, cy = yy;
        var t = (yy - 300) / 800, idx = Math.floor(t * (SKY.length - 1) + (R0() - .5) * 2.4);
        var col = SKY[Math.max(0, Math.min(SKY.length - 1, idx))];
        if (R0() < .07) col = '#FFF4DC';
        el('polygon', { points: cx + ',' + (cy - 26) + ' ' + (cx + 26) + ',' + cy + ' ' + cx + ',' + (cy + 26) + ' ' + (cx - 26) + ',' + cy, fill: col, stroke: '#0A0B10', 'stroke-width': bloom ? 0 : 3.2, class: 'pane', 'data-i': side }, g);
      }
      // a light streak down each light, where the sun is brightest
      var sg = el('linearGradient', { id: id + 'st' + side, x1: 0, y1: 0, x2: 0, y2: 1 }, defs);
      el('stop', { offset: 0, 'stop-color': '#fff', 'stop-opacity': 0 }, sg); el('stop', { offset: .7, 'stop-color': '#FFF1D2', 'stop-opacity': .42 }, sg); el('stop', { offset: 1, 'stop-color': '#FFF1D2', 'stop-opacity': .7 }, sg);
      el('rect', { x: 0, y: 300, width: 600, height: 800, fill: 'url(#' + id + 'st' + side + ')', style: 'mix-blend-mode:screen' }, g);
    });
    // the rose: seven petals around the mark
    var rose = el('g', {}, svg), ROOM = ['#14B8A6', '#22C55E', '#F97316', '#3B82F6', '#EC4899', '#EAB308', '#94A3B8'];
    el('circle', { cx: ROSE.cx, cy: ROSE.cy, r: ROSE.r + 6, fill: '#0A0B10' }, rose);
    ROOM.forEach(function (c, i) {
      var a0 = (-90 + (i - .5) * 360 / 7 + 2) * Math.PI / 180, a1 = (-90 + (i + .5) * 360 / 7 - 2) * Math.PI / 180, ri = 34, ro = ROSE.r - 4;
      function P(r, a) { return (ROSE.cx + r * Math.cos(a)).toFixed(1) + ',' + (ROSE.cy + r * Math.sin(a)).toFixed(1); }
      el('path', { d: 'M' + P(ri, a0) + ' L' + P(ro, a0) + ' A' + ro + ',' + ro + ' 0 0 1 ' + P(ro, a1) + ' L' + P(ri, a1) + ' A' + ri + ',' + ri + ' 0 0 0 ' + P(ri, a0) + ' Z', fill: c, stroke: '#0A0B10', 'stroke-width': bloom ? 0 : 3.4 }, rose);
      var am = (a0 + a1) / 2; el('circle', { cx: ROSE.cx + 82 * Math.cos(am), cy: ROSE.cy + 82 * Math.sin(am), r: 11, fill: '#FFF4DC', opacity: .85, stroke: '#0A0B10', 'stroke-width': bloom ? 0 : 3 }, rose);
    });
    el('circle', { cx: ROSE.cx, cy: ROSE.cy, r: 32, fill: '#0A0B10', stroke: 'url(#' + id + 'mk)', 'stroke-width': 2.5 }, rose);
    var mk = el('svg', { x: ROSE.cx - 24, y: ROSE.cy - 21, width: 48, height: 42, viewBox: '8 36 496 424' }, rose), mg = el('g', { fill: 'url(#' + id + 'mk)', stroke: '#fff', 'stroke-width': 14 }, mk);
    ['18,46 175,232 237,231 133,98 376,99 356,131 412,167 494,49', '205,138 338,241 232,391 274,449 435,221 319,137', '264,274 149,279 201,359'].forEach(function (pp) { el('polygon', { points: pp }, mg); });
    if (bloom) return;
    // the stone tracery
    var st = el('g', { fill: 'none', stroke: '#14131C', 'stroke-linejoin': 'round' }, svg);
    el('path', { d: L.d, 'stroke-width': 13 }, st); el('path', { d: R.d, 'stroke-width': 13 }, st);
    el('rect', { x: 292, y: 560, width: 16, height: 560, fill: '#14131C', stroke: 'none' }, st);
    el('circle', { cx: ROSE.cx, cy: ROSE.cy, r: ROSE.r + 3, 'stroke-width': 12 }, st);
    el('path', { d: OUT.d, 'stroke-width': 26 }, st);
    el('path', { d: OUT.d, 'stroke-width': 1.5, stroke: 'rgba(255,230,190,.35)' }, st);
    el('path', { d: L.d, 'stroke-width': 1.2, stroke: 'rgba(255,230,190,.25)' }, st); el('path', { d: R.d, 'stroke-width': 1.2, stroke: 'rgba(255,230,190,.25)' }, st);
  }
  build(document.getElementById('slWinBloom'), true);
  build(document.getElementById('slWinGlass'), false);

  var hero = document.getElementById('hero-v3'), box = document.getElementById('slLight'), win = document.getElementById('slWin');
  function shown() { return true; }

  /* ---------- the still life scales as one piece ---------- */
  var still = document.getElementById('slStill'), stillIn = document.getElementById('slStillIn');
  function fitStill() {
    if (!still.clientWidth) return;
    if (window.innerWidth <= 560) { var kp = still.clientWidth / 330; stillIn.style.transform = 'scale(' + kp + ') translateX(-362px)'; return; }
    var k = still.clientWidth / 700; stillIn.style.transform = 'scale(' + k + ')';
  }

  /* ---------- sunlight: the window's own shape, cast in parallel down and to the left ---------- */
  var shafts = document.getElementById('slShafts'), glassSVG = document.getElementById('slWinGlass'), glassImg = null;
  function loadGlass(cb) {
    var xml = new XMLSerializer().serializeToString(glassSVG);
    if (xml.indexOf('xmlns="http://www.w3.org/2000/svg"') < 0) xml = xml.replace('<svg', '<svg xmlns="http://www.w3.org/2000/svg"');
    xml = xml.replace('<svg', '<svg width="600" height="1100"');
    var img = new Image(); img.onload = function () { glassImg = img; cb(); }; img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(xml);
  }
  var light = { x: 0, y: 0 };
  function drawShafts() {
    if (!glassImg || !shown()) return;
    var hr = box.getBoundingClientRect();
    if (hr.width < 2 || hr.height < 2) return;
    var wr = win.getBoundingClientRect(), S = .5;
    var W = Math.round(hr.width * S), H = Math.round(hr.height * S);
    shafts.width = W; shafts.height = H;
    // 1. the window as the sun sees it: its glass washed toward warm white, faded where the window fades
    var src = document.createElement('canvas'); src.width = W; src.height = H; var s = src.getContext('2d');
    var x = (wr.left - hr.left) * S, y = (wr.top - hr.top) * S, w = wr.width * S, h = wr.height * S;
    s.drawImage(glassImg, x, y, w, h);
    s.globalCompositeOperation = 'source-atop'; s.fillStyle = 'rgba(255,236,204,.55)'; s.fillRect(0, 0, W, H);
    s.globalCompositeOperation = 'destination-in';
    var fade = s.createLinearGradient(x + w, 0, x, 0); fade.addColorStop(0, 'rgba(0,0,0,1)'); fade.addColorStop(.55, 'rgba(0,0,0,.9)'); fade.addColorStop(1, 'rgba(0,0,0,.25)');
    s.fillStyle = fade; s.fillRect(0, 0, W, H);
    // 2. soften it, so the shafts carry the window's shape without its fine detail
    var soft = document.createElement('canvas'); soft.width = W; soft.height = H; var o = soft.getContext('2d');
    try { o.filter = 'blur(3px)'; } catch (e) { /* fine without */ }
    o.drawImage(src, 0, 0); o.filter = 'none';
    // 3. cast it: many faint copies along the light's direction, fading as they go
    var g = shafts.getContext('2d'); g.clearRect(0, 0, W, H); g.globalCompositeOperation = 'lighter';
    var dir = [-.79, .61], N = 96, step = Math.hypot(W, H) * 1.05 / N, power = hr.width < 600 ? .28 : hr.width < 1100 ? .7 : 1;
    for (var k = 1; k <= N; k++) { var t = k / N; g.globalAlpha = .11 * power * Math.pow(1 - t, 1.35); g.drawImage(soft, dir[0] * step * k, dir[1] * step * k); }
    // 4. a few finer streaks inside the light, the way dust shows it
    var r = rng(11); g.globalAlpha = 1; g.globalCompositeOperation = 'lighter';
    for (var i = 0; i < 22; i++) {
      var sx = x + w * (.25 + r() * .6), sy = y + h * (.1 + r() * .75), len = (300 + r() * 600) * S, wid = (1 + r() * 4) * S;
      var lg = g.createLinearGradient(sx, sy, sx + dir[0] * len, sy + dir[1] * len); lg.addColorStop(0, 'rgba(255,236,206,' + (.04 + r() * .05).toFixed(3) + ')'); lg.addColorStop(1, 'rgba(255,236,206,0)');
      g.strokeStyle = lg; g.lineWidth = wid; g.beginPath(); g.moveTo(sx, sy); g.lineTo(sx + dir[0] * len, sy + dir[1] * len); g.stroke();
    }
    // 5. where the light lands: the window's colours stretched across the floor
    g.globalCompositeOperation = 'lighter'; g.globalAlpha = .1;
    try { g.filter = 'blur(' + Math.round(10 * S * 2) + 'px)'; } catch (e) { /* fine without */ }
    g.setTransform(.75, 0, -1.25, .26, x + w * .08 - W * .18, H * .7); g.drawImage(src, 0, -y * .4); g.setTransform(1, 0, 0, 1, 0, 0); g.filter = 'none'; g.globalAlpha = 1;
    light.x = (x + w * .5) / S; light.y = (y + h * .3) / S;
  }

  /* ---------- a little dust in the light, on computers ---------- */
  var cv = document.getElementById('slMotes'), mc = cv.getContext('2d'), dots = [], MW = 0, MH = 0, dpr = 1, running = false;
  function sizeMotes() { dpr = Math.min(2, window.devicePixelRatio || 1); MW = box.clientWidth; MH = box.clientHeight; cv.width = MW * dpr; cv.height = MH * dpr; dots = []; var n = MW < 700 ? 0 : 30; for (var i = 0; i < n; i++) dots.push(spawn()); }
  function spawn() { var d = Math.random() * MW * .9, side = (Math.random() - .5) * 260; return { x: light.x - .79 * d + .61 * side, y: light.y + .61 * d + .79 * side, r: .5 + Math.random() * 1.2, vx: -.03 - Math.random() * .04, vy: .01 + Math.random() * .03, ph: Math.random() * 6.3, life: 600 + Math.random() * 900 }; }
  function frame(t) {
    if (!running) return;
    mc.setTransform(dpr, 0, 0, dpr, 0, 0); mc.clearRect(0, 0, MW, MH);
    for (var i = 0; i < dots.length; i++) { var m = dots[i]; m.x += m.vx; m.y += m.vy; m.life--; if (m.life < 0 || m.x < 0 || m.y > MH) { dots[i] = spawn(); continue; } var al = .16 + .14 * Math.sin(t / 2600 + m.ph); mc.beginPath(); mc.arc(m.x, m.y, m.r, 0, 6.283); mc.fillStyle = 'rgba(255,238,205,' + al.toFixed(3) + ')'; mc.fill(); }
    requestAnimationFrame(frame);
  }
  if (!reduce && 'IntersectionObserver' in window) new IntersectionObserver(function (es) { var was = running; running = es[0].isIntersecting && shown(); if (running && !was) requestAnimationFrame(frame); }).observe(hero);

  window.addEventListener('pointermove', function (e) { if (!shown()) return; var r = box.getBoundingClientRect(); if (e.clientY > r.bottom) return; hero.style.setProperty('--slx', ((e.clientX - r.left) / r.width - .5).toFixed(3)); hero.style.setProperty('--sly', ((e.clientY - r.top) / r.height - .5).toFixed(3)); }, { passive: true });

  function hdr() { var h = document.querySelector('#top > header'); if (h) hero.style.setProperty('--slhdr', h.offsetHeight + 'px'); }
  function layout() { if (!shown()) return; hdr(); fitStill(); drawShafts(); sizeMotes(); }
  var rt; window.addEventListener('resize', function () { clearTimeout(rt); rt = setTimeout(layout, 140); });
  fitStill();
  loadGlass(function () { layout(); if (document.fonts && document.fonts.ready) document.fonts.ready.then(layout); });

  /* ---------- the sunrise ---------- */
  function sunrise() { hero.classList.add('sl-dawn'); void hero.offsetWidth; setTimeout(function () { hero.classList.remove('sl-dawn'); }, reduce ? 0 : 160); }
  if (shown()) sunrise();

})();

/* The church overview: the closing window, the move and the size picker. */
(function () {
  'use strict';
  var NS = 'http://www.w3.org/2000/svg';
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  var ROOMS = {
    people: { name: 'People and Care', line: 'Every family has a shepherd', slug: 'people-and-care', t: ['#5EEAD4', '#14B8A6', '#0F766E'] },
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
      go.hidden = false; go.textContent = 'Start free on ' + P.short;
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

/* A WEEK AT CHURCH: one office app screen per day, tagged with the part of church life it served.
   Moves on by itself every seven seconds until someone taps a day; rests when it's off screen. */
(function () {
  'use strict';
  var sec = document.getElementById('week');
  if (!sec) return;
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  var P = {
    faith: ['Faith', '#EAB308', '#A16207'],
    community: ['Community', '#14B8A6', '#0F766E'],
    serving: ['Serving', '#F97316', '#C2410C'],
    stewardship: ['Stewardship', '#22C55E', '#15803D'],
    all: ['All together', '#7C5CFF', '#5B3FE0']
  };
  // rail colours, as on the hero's tablet: this week, people, groups, giving, kids and serving, member app, website, books
  var RAIL = ['#7C5CFF', '#14B8A6', '#3B82F6', '#22C55E', '#F97316', '#EC4899', '#EAB308', '#94A3B8'];

  function row(av, c, name, sub, chip, kind, sq) {
    return '<div class="wk-row"><span class="wk-av' + (sq ? ' sq' : '') + '" style="background:' + c + '">' + av + '</span><span class="wk-tx"><b>' + name + '</b><small>' + sub + '</small></span>' +
      (chip ? '<em class="wk-chip ' + kind + '">' + chip + '</em>' : '<i></i>') + '</div>';
  }
  function tiles(list) {
    return '<div class="wk-tiles" style="--n:' + list.length + '">' + list.map(function (t) {
      return '<div style="--c:' + t[3] + '"><small>' + t[0] + '</small><b>' + t[1] + '</b><span>' + t[2] + '</span></div>';
    }).join('') + '</div>';
  }

  var DAYS = [
    { d: 'Mon', date: 'Monday, November 9', p: 'community', rail: 1, t: 'Every guest has a person', h: 'First-time guests from Sunday',
      chief: '<b>6 guests</b> filled out cards on Sunday. Each one is with someone from the welcome team.',
      body: '<div class="wk-rows">' +
        row('JP', '#5EEAD4', 'Jordan and Alexis Price', 'Family of four · with Denise R.', 'Text sent', 'ok') +
        row('AH', '#99F6E4', 'Andre Hill', 'With Paul O.', 'Coffee Thursday', 'go') +
        row('TN', '#2DD4BF', 'The Nguyen family', 'Two kids in Little Lambs · with Denise R.', 'Text sent', 'ok') +
        row('BC', '#5EEAD4', 'Bri Carter', 'With Sam T.', 'Note ready', 'wait') +
        row('LO', '#99F6E4', 'Luis Ortega', 'With Paul O.', 'Text sent', 'ok') + '</div>' },
    { d: 'Tue', date: 'Tuesday, November 10', p: 'community', rail: 1, t: 'No family is forgotten', h: 'Care this week',
      chief: '<b>3 families</b> have missed three Sundays. Their shepherds each have a note ready.',
      body: '<div class="wk-rows">' +
        row('RF', '#5EEAD4', 'The Reyes family', 'Missed 3 Sundays · shepherd Angela W.', 'Note ready', 'wait') +
        row('RE', '#99F6E4', 'Raymond Ellis', 'Missed 3 Sundays · shepherd Tony M.', 'Called', 'ok') +
        row('OF', '#2DD4BF', 'The Okafor family', 'Missed 4 Sundays · shepherd Angela W.', 'Note ready', 'wait') +
        row('&#10022;', '#F4C04E', '4 new prayer requests', 'With the intercessors', 'Praying', 'go') + '</div>' },
    { d: 'Wed', date: 'Wednesday, November 11', p: 'faith', rail: 2, t: "Sunday's message keeps going", h: "This week's group study",
      chief: "This week's study is drawn from <b>Sunday's message on Romans 8</b>. It's posted in all 12 groups.",
      body: '<div class="wk-study"><small>Romans 8 · four questions</small><b>No condemnation</b><ol><li>What does &ldquo;no condemnation&rdquo; change about how you see this week?</li><li>Where do you still live like the verdict is out?</li></ol></div>' +
        '<div class="wk-rows">' +
        row('TW', '#93C5FD', 'Tuesday Women', '14 members · meets tonight', 'Posted', 'ok', true) +
        row('YA', '#60A5FA', 'Young Adults', '22 members · Thursday', 'Posted', 'ok', true) +
        row('+9', '#BFDBFE', '9 more groups', 'Each with the study and its prayer wall', 'Posted', 'ok', true) + '</div>' },
    { d: 'Thu', date: 'Thursday, November 12', p: 'serving', rail: 4, t: 'Every team is ready to serve', h: "Sunday's serving teams",
      chief: 'Every team is full for Sunday except <b>parking</b>, which has one spot open.',
      body: '<div class="wk-rows">' +
        row('6/6', '#FDBA74', 'Welcome team', 'Doors, greeters and the guest table', 'Full', 'ok', true) +
        row('8/8', '#FB923C', 'Kids', 'Background checks current for all eight', 'Full', 'ok', true) +
        row('5/5', '#FDBA74', 'Worship', 'Set list shared Tuesday', 'Full', 'ok', true) +
        row('3/4', '#FED7AA', 'Parking', 'One spot open on the Serve tab', '1 open', 'wait', true) + '</div>' },
    { d: 'Fri', date: 'Friday, November 13', p: 'stewardship', rail: 3, t: 'Giving, counted and matched', h: 'Giving this week',
      chief: '<b>$4,820</b> came in this week on your own Stripe. It matches Friday\'s deposit, and the books are current.',
      body: tiles([['General', '$3,640', '58 gifts', '#4ADE80'], ['Missions', '$780', '19 gifts', '#86EFAC'], ['Building', '$400', '7 gifts', '#BBF7D0']]) +
        '<div class="wk-rows">' +
        row('$', '#4ADE80', "Friday's deposit", '$4,820 · every gift accounted for', 'Matched', 'ok', true) +
        row('2', '#CBD5E1', 'Bills paid', 'Electric and the copier lease', 'Booked', 'ok', true) + '</div>' },
    { d: 'Sat', date: 'Saturday, November 14', p: 'faith', rail: 5, t: 'Tomorrow is ready', h: 'Ready for Sunday',
      chief: "Tomorrow's announcements are scheduled, the sermon notes are up, and the stream is set for <b>11:00</b>.",
      body: '<div class="wk-rows">' +
        row('&#9788;', '#F9A8D4', "Today's devotional", 'Sent by text and in the app · 142 opened', 'Sent', 'ok', true) +
        row('&#9993;', '#F472B6', 'Announcements', 'To every phone · Sunday 8:00 AM', 'Scheduled', 'go', true) +
        row('&#10070;', '#FDE68A', 'Sermon notes', 'Romans 8:18&ndash;30 · under Watch', 'Ready', 'ok', true) +
        row('&#9654;', '#F9A8D4', 'Live stream', 'The app and the website · 11:00 AM', 'Set', 'ok', true) + '</div>' },
    { d: 'Sun', date: 'Sunday, November 15', p: 'all', rail: 0, t: 'The church gathers', h: 'Good morning, Pastor James',
      chief: 'Everything is set for 11:00. <b>The welcome team</b> has the guest cards, and the kids rooms are staffed.',
      body: tiles([['Here', '214', 'checked in', '#A78BFA'], ['Kids', '38', 'pickup codes printed', '#FDBA74'], ['Online', '86', 'watching live', '#F9A8D4']]) +
        '<div class="wk-rows">' +
        row('&#10022;', '#F4C04E', '4 prayer requests', 'With the intercessors', 'New', 'go') +
        row('6', '#5EEAD4', 'Guest cards', 'On Monday\'s list for the welcome team', 'Saved', 'ok', true) + '</div>' }
  ];

  var list = document.getElementById('wk-days'), scr = document.getElementById('wk-scr'), cap = document.getElementById('wk-cap');
  var mark = '<svg viewBox="8 36 496 424" aria-hidden="true"><defs><linearGradient id="wkmk" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#E040FB"/><stop offset=".55" stop-color="#7C5CFF"/><stop offset="1" stop-color="#22D3EE"/></linearGradient></defs><g fill="url(#wkmk)" stroke="#fff" stroke-width="10"><polygon points="18,46 175,232 237,231 133,98 376,99 356,131 412,167 494,49"/><polygon points="205,138 338,241 232,391 274,449 435,221 319,137"/><polygon points="264,274 149,279 201,359"/></g></svg>';
  scr.innerHTML = '<div class="wk-rail">' + mark + RAIL.map(function (c) { return '<i style="--c:' + c + '"></i>'; }).join('') + '</div><div class="wk-main" id="wk-main"></div>';
  var main = document.getElementById('wk-main'), dots = scr.querySelectorAll('.wk-rail i');

  var buttons = DAYS.map(function (day, i) {
    var p = P[day.p], li = document.createElement('li'), b = document.createElement('button');
    b.type = 'button'; b.setAttribute('role', 'tab'); b.id = 'wk-tab-' + i; b.setAttribute('aria-controls', 'wk-scr');
    b.style.setProperty('--c', p[1]); b.style.setProperty('--d', p[2]);
    b.innerHTML = '<span class="d">' + day.d + '</span><span class="t">' + day.t + '</span><span class="p">' + p[0] + '</span>';
    b.setAttribute('aria-label', day.date.split(',')[0] + ': ' + day.t + '. ' + p[0] + '.');
    li.appendChild(b); list.appendChild(li); return b;
  });

  var active = -1, auto = !reduce;
  function show(i, user) {
    if (user) { auto = false; buttons.forEach(function (b) { b.classList.remove('run'); }); }
    active = i; var day = DAYS[i], p = P[day.p];
    buttons.forEach(function (b, k) { var on = k === i; b.setAttribute('aria-selected', String(on)); b.tabIndex = on ? 0 : -1; b.classList.remove('run'); });
    if (auto) { void buttons[i].offsetWidth; buttons[i].classList.add('run'); }
    scr.setAttribute('aria-labelledby', buttons[i].id);
    for (var k = 0; k < dots.length; k++) dots[k].classList.toggle('on', k === day.rail);
    cap.style.setProperty('--c', p[1]); cap.style.setProperty('--d', p[2]);
    cap.innerHTML = day.t + ' <span class="p">' + p[0] + '</span>';
    main.classList.remove('in'); void main.offsetWidth;
    main.innerHTML = '<div class="wk-top"><span class="s"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#8D93A1" stroke-width="2.4" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>Search people, groups, gifts</span><span>Grace Fellowship</span></div>' +
      '<div class="wk-date">' + day.date + '</div><div class="wk-h">' + day.h + '</div>' +
      '<div class="wk-chief"><span class="o" aria-hidden="true"></span><span>' + day.chief + '</span></div>' + day.body;
    if (!reduce) main.classList.add('in');
  }
  buttons.forEach(function (b, i) {
    b.addEventListener('click', function () { show(i, true); });
    b.addEventListener('animationend', function () { if (auto && i === active) show((i + 1) % DAYS.length, false); });
    b.addEventListener('keydown', function (e) {
      var k = e.key === 'ArrowDown' || e.key === 'ArrowRight' ? 1 : e.key === 'ArrowUp' || e.key === 'ArrowLeft' ? -1 : 0;
      if (!k) return; e.preventDefault(); var n = (active + k + DAYS.length) % DAYS.length; show(n, true); buttons[n].focus();
    });
  });
  show(0, false);
  // rest while off screen
  sec.classList.add('paused');
  if ('IntersectionObserver' in window) new IntersectionObserver(function (es) { sec.classList.toggle('paused', !es[0].isIntersecting); }, { threshold: .35 }).observe(sec);
  else sec.classList.remove('paused');
})();
