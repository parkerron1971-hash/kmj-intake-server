(function () {
  // The ONE place this site's forms are sent from. Every form is marked
  // data-church-form="<kind>" and holds plainly named fields.
  //
  // For now every kind posts to the platform's website contact endpoint,
  // which takes {name, email, phone, message}: the fields it has no slot
  // for are written into the message as "Question: answer" lines. When the
  // church's own endpoint exists, rewire ENDPOINT and toPayload() here; the
  // pages don't change. The recipient is set on the server, never here.
  var ENDPOINT = '{{API_BASE}}/sites/{{BUSINESS_ID}}/contact-submit';

  var TITLES = { 'connect-card': 'Connect card', 'prayer-request': 'Prayer request' };
  var THANKS = {
    'connect-card': 'Thank you. Your connect card is in, and someone from our team will be in touch.',
    'prayer-request': 'Thank you. Your request is with our prayer team, and we are praying with you.'
  };
  var FAILED = 'That didn’t send. Check your connection and try again.';

  function fieldValues(form) {
    var out = {};
    Array.prototype.forEach.call(form.elements, function (el) {
      if (!el.name || el.disabled || el.name === 'website') return;
      if ((el.type === 'checkbox' || el.type === 'radio') && !el.checked) return;
      var v = (el.value || '').trim();
      if (!v) return;
      if (el.type === 'checkbox') (out[el.name] = out[el.name] || []).push(v);
      else out[el.name] = v;
    });
    return out;
  }

  function textOf(node) {
    // A label's words without its "required" marker.
    var copy = node.cloneNode(true);
    Array.prototype.forEach.call(copy.querySelectorAll('.req, input'), function (n) { n.remove(); });
    return copy.textContent.replace(/\s+/g, ' ').trim();
  }

  function question(form, name) {
    // A field's question as the visitor saw it: its group's legend, else its label.
    var el = form.elements[name];
    if (el && !el.tagName) el = el[0];
    if (!el) return name;
    var group = el.closest('fieldset');
    var legend = group && group.querySelector('legend');
    if (legend) return textOf(legend);
    var label = (el.id && form.querySelector('label[for="' + el.id + '"]')) || el.closest('label');
    return label ? textOf(label) : name;
  }

  function toPayload(kind, form, v) {
    var own = { first_name: 1, last_name: 1, email: 1, phone: 1 };
    var lines = [TITLES[kind] || kind];
    Object.keys(v).forEach(function (k) {
      if (own[k]) return;
      lines.push(question(form, k) + ': ' + (Array.isArray(v[k]) ? v[k].join(', ') : v[k]));
    });
    return {
      name: [v.first_name, v.last_name].filter(Boolean).join(' '),
      email: v.email || '',
      phone: v.phone || '',
      message: lines.join('\n'),
      form: kind
    };
  }

  // A link like /connect?interest=next-step#connect-card ticks that box.
  var interest = new URLSearchParams(window.location.search).get('interest');
  if (interest) {
    var box = document.querySelector('[data-interest="' + interest.replace(/[^a-z0-9-]/g, '') + '"]');
    if (box) box.checked = true;
  }

  Array.prototype.forEach.call(document.querySelectorAll('[data-church-form]'), function (form) {
    var kind = form.getAttribute('data-church-form');
    var note = form.querySelector('[data-form-note]');
    var button = form.querySelector('[type="submit"]');
    function say(text, tone) { note.textContent = text; note.className = 'form-note' + (tone ? ' ' + tone : ''); }

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      if (form.elements.website && form.elements.website.value) return; // the hidden field only bots fill in
      button.disabled = true;
      say('Sending…');
      fetch(ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(toPayload(kind, form, fieldValues(form)))
      })
        // Any 2xx means the submission was saved. A body of {ok: false}
        // only says the notification email failed after saving, and
        // showing an error then would just get the form sent twice.
        .then(function (r) {
          if (r.ok) { form.reset(); say(THANKS[kind] || 'Thank you. It’s sent.', 'ok'); }
          else say(r.status === 429 ? 'Too many tries in a minute. Wait a moment and send again.' : FAILED, 'err');
        })
        .catch(function () { say(FAILED, 'err'); })
        .then(function () { button.disabled = false; });
    });
  });
})();
