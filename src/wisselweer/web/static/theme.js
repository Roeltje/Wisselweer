// Themakeuze: automatisch (systeem) -> licht -> donker. Wordt onthouden in localStorage.
// Dit script staat zonder defer in <head> zodat het thema voor de eerste weergave staat.
// De labels komen uit data-theme-label-* op <html> (vertaald door de server); Nederlands is de terugval.
(function () {
  "use strict";
  var KEY = "ww-theme";
  var ORDER = ["auto", "light", "dark"];
  var FALLBACK = { auto: "Thema: automatisch", light: "Thema: licht", dark: "Thema: donker" };
  // Constante iconen; er komt nooit invoer van buiten in innerHTML.
  var ICON = {
    auto: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8"/><path d="M12 4v16"/><path d="M12 4a8 8 0 0 1 0 16z" fill="currentColor"/></svg>',
    light: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2.5v2.5M12 19v2.5M2.5 12H5M19 12h2.5M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M5.3 18.7l1.8-1.8M16.9 7.1l1.8-1.8"/></svg>',
    dark: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z"/></svg>'
  };
  var root = document.documentElement;

  function read() {
    try {
      var v = localStorage.getItem(KEY);
      return ORDER.indexOf(v) >= 0 ? v : "auto";
    } catch (e) {
      return "auto";
    }
  }
  function write(v) {
    try {
      localStorage.setItem(KEY, v);
    } catch (e) {
      /* opslag niet beschikbaar: de keuze geldt dan alleen voor deze pagina */
    }
  }
  function apply(v) {
    if (v === "auto") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", v);
  }
  function label(v) {
    return root.getAttribute("data-theme-label-" + v) || FALLBACK[v];
  }

  var current = read();
  apply(current);

  function attach() {
    var row = document.querySelector(".header-row");
    if (!row || document.getElementById("theme-switch")) return;
    var b = document.createElement("button");
    b.type = "button";
    b.id = "theme-switch";
    b.className = "theme-switch";
    function paint() {
      b.innerHTML = ICON[current];
      b.setAttribute("aria-label", label(current));
      b.setAttribute("title", label(current));
    }
    b.addEventListener("click", function () {
      current = ORDER[(ORDER.indexOf(current) + 1) % ORDER.length];
      write(current);
      apply(current);
      paint();
    });
    paint();
    // Voor de uitlogknop als die er is, anders achteraan in de kop.
    var logout = row.querySelector(".logout");
    if (logout) row.insertBefore(b, logout);
    else row.appendChild(b);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", attach);
  else attach();
})();
