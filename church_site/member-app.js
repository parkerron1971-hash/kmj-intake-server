/* member-app.js: the Member App room's scenes, on the lit rooms kit (lit.js). */
(function () {
  var L = window.Lit; if (!L) return;

  /* the hero: a 6-digit code, no password, and Home */
  var hero = document.getElementById('maHero');
  if (hero) {
    var boxes = hero.querySelectorAll('.ma-code span'), steps = [[0, function () { hero.classList.add('door'); boxes.forEach(function (b) { b.classList.remove('f'); }); }]];
    boxes.forEach(function (b, i) { steps.push([900 + i * 260, function () { b.classList.add('f'); }]); });
    steps.push([3000, function () { hero.classList.remove('door'); }]);
    L.loop(hero, steps, 9000);
  }

  /* news: an Important post drops in, members answer, the group's note waits for morning */
  var news = document.getElementById('maNews');
  if (news) {
    var rx = news.querySelectorAll('[data-rx]');
    var set = function (el, n) { el.textContent = el.textContent.replace(/\d+$/, n); };
    L.loop(news, [
      [0, function () { news.classList.add('hush'); rx.forEach(function (el) { set(el, el.getAttribute('data-n')); el.classList.remove('bump'); }); }],
      [700, function () { news.classList.remove('hush'); }],
      [1900, function () { var el = rx[0]; set(el, +el.getAttribute('data-n') + 1); el.classList.add('bump'); }],
      [2800, function () { var el = rx[1]; set(el, +el.getAttribute('data-n') + 1); el.classList.add('bump'); }],
      [3800, function () { rx.forEach(function (el) { el.classList.remove('bump'); }); }]
    ], 8000);
  }

  /* the Bible: a verse marked in yellow, the actions under it */
  var bib = document.getElementById('maBible');
  if (bib) L.loop(bib, [[0, function () { bib.classList.remove('marked'); }], [800, function () { bib.classList.add('marked'); }]], 7000);

  /* live: the chat keeps moving; a prayer goes to the pastor, never into it */
  var live = document.getElementById('maLive');
  if (live) {
    var chat = live.querySelector('#maChat'), scr = live.querySelector('.lit-screen'), here = live.querySelector('[data-to]');
    var more = [['SK', 'Sarah K.', 'Morning from the back row!'], ['JO', 'James O.', 'Amen!'], ['TL', 'The Lees', 'Kids are singing along at home'],
                ['DR', 'Denise R.', 'Ephesians 3:16, write that one down'], ['MT', 'Marcus T.', 'So good to be here this morning']];
    var k = 0;
    var say = function () {
      var m = more[k++ % more.length], li = document.createElement('li'), b = document.createElement('b'), s = document.createElement('span'), st = document.createElement('strong');
      b.className = 'i'; b.textContent = m[0]; st.textContent = m[1]; s.appendChild(st); s.appendChild(document.createTextNode(m[2]));
      li.appendChild(b); li.appendChild(s); chat.appendChild(li);
      while (chat.children.length > 5) chat.removeChild(chat.firstElementChild);
    };
    L.loop(live, [
      [0, function () { live.classList.remove('prayed'); L.reset(here); }],
      [600, function () { L.count(here, 600); say(); }],
      [2000, say],
      [3200, function () { L.tap(scr, live.querySelector('[data-t="pray"]')); }],
      [3600, function () { live.classList.add('prayed'); }],
      [4800, say],
      [6600, say]
    ], 9000);
  }

  /* youth and kids: one phone, three spaces */
  var sp = document.getElementById('maSpaces');
  if (sp) {
    var cap = document.getElementById('maCap');
    var caps = { 1: 'Church: a leader switches spaces', 2: 'Youth: its own colour, its own tabs', 3: "Kids: a parent's Sunday pass" };
    var show = function (n) { sp.setAttribute('data-s', n); cap.textContent = caps[n]; };
    L.loop(sp, [[0, function () { show(1); }], [3000, function () { show(2); }], [6000, function () { show(3); }]], 9000);
  }
})();
