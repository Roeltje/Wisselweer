(function () {
  'use strict';
  var TZ = 'Europe/Amsterdam';
  var STATUS = {
    KEEP_CURRENT: { cls: 'badge-keep', icon: '✓', label: 'Nog niet wisselen' },
    PREPARE_CHANGE: { cls: 'badge-prepare', icon: '!', label: 'Bereid je voor' },
    CHANGE_RECOMMENDED: { cls: 'badge-change', icon: '→', label: 'Wisselen aanbevolen' },
    REGIONAL_DIFFERENCES: { cls: 'badge-regional', icon: '≈', label: 'Verschilt per regio' },
    INSUFFICIENT_DATA: { cls: 'badge-unknown', icon: '?', label: 'Nog geen advies' }
  };
  var FALLBACK = { cls: 'badge-unknown', icon: '?', label: 'Onbekend' };
  var fmtDay = new Intl.DateTimeFormat('nl-NL', { timeZone: TZ, weekday: 'long', day: 'numeric', month: 'long' });
  var fmtDayShort = new Intl.DateTimeFormat('nl-NL', { timeZone: TZ, day: 'numeric', month: 'long' });
  var fmtDateTime = new Intl.DateTimeFormat('nl-NL', { timeZone: TZ, day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit' });

  function $(id) { return document.getElementById(id); }
  function isStr(v) { return typeof v === 'string' && v.length > 0; }
  function isoDate(s) {
    if (!isStr(s) || !/^\d{4}-\d{2}-\d{2}$/.test(s)) return null;
    var d = new Date(s + 'T12:00:00Z');
    return isNaN(d.getTime()) ? null : d;
  }
  function isoTime(s) {
    if (!isStr(s)) return null;
    var d = new Date(s);
    return isNaN(d.getTime()) ? null : d;
  }
  function valid(a) {
    return a && typeof a === 'object' && a.schema_version === 1 && isStr(a.heading) &&
      isStr(a.status) && isStr(a.summary) && isoTime(a.generated_at) && isoTime(a.stale_after);
  }
  function notice(text, error) {
    var n = $('notice');
    n.textContent = text;
    n.className = 'notice' + (error ? ' error' : '');
    n.hidden = false;
  }
  function unavailable() {
    notice('Het actuele advies is tijdelijk niet beschikbaar.', true);
  }
  function show(id, on) { $(id).hidden = !on; }

  function render(a) {
    var st = Object.prototype.hasOwnProperty.call(STATUS, a.status) ? STATUS[a.status] : FALLBACK;
    $('advice-heading').textContent = a.heading;
    $('status-badge').className = 'badge ' + st.cls;
    $('status-icon').textContent = st.icon;
    $('status-text').textContent = isStr(a.status_label) ? a.status_label : st.label;
    $('summary').textContent = a.summary;

    var rec = null;
    var d = isoDate(a.recommended_date);
    var p = a.recommended_period;
    if (d) {
      rec = fmtDay.format(d);
    } else if (p && typeof p === 'object') {
      var s = isoDate(p.start), e = isoDate(p.end);
      if (s && e) rec = fmtDayShort.format(s) + ' t/m ' + fmtDayShort.format(e);
    }
    if (rec) {
      $('recommended-label').textContent = d ? 'Aanbevolen datum' : 'Aanbevolen periode';
      $('recommended-value').textContent = rec;
    }
    show('recommended', !!rec);

    var list = $('regions');
    list.textContent = '';
    var regions = Array.isArray(a.regions) ? a.regions : [];
    regions.forEach(function (r) {
      if (!r || !isStr(r.name)) return;
      var rs = Object.prototype.hasOwnProperty.call(STATUS, r.status) ? STATUS[r.status] : FALLBACK;
      var li = document.createElement('li');
      var n = document.createElement('span');
      n.textContent = r.name;
      var s2 = document.createElement('span');
      s2.className = 'st';
      s2.textContent = rs.icon + ' ' + rs.label;
      li.appendChild(n);
      li.appendChild(s2);
      list.appendChild(li);
    });
    show('regions-block', list.children.length > 0);

    var gen = isoTime(a.generated_at), stale = isoTime(a.stale_after);
    $('generated').textContent = fmtDateTime.format(gen);
    var fu = isoDate(a.forecast_until);
    if (fu) $('forecast').textContent = fmtDayShort.format(fu);
    show('forecast-row', !!fu);

    var src = a.source;
    if (src && isStr(src.attribution)) {
      $('source-text').textContent = src.attribution + ' · ';
      if (isStr(src.license_url) && /^https:\/\//.test(src.license_url)) {
        $('source-link').href = src.license_url;
      }
      show('source', true);
    }

    show('advice-body', true);
    if (Date.now() > stale.getTime()) {
      notice('Dit advies is verouderd (laatste update ' + fmtDateTime.format(gen) + ').', false);
      $('advice').classList.add('is-stale');
    }
  }

  fetch('advice.json', { cache: 'no-cache' })
    .then(function (r) { if (!r.ok) throw new Error('http'); return r.json(); })
    .then(function (a) { if (valid(a)) render(a); else unavailable(); })
    .catch(unavailable);
})();
