(function () {
  'use strict';
  // The menu on a phone, and the bar's line once the page moves.
  var nav = document.getElementById('nav');
  function scrolled() { if (nav) { nav.classList.toggle('scrolled', window.scrollY > 8); } }
  scrolled();
  window.addEventListener('scroll', scrolled, { passive: true });
  var menu = document.getElementById('menu');
  var sheet = document.getElementById('sheet');
  if (menu && sheet) {
    menu.addEventListener('click', function () {
      var open = sheet.classList.toggle('open');
      menu.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    sheet.addEventListener('click', function (e) {
      if (e.target.tagName === 'A') { sheet.classList.remove('open'); menu.setAttribute('aria-expanded', 'false'); }
    });
  }

  // The booth you can try. Everything a visitor types goes on the screens as
  // text (textContent), never as markup. Scripture is the KJV, a few passages
  // only; anything else typed is a slide of its own words.
  var BIBLE = {
    'John': { 3: { 16: 'For God so loved the world, that he gave his only begotten Son, that whosoever believeth in him should not perish, but have everlasting life.' } },
    'Psalm': {
      23: {
        1: 'The LORD is my shepherd; I shall not want.',
        2: 'He maketh me to lie down in green pastures: he leadeth me beside the still waters.',
        3: 'He restoreth my soul: he leadeth me in the paths of righteousness for his name’s sake.',
        4: 'Yea, though I walk through the valley of the shadow of death, I will fear no evil: for thou art with me; thy rod and thy staff they comfort me.',
        5: 'Thou preparest a table before me in the presence of mine enemies: thou anointest my head with oil; my cup runneth over.',
        6: 'Surely goodness and mercy shall follow me all the days of my life: and I will dwell in the house of the LORD for ever.'
      },
      46: {
        1: 'God is our refuge and strength, a very present help in trouble.',
        10: 'Be still, and know that I am God: I will be exalted among the heathen, I will be exalted in the earth.'
      },
      100: {
        1: 'Make a joyful noise unto the LORD, all ye lands.',
        2: 'Serve the LORD with gladness: come before his presence with singing.',
        3: 'Know ye that the LORD he is God: it is he that hath made us, and not we ourselves; we are his people, and the sheep of his pasture.',
        4: 'Enter into his gates with thanksgiving, and into his courts with praise: be thankful unto him, and bless his name.',
        5: 'For the LORD is good; his mercy is everlasting; and his truth endureth to all generations.'
      }
    },
    'Proverbs': { 3: { 5: 'Trust in the LORD with all thine heart; and lean not unto thine own understanding.', 6: 'In all thy ways acknowledge him, and he shall direct thy paths.' } },
    'Isaiah': { 40: { 31: 'But they that wait upon the LORD shall renew their strength; they shall mount up with wings as eagles; they shall run, and not be weary; and they shall walk, and not faint.' } },
    'Jeremiah': { 29: { 11: 'For I know the thoughts that I think toward you, saith the LORD, thoughts of peace, and not of evil, to give you an expected end.' } },
    'Matthew': { 5: { 14: 'Ye are the light of the world. A city that is set on an hill cannot be hid.' }, 11: { 28: 'Come unto me, all ye that labour and are heavy laden, and I will give you rest.' } },
    'Romans': { 8: { 28: 'And we know that all things work together for good to them that love God, to them who are the called according to his purpose.' } },
    'Philippians': { 4: { 13: 'I can do all things through Christ which strengtheneth me.' } },
    'Joshua': { 1: { 9: 'Have not I commanded thee? Be strong and of a good courage; be not afraid, neither be thou dismayed: for the LORD thy God is with thee whithersoever thou goest.' } },
    'Lamentations': { 3: { 22: 'It is of the LORD’s mercies that we are not consumed, because his compassions fail not.', 23: 'They are new every morning: great is thy faithfulness.' } },
    'Micah': { 6: { 8: 'He hath shewed thee, O man, what is good; and what doth the LORD require of thee, but to do justly, and to love mercy, and to walk humbly with thy God?' } },
    '1 John': { 4: { 19: 'We love him, because he first loved us.' } }
  };
  var WHOLE = { 'Psalm 23': true, 'Psalm 100': true };
  var BOOKS = (function () {
    var names = ['Genesis', 'Exodus', 'Leviticus', 'Numbers', 'Deuteronomy', 'Joshua', 'Judges', 'Ruth',
      '1 Samuel', '2 Samuel', '1 Kings', '2 Kings', '1 Chronicles', '2 Chronicles', 'Ezra', 'Nehemiah', 'Esther',
      'Job', 'Psalm', 'Proverbs', 'Ecclesiastes', 'Isaiah', 'Jeremiah', 'Lamentations', 'Ezekiel', 'Daniel',
      'Hosea', 'Joel', 'Amos', 'Obadiah', 'Jonah', 'Micah', 'Nahum', 'Habakkuk', 'Zephaniah', 'Haggai',
      'Zechariah', 'Malachi', 'Matthew', 'Mark', 'Luke', 'John', 'Acts', 'Romans', '1 Corinthians',
      '2 Corinthians', 'Galatians', 'Ephesians', 'Philippians', 'Colossians', '1 Thessalonians',
      '2 Thessalonians', '1 Timothy', '2 Timothy', 'Titus', 'Philemon', 'Hebrews', 'James', '1 Peter', '2 Peter',
      '1 John', '2 John', '3 John', 'Jude', 'Revelation'];
    var map = {};
    names.forEach(function (n) { map[n.toLowerCase().replace(/\s/g, '')] = n; });
    var short = {
      gen: 'Genesis', ex: 'Exodus', exod: 'Exodus', lev: 'Leviticus', num: 'Numbers', deut: 'Deuteronomy',
      josh: 'Joshua', judg: 'Judges', '1sam': '1 Samuel', '2sam': '2 Samuel', '1kgs': '1 Kings', '2kgs': '2 Kings',
      '1chr': '1 Chronicles', '2chr': '2 Chronicles', neh: 'Nehemiah', esth: 'Esther', psalms: 'Psalm', ps: 'Psalm',
      psa: 'Psalm', prov: 'Proverbs', pro: 'Proverbs', eccl: 'Ecclesiastes', isa: 'Isaiah', jer: 'Jeremiah',
      lam: 'Lamentations', ezek: 'Ezekiel', dan: 'Daniel', hos: 'Hosea', obad: 'Obadiah', mic: 'Micah',
      nah: 'Nahum', hab: 'Habakkuk', zeph: 'Zephaniah', hag: 'Haggai', zech: 'Zechariah', mal: 'Malachi',
      matt: 'Matthew', mt: 'Matthew', mk: 'Mark', lk: 'Luke', jn: 'John', jhn: 'John', rom: 'Romans',
      '1cor': '1 Corinthians', '2cor': '2 Corinthians', gal: 'Galatians', eph: 'Ephesians', phil: 'Philippians',
      php: 'Philippians', col: 'Colossians', '1thess': '1 Thessalonians', '2thess': '2 Thessalonians',
      '1tim': '1 Timothy', '2tim': '2 Timothy', tit: 'Titus', heb: 'Hebrews', jas: 'James', '1pet': '1 Peter',
      '2pet': '2 Peter', '1jn': '1 John', rev: 'Revelation'
    };
    Object.keys(short).forEach(function (k) { map[k] = short[k]; });
    return map;
  })();
  var LOOKS = { midnight: 'Midnight', sunrise: 'Sunrise', stone: 'Stone', forest: 'Forest' };
  var QUICK = { A: 'Amen', S: 'Please stand', G: 'Give at the welcome table or online' };
  var FIRST_MSG = 'Press Next, or type John 3:16 and press Enter.';

  function firstSlides() {
    var out = [{ label: 'Welcome', text: 'Every service, ready.' }];
    [1, 2, 3, 4, 5].forEach(function (v) {
      out.push({ label: 'Psalm 100:' + v + ' · KJV', text: BIBLE.Psalm[100][v], ref: 'Psalm 100:' + v });
    });
    return out;
  }
  var S = { slides: firstSlides(), idx: 0, live: 0, mode: 'live', look: 'midnight', msg: FIRST_MSG, kind: '',
            stg: 'band', arr: 'main', qk: 'S' };

  function parse(q) {
    var m = q.trim().toLowerCase().replace(/\s+/g, ' ').match(/^((?:[123]\s?)?[a-z]+)\.?\s*(\d+)(?:\s*[:.]\s*(\d+)(?:\s*[-–]\s*(\d+))?)?$/);
    if (!m) { return null; }
    var book = BOOKS[m[1].replace(/\s/g, '')];
    if (!book) { return null; }
    var ch = Number(m[2]);
    var v1 = m[3] ? Number(m[3]) : null;
    var v2 = m[4] ? Number(m[4]) : v1;
    var name = book + ' ' + ch;
    var ref = v1 === null ? name : name + ':' + v1 + (v2 !== v1 ? '-' + v2 : '');
    var chap = (BIBLE[book] || {})[ch];
    if (!chap) { return { error: true, ref: ref }; }
    var verses = [];
    if (v1 === null) {
      if (!WHOLE[name]) { return { error: true, ref: ref }; }
      verses = Object.keys(chap).map(Number).sort(function (a, b) { return a - b; });
    } else {
      if (v2 < v1 || v2 - v1 > 30) { return { error: true, ref: ref }; }
      for (var v = v1; v <= v2; v++) { verses.push(v); }
      if (verses.some(function (x) { return !chap[x]; })) { return { error: true, ref: ref }; }
    }
    return { ref: ref, slides: verses.map(function (x) {
      return { label: book + ' ' + ch + ':' + x + ' · KJV', text: chap[x], ref: book + ' ' + ch + ':' + x };
    }) };
  }

  function add(q) {
    var input = document.getElementById('cs-try');
    var text = String(q != null ? q : (input ? input.value : '')).replace(/\s+/g, ' ').trim().slice(0, 160);
    if (!text) { S.msg = 'Type a verse or a line first.'; S.kind = 'warn'; return render(); }
    var r = parse(text);
    if (r && r.error) {
      S.msg = r.ref + ' isn’t in this demo. Try John 3:16, Psalm 23 or Proverbs 3:5-6. In ChurchSavvy every verse of the KJV and the WEB is there.';
      S.kind = 'warn';
      return render();
    }
    var made = r ? r.slides : [{ label: '', text: text }];
    if (S.slides.length + made.length > 40) {
      S.msg = 'This demo holds 40 slides. A real service holds as many as you need.'; S.kind = 'warn';
      return render();
    }
    var idx = S.slides.length;
    S.slides = S.slides.concat(made);
    S.idx = idx;
    if (S.mode === 'live') { S.live = idx; }
    S.msg = (r ? 'Added ' + r.ref + (made.length > 1 ? ', one verse to a slide.' : '.') : 'Added your slide.') +
      (S.mode === 'live' ? ' It’s on every screen.' : ' You’re rehearsing, so the room still shows slide ' + (S.live + 1) + '.');
    S.kind = 'ok';
    if (input) { input.value = ''; }
    render();
  }

  function go(i) {
    if (i < 0 || i >= S.slides.length) { return; }
    S.idx = i;
    if (S.mode === 'live') { S.live = i; }
    render();
  }

  function size(t) { return t.length <= 24 ? 'z1' : t.length <= 60 ? 'z2' : t.length <= 110 ? 'z3' : 'z4'; }
  function short(t, k) { return t.length > k ? t.slice(0, k - 1).replace(/\s+\S*$/, '') + '…' : t; }
  function clock() {
    var d = new Date();
    var h = d.getHours() % 12 || 12;
    return h + ':' + String(d.getMinutes()).padStart(2, '0');
  }
  function each(sel, fn) { Array.prototype.forEach.call(document.querySelectorAll(sel), fn); }
  function put(key, text) { each('[data-b="' + key + '"]', function (el) { el.textContent = text; }); }
  function sized(el, text) {
    el.textContent = text;
    if (el.hasAttribute('data-size')) { el.className = el.className.replace(/\bz[1-4]\b/g, '').trim() + ' ' + size(text); }
  }
  function press(sel, attr, value) {
    each(sel, function (b) {
      var on = b.getAttribute(attr) === value;
      b.classList.toggle('on', on);
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }

  function render() {
    var n = S.slides.length;
    var cur = S.slides[S.live] || S.slides[0];
    var nxt = S.slides[S.live + 1];
    var pv = S.slides[S.idx] || cur;
    var reh = S.mode === 'rehearse';
    each('[data-b="label"]', function (el) { el.textContent = cur.label || ''; el.hidden = !cur.label; });
    each('[data-b="text"]', function (el) { sized(el, cur.text); });
    put('line', short(cur.text, 64));
    put('stage-now', short(cur.text, 92));
    put('stage-next', nxt ? (nxt.ref || short(nxt.text, 46)) : 'End of the slides');
    put('live-count', (S.live + 1) + ' OF ' + n);
    put('count', (S.idx + 1) + ' / ' + n);
    put('mode-tag', reh ? 'BOOTH REHEARSING' : 'ON SCREEN');
    put('stream-title', cur.ref || 'Sunday service');
    put('stream-text', short(cur.text, 80));
    put('clock', clock());
    each('[data-b="pv-label"]', function (el) { el.textContent = pv.label || ''; el.hidden = !pv.label; });
    each('[data-b="pv-text"]', function (el) { sized(el, pv.text); });
    var frame = S.idx === S.live ? 'onair' : 'prev';
    each('[data-b="pv-frame"], [data-b="pv-tag"]', function (el) {
      el.classList.remove('onair', 'prev');
      el.classList.add(frame);
    });
    put('pv-tag', S.idx === S.live ? 'ON SCREEN' : 'PREVIEW ONLY');
    each('[data-b="msg"]', function (el) {
      el.textContent = S.msg;
      el.classList.remove('ok', 'warn');
      if (S.kind) { el.classList.add(S.kind); }
    });
    each('[data-look-host]', function (el) {
      el.className = el.className.replace(/\blook-\w+\b/, 'look-' + S.look);
    });
    press('[data-look]', 'data-look', S.look);
    press('[data-mode]', 'data-mode', S.mode);
    each('[data-mode="rehearse"]', function (b) { b.classList.toggle('reh', reh); });
    press('[data-stg]', 'data-stg', S.stg);
    each('[data-view]', function (v) { v.hidden = v.getAttribute('data-view') !== S.stg; });
    press('[data-arr]', 'data-arr', S.arr);
    each('[data-full-only]', function (el) { el.hidden = S.arr === 'short'; });
    press('[data-qk]', 'data-qk', S.qk);
    var words = QUICK[S.qk] || '';
    each('[data-b="qk-text"]', function (el) { el.textContent = words; el.hidden = !words; });
    each('[data-b="qk-logo"]', function (el) { el.hidden = S.qk !== 'L'; });
    each('[data-b="qk-scr"]', function (el) {
      el.classList.toggle('black', S.qk === 'B');
      el.classList.toggle('lk-bg', S.qk !== 'B');
    });
  }

  document.addEventListener('click', function (e) {
    var t = e.target.closest ? e.target.closest('[data-look],[data-mode],[data-act],[data-q],[data-arr],[data-stg],[data-qk]') : null;
    if (!t) { return; }
    if (t.hasAttribute('data-look')) {
      S.look = t.getAttribute('data-look');
      S.msg = LOOKS[S.look] + '. The room and the stream take your church’s look; the stage display stays plain for the people up front.';
      S.kind = '';
    } else if (t.hasAttribute('data-mode')) {
      if (t.getAttribute('data-mode') === 'rehearse') {
        S.mode = 'rehearse';
        S.msg = 'Rehearsing. Step through or add slides; the room keeps showing slide ' + (S.live + 1) + ' until you go live.';
        S.kind = '';
      } else {
        S.mode = 'live';
        S.live = S.idx;
        S.msg = 'Live. Slide ' + (S.idx + 1) + ' is on every screen.';
        S.kind = 'ok';
      }
    } else if (t.hasAttribute('data-q')) {
      return add(t.getAttribute('data-q'));
    } else if (t.hasAttribute('data-arr')) {
      S.arr = t.getAttribute('data-arr');
    } else if (t.hasAttribute('data-stg')) {
      S.stg = t.getAttribute('data-stg');
    } else if (t.hasAttribute('data-qk')) {
      S.qk = t.getAttribute('data-qk');
    } else {
      var act = t.getAttribute('data-act');
      if (act === 'show') { return add(); }
      if (act === 'next') { return go(S.idx + 1); }
      if (act === 'back') { return go(S.idx - 1); }
      if (act === 'reset') {
        S.slides = firstSlides(); S.idx = 0; S.live = 0; S.mode = 'live'; S.look = 'midnight';
        S.msg = 'Back to the start. Type a verse or a line, or press Next.'; S.kind = '';
        var input = document.getElementById('cs-try');
        if (input) { input.value = ''; }
      }
    }
    render();
  });
  var field = document.getElementById('cs-try');
  if (field) {
    field.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); add(); }
    });
  }
  render();
  setInterval(function () { put('clock', clock()); }, 10000);
})();
