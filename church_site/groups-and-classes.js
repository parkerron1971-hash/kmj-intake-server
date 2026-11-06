/* groups-and-classes.js: the Groups and Classes room's scenes, on the lit rooms kit (lit.js). */
(function () {
  var L = window.Lit; if (!L) return;
  var tapLoop = function (box, sel, period) {
    if (!box) return;
    var scr = box.querySelector('.lit-screen');
    L.loop(box, [[1600, function () { L.tap(scr, box.querySelector(sel)); }]], period || 6000);
  };

  /* the hero: "I'm here" in the app, one more on the office's Groups page */
  var hero = document.getElementById('gxHero');
  if (hero) {
    var n = hero.querySelector('[data-to]'), scr = hero.querySelector('.lit-screen');
    L.loop(hero, [
      [0, function () { hero.classList.remove('arrived'); L.reset(n); }],
      [1800, function () { L.tap(scr, hero.querySelector('[data-t="here"]')); hero.classList.add('arrived'); L.count(n, 500); }]
    ], 7000);
  }

  /* the chat: every message checked before anyone sees it */
  var st = document.getElementById('gxChatSt');
  if (st) {
    var chat = document.getElementById('gxChat');
    var more = [['JO', 'James O.', 'Running late, save me a seat!'], ['', '', 'Bringing extra chairs too'], ['TL', 'The Lees', 'Thank you for praying. Surgery is at 8.'], ['DR', 'Denise R.', 'Kids are welcome, we have a sitter downstairs']];
    var k = 0;
    var say = function () {
      var m = more[k++ % more.length], li = document.createElement('li'), b = document.createElement('span');
      b.className = 'b';
      if (m[0]) {
        var av = document.createElement('span'), st2 = document.createElement('strong');
        av.className = 'gx-av'; av.textContent = m[0]; st2.textContent = m[1]; b.appendChild(st2); li.appendChild(av);
      } else li.className = 'me';
      b.appendChild(document.createTextNode(m[2])); li.appendChild(b); chat.appendChild(li);
      while (chat.children.length > 5) chat.removeChild(chat.firstElementChild);
    };
    L.loop(st, [[900, function () { st.classList.add('typing'); }], [2300, function () { st.classList.remove('typing'); say(); }]], 5000);
  }

  /* the prayer wall: "I'm praying", and the asker hears once a day */
  var wall = document.getElementById('gxWall');
  if (wall) {
    var c = wall.querySelector('[data-to]'), ws = wall.querySelector('.lit-screen');
    L.loop(wall, [
      [0, function () { L.reset(c); }],
      [1500, function () { L.tap(ws, wall.querySelector('[data-t="pray"]')); L.count(c, 400); }]
    ], 6500);
  }

  tapLoop(document.getElementById('gxMeet'), '[data-t="here"]', 6500);
  tapLoop(document.getElementById('gxClasses'), '[data-t="join"]', 6500);
})();
