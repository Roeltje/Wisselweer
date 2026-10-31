(function () {
  'use strict';
  // Optionele, zelf-gehoste Umami-analytics. Alles komt uit analytics.json op de
  // server (niet in git); zonder dat bestand gebeurt er niets.
  var UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  var NOTE = 'geen cookies; anonieme bezoekersstatistieken via eigen Umami.';

  function load(cfg) {
    if (!cfg || typeof cfg !== 'object') return;
    var url;
    try { url = new URL(cfg.src); } catch (e) { return; }
    if (url.protocol !== 'https:') return;
    if (typeof cfg.websiteId !== 'string' || !UUID.test(cfg.websiteId)) return;
    var s = document.createElement('script');
    s.defer = true;
    s.src = url.href;
    s.setAttribute('data-website-id', cfg.websiteId);
    s.setAttribute('data-do-not-track', 'true');
    if (typeof cfg.domains === 'string' && cfg.domains.length > 0) {
      s.setAttribute('data-domains', cfg.domains);
    }
    document.head.appendChild(s);
    var note = document.getElementById('privacy-note');
    if (note) note.textContent = NOTE;
  }

  try {
    fetch('/analytics.json', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(load)
      .catch(function () {});
  } catch (e) { /* geen fetch beschikbaar: negeren */ }
})();
