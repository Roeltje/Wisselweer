(function () {
  'use strict';
  // Optioneel contactadres uit contact.json op de server (niet in git).
  // Zonder geldig bestand blijft de fallback-tekst in de pagina staan.
  var EMAIL = /^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$/;

  function show(cfg) {
    if (!cfg || typeof cfg.email !== 'string') return;
    var email = cfg.email.trim();
    if (email.length > 254 || !EMAIL.test(email)) return;
    var target = document.getElementById('privacy-contact');
    if (!target) return;
    var a = document.createElement('a');
    a.href = 'mailto:' + email;
    a.textContent = email;
    while (target.firstChild) target.removeChild(target.firstChild);
    target.appendChild(a);
  }

  try {
    fetch('/contact.json', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(show)
      .catch(function () {});
  } catch (e) { /* geen fetch beschikbaar: negeren */ }
})();
