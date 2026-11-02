// Themakeuze: automatisch (systeem) -> licht -> donker. Wordt onthouden in localStorage.
// Dit script staat zonder defer in <head> zodat het thema voor de eerste weergave staat.
// De labels komen uit data-theme-label-* op <html> (vertaald door de server); Nederlands is de terugval.
(function () {
  "use strict";
  var KEY = "ww-theme";
  var ORDER = ["auto", "light", "dark"];
  var FALLBACK = { auto: "Thema: automatisch", light: "Thema: licht", dark: "Thema: donker" };
  // Constante iconen (drie standen naast elkaar; de actieve staat op een vlakje); er komt nooit
  // invoer van buiten in innerHTML.
  var ICON = {
    auto: '<svg viewBox="0 0 62 30" aria-hidden="true"><rect class="knob" x="23" y="3" width="16" height="24" rx="4"/><circle class="off" cx="10" cy="15" r="3"/><path class="off" d="M10 9.5v1M10 19.5v1M4.5 15h1M14.5 15h1M6.1 11.1l.7.7M13.2 18.2l.7.7M6.1 18.9l.7-.7M13.2 11.8l.7-.7"/><circle class="on" cx="31" cy="15" r="4.5"/><path class="on-fill" d="M31 10.5a4.5 4.5 0 0 1 0 9z"/><path class="off" d="M52.5 10.2a5 5 0 1 0 4.3 7.3 5.6 5.6 0 0 1-4.3-7.3z"/></svg>',
    light: '<svg viewBox="0 0 62 30" aria-hidden="true"><rect class="knob" x="2" y="3" width="16" height="24" rx="4"/><circle class="on" cx="10" cy="15" r="3"/><path class="on" d="M10 9.5v1M10 19.5v1M4.5 15h1M14.5 15h1M6.1 11.1l.7.7M13.2 18.2l.7.7M6.1 18.9l.7-.7M13.2 11.8l.7-.7"/><circle class="off" cx="31" cy="15" r="4.5"/><path class="off-fill" d="M31 10.5a4.5 4.5 0 0 1 0 9z"/><path class="off" d="M52.5 10.2a5 5 0 1 0 4.3 7.3 5.6 5.6 0 0 1-4.3-7.3z"/></svg>',
    dark: '<svg viewBox="0 0 62 30" aria-hidden="true"><rect class="knob" x="44" y="3" width="16" height="24" rx="4"/><circle class="off" cx="10" cy="15" r="3"/><path class="off" d="M10 9.5v1M10 19.5v1M4.5 15h1M14.5 15h1M6.1 11.1l.7.7M13.2 18.2l.7.7M6.1 18.9l.7-.7M13.2 11.8l.7-.7"/><circle class="off" cx="31" cy="15" r="4.5"/><path class="off-fill" d="M31 10.5a4.5 4.5 0 0 1 0 9z"/><path class="on" d="M52.5 10.2a5 5 0 1 0 4.3 7.3 5.6 5.6 0 0 1-4.3-7.3z"/></svg>'
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
  // Seizoen voor de foto's (1 feb t/m 31 jul = zomer, anders winter), zoals op wisselweer.nl.
  var month = new Date().getMonth(); // 0 = januari
  root.setAttribute("data-season", month >= 1 && month <= 6 ? "summer" : "winter");

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
    // In de gereedschapsgroep rechts in de kop, vóór de uitlogknop.
    var tools = row.querySelector(".header-tools") || row;
    var logout = tools.querySelector(".logout");
    if (logout) tools.insertBefore(b, logout);
    else tools.appendChild(b);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", attach);
  else attach();
})();
