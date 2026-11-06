/* kids-and-youth.js: the Kids and Youth room's scenes, on the lit rooms kit (lit.js). */
(function () {
  var L = window.Lit; if (!L) return;

  /* the hero: two children in, the tag prints, the code is texted */
  var hero = document.getElementById('kyHero');
  if (hero) {
    var kids = hero.querySelectorAll('.ky-kid'), desk = hero.querySelector('.ky-desk .in');
    L.loop(hero, [
      [0, function () { hero.classList.add('printing', 'texting'); kids.forEach(function (k) { k.classList.remove('on'); }); }],
      [800, function () { L.tap(desk, kids[0]); kids[0].classList.add('on'); }],
      [1400, function () { L.tap(desk, kids[1]); kids[1].classList.add('on'); }],
      [2100, function () { L.tap(desk, hero.querySelector('.ky-go')); hero.classList.add('press'); }],
      [2350, function () { hero.classList.remove('press', 'printing'); }],
      [3500, function () { hero.classList.remove('texting'); }]
    ], 9000);
  }

  /* the kiosk: a parent types their mobile number */
  var kiosk = document.getElementById('kyKiosk');
  if (kiosk) {
    var num = document.getElementById('kyNum'), keys = kiosk.querySelectorAll('.pad span'), digits = '5550142290';
    var fmt = function (d) { var s = d.slice(0, 3), m = d.slice(3, 6), e = d.slice(6); return d.length > 3 ? '(' + s + ') ' + m + (e ? '-' + e : '') : d; };
    var steps = [[0, function () { num.textContent = ''; }]];
    digits.split('').forEach(function (ch, i) {
      steps.push([600 + i * 280, function () {
        num.textContent = fmt(digits.slice(0, i + 1));
        var key = [].filter.call(keys, function (k) { return k.textContent === ch; })[0];
        if (key) { key.classList.add('hit'); setTimeout(function () { key.classList.remove('hit'); }, 180); }
      }]);
    });
    L.loop(kiosk, steps, 7000);
  }

  /* parents: the code while they're in, what they learned after */
  var par = document.getElementById('kyPar'), km = document.getElementById('kyKmode');
  if (par) L.loop(par, [[0, function () { par.classList.remove('after'); }], [3800, function () { par.classList.add('after'); }]], 8500);
  if (km) L.loop(km, [[0, function () { km.classList.remove('holding'); }], [1200, function () { km.classList.add('holding'); }]], 6500);

  /* youth: the chat keeps moving, two leaders always in it */
  var yo = document.getElementById('kyYouth');
  if (yo) {
    var chat = document.getElementById('kyChat');
    var more = [['', 'DW', 'Devin W.', 'what time does it end'], ['ld', 'MR', 'Marcus R. · Leader', 'About 9:30. Parents pick up at the side door.'],
                ['', 'JW', 'Jayden W.', 'bet'], ['ld', 'AN', 'Ana N. · Leader', 'Pizza is on us this week.']];
    var k = 0;
    var say = function () {
      var m = more[k++ % more.length], li = document.createElement('li'), b = document.createElement('b'), s = document.createElement('span'), st = document.createElement('strong');
      if (m[0]) li.className = m[0];
      b.className = 'i'; b.textContent = m[1]; st.textContent = m[2]; s.appendChild(st); s.appendChild(document.createTextNode(m[3]));
      li.appendChild(b); li.appendChild(s); chat.appendChild(li);
      while (chat.children.length > 5) chat.removeChild(chat.firstElementChild);
    };
    L.loop(yo, [[1500, say], [3500, say], [5500, say], [7500, say]], 8000);
  }

  /* Chief: the Sundays rise once, when they're seen */
  var ch = document.querySelector('.ky-chiefst');
  if (ch && !L.reduce) ch.classList.add('armed');
})();
