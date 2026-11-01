/* Kleine verbeteringen; alle pagina's werken ook zonder JavaScript. */
(function () {
  "use strict";

  // Bevestiging bij formulieren met data-confirm (verwijderen, intrekken).
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (form && form.matches && form.matches("form[data-confirm]")) {
      if (!window.confirm(form.getAttribute("data-confirm"))) {
        event.preventDefault();
      }
    }
  });

  // Banden per groep: zonder JavaScript staan alle extra regels als ingeklapte <details> onder elkaar;
  // met JavaScript tonen we de volgende pas als de vorige is opengeklapt (of zelf al open staat).
  var groupBox = document.querySelector("[data-tire-groups]");
  if (groupBox) {
    var extras = Array.prototype.slice.call(groupBox.querySelectorAll("[data-group-extra]"));
    var syncExtras = function () {
      extras.forEach(function (details, i) {
        details.hidden = !(i === 0 || details.open || extras[i - 1].open);
      });
    };
    extras.forEach(function (details) { details.addEventListener("toggle", syncExtras); });
    syncExtras();
  }

  // Merk- en typesuggesties: de server levert datalists met alle typen van het seizoen (werkt zonder
  // JavaScript); hier wisselen we de typen per merk en seizoen. Vrije invoer blijft altijd mogelijk.
  var tireForm = document.querySelector("form[data-tire-form]");
  if (tireForm) {
    var catalog = {};
    try { catalog = JSON.parse(tireForm.getAttribute("data-catalog") || "{}") || {}; } catch (e) { catalog = {}; }
    var typeSelect = tireForm.querySelector('select[name="type"]');
    var fixedSeason = tireForm.getAttribute("data-season") || "";
    var fixedSetBrand = tireForm.getAttribute("data-set-brand") || "";
    var setBrandInput = tireForm.querySelector('input[name="brand"]');

    var season = function () { return typeSelect ? typeSelect.value : fixedSeason; };
    var findBrand = function (name) {
      var wanted = (name || "").trim().toLowerCase();
      if (!wanted) { return null; }
      var keys = Object.keys(catalog);
      for (var i = 0; i < keys.length; i += 1) {
        if (keys[i].toLowerCase() === wanted) { return keys[i]; }
      }
      return null;
    };
    var modelsFor = function (brandName) {
      var s = season();
      var key = findBrand(brandName);
      if (key) { return catalog[key][s] || []; }
      var all = {};
      Object.keys(catalog).forEach(function (b) {
        (catalog[b][s] || []).forEach(function (m) { all[m] = true; });
      });
      return Object.keys(all).sort(function (a, b) { return a.toLowerCase() < b.toLowerCase() ? -1 : 1; });
    };

    // Elk typeveld krijgt zijn eigen datalist, afhankelijk van het merk dat erbij hoort.
    var pairs = [];
    Array.prototype.forEach.call(tireForm.querySelectorAll('input[name$="model"]'), function (modelInput) {
      var prefix = modelInput.name.slice(0, -"model".length);
      var brandInput = tireForm.querySelector('input[name="' + prefix + 'brand"]');
      if (!brandInput) { return; }
      var list = document.createElement("datalist");
      list.id = "dl-models-" + (prefix || "main").replace(/[^a-z0-9]/gi, "");
      modelInput.parentNode.appendChild(list);
      modelInput.setAttribute("list", list.id);
      // Een groep zonder eigen merk valt terug op het merk van de set.
      var inherits = /^g\d_$/.test(prefix) && setBrandInput ? setBrandInput : null;
      pairs.push({ brand: brandInput, list: list, inherits: inherits });
    });
    var refresh = function () {
      pairs.forEach(function (pair) {
        var name = pair.brand.value.trim() || (pair.inherits ? pair.inherits.value : fixedSetBrand);
        while (pair.list.firstChild) { pair.list.removeChild(pair.list.firstChild); }
        modelsFor(name).forEach(function (model) {
          var option = document.createElement("option");
          option.value = model;
          pair.list.appendChild(option);
        });
      });
    };
    tireForm.addEventListener("input", function (event) {
      var target = event.target;
      if (target && target.name && /(^|_)brand$/.test(target.name)) { refresh(); }
    });
    if (typeSelect) { typeSelect.addEventListener("change", refresh); }
    refresh();

    // Maat: alleen een zachte hint, geen blokkade (bestaande en afwijkende maten blijven kunnen).
    var sizeInput = tireForm.querySelector('input[name="size"]');
    if (sizeInput) {
      var sizeHint = document.createElement("p");
      sizeHint.className = "size-hint";
      sizeHint.setAttribute("role", "status");
      sizeHint.hidden = true;
      sizeHint.textContent = tireForm.getAttribute("data-msg-size-odd") || "";
      sizeInput.parentNode.appendChild(sizeHint);
      var usual = /^(?:P|LT)?\d{3}\s*\/\s*\d{2}\s*(?:Z|V|W|Y)?\s*[-R]\s*\d{2}(?:\.\d)?(?:\b.*)?$/i;
      var checkSize = function () {
        var value = sizeInput.value.trim();
        sizeHint.hidden = value === "" || usual.test(value);
      };
      sizeInput.addEventListener("input", checkSize);
      checkSize();
    }
  }

  // Tijdblokken van het eigen weekschema toevoegen/verwijderen.
  var schedule = document.querySelector("[data-schedule]");
  if (schedule) {
    var counter = 1000;

    var refresh = function (day) {
      var slots = day.querySelectorAll(".slot");
      slots.forEach(function (slot) {
        var remove = slot.querySelector("[data-remove-slot]");
        if (remove) { remove.hidden = slots.length <= 1; }
      });
    };

    schedule.querySelectorAll("[data-add-slot], [data-remove-slot]").forEach(function (b) {
      b.hidden = false;
    });
    schedule.querySelectorAll(".day").forEach(refresh);

    schedule.addEventListener("click", function (event) {
      var target = event.target;
      if (!(target instanceof Element)) { return; }
      var day = target.closest(".day");
      if (!day) { return; }

      if (target.matches("[data-add-slot]")) {
        var list = day.querySelector(".slots");
        var template = list.querySelector(".slot:last-child");
        var copy = template.cloneNode(true);
        counter += 1;
        copy.querySelectorAll("input[type=time]").forEach(function (input) {
          input.value = "";
          var oldId = input.id;
          input.id = oldId + "-n" + counter;
          var label = copy.querySelector('label[for="' + oldId + '"]');
          if (label) { label.setAttribute("for", input.id); }
        });
        list.appendChild(copy);
        refresh(day);
        var first = copy.querySelector("input[type=time]");
        if (first) { first.focus(); }
      } else if (target.matches("[data-remove-slot]")) {
        var slot = target.closest(".slot");
        var all = day.querySelectorAll(".slot");
        if (all.length > 1) {
          slot.remove();
        } else {
          slot.querySelectorAll("input[type=time]").forEach(function (i) { i.value = ""; });
        }
        refresh(day);
      }
    });
  }

  // Coördinaten opzoeken: adres/plaats via de geocode-API (sessiecookie, alleen GET; de URL staat in data-url) en
  // "Gebruik mijn locatie" via de browser. DOM wordt met createElement/textContent gebouwd.
  var geo = document.querySelector("[data-geo]");
  var geoForm = geo ? geo.closest("form") : null;
  if (geo && geoForm) {
    var latInput = geoForm.querySelector('input[name="latitude"]');
    var lonInput = geoForm.querySelector('input[name="longitude"]');
    var nameInput = geoForm.querySelector('input[name="location_name"]');
    var statusEl = geo.querySelector("[data-geo-status]");
    var queryInput = geo.querySelector("[data-geo-query]");
    var searchBtn = geo.querySelector("[data-geo-search]");
    var locateBtn = geo.querySelector("[data-geo-locate]");
    var resultList = geo.querySelector("[data-geo-results]");

    var text = function (key) { return geo.getAttribute("data-msg-" + key) || ""; };
    var say = function (key) { statusEl.textContent = text(key); };
    var setCoords = function (lat, lon) {
      latInput.value = String(lat);
      lonInput.value = String(lon);
    };

    // "Domplein, Utrecht, ..." -> "Domplein"; een huisnummer vooraan ("12, Straat, ...") -> "Straat 12".
    var shortName = function (label) {
      var parts = label.split(",").map(function (p) { return p.trim(); });
      var name = parts[0];
      if (/^\d/.test(name) && parts.length > 1) { name = parts[1] + " " + name; }
      var max = nameInput ? parseInt(nameInput.getAttribute("maxlength"), 10) : NaN;
      return isNaN(max) ? name : name.slice(0, max);
    };

    var clearResults = function () {
      while (resultList.firstChild) { resultList.removeChild(resultList.firstChild); }
      resultList.hidden = true;
    };

    var choose = function (item) {
      setCoords(item.latitude, item.longitude);
      if (nameInput && !nameInput.value.trim()) { nameInput.value = shortName(item.label); }
      clearResults();
      say("filled");
      queryInput.focus();
    };

    var showResults = function (items) {
      var usable = Array.isArray(items) ? items.filter(function (item) {
        return item && typeof item.label === "string" &&
          typeof item.latitude === "number" && isFinite(item.latitude) &&
          typeof item.longitude === "number" && isFinite(item.longitude);
      }).slice(0, 5) : [];
      if (!usable.length) { say("none"); return; }
      usable.forEach(function (item) {
        var li = document.createElement("li");
        var button = document.createElement("button");
        button.type = "button";
        button.className = "btn btn-small";
        button.textContent = item.label;
        button.addEventListener("click", function () { choose(item); });
        li.appendChild(button);
        resultList.appendChild(li);
      });
      resultList.hidden = false;
      say("found");
      resultList.querySelector("button").focus();
    };

    var busy = false;
    var search = function () {
      if (busy) { return; }
      var q = queryInput.value.trim();
      clearResults();
      if (q.length < 2) { say("short"); queryInput.focus(); return; }
      busy = true;
      say("searching");
      fetch(geo.getAttribute("data-url") + "?q=" + encodeURIComponent(q), {
        credentials: "same-origin",
        headers: { "Accept": "application/json" }
      }).then(function (response) {
        if (!response.ok) {
          var error = new Error("http");
          error.status = response.status;
          throw error;
        }
        return response.json();
      }).then(function (items) {
        showResults(items);
      }).catch(function (error) {
        say(error && error.status === 429 ? "busy" : "error");
      }).then(function () {
        busy = false;
      });
    };

    if (searchBtn && queryInput && resultList) {
      searchBtn.addEventListener("click", search);
      queryInput.addEventListener("keydown", function (event) {
        // Enter zoekt in plaats van het formulier te versturen.
        if (event.key === "Enter") { event.preventDefault(); search(); }
      });
    }

    var round3 = function (value) { return Math.round(value * 1000) / 1000 + 0; };
    if (locateBtn && "geolocation" in navigator) {
      locateBtn.hidden = false;
      locateBtn.addEventListener("click", function () {
        if (window.isSecureContext === false) { say("insecure"); return; }
        say("locating");
        navigator.geolocation.getCurrentPosition(function (position) {
          setCoords(round3(position.coords.latitude), round3(position.coords.longitude));
          say("located");
        }, function (error) {
          say(error && error.code === 1 ? "denied" : "unavailable");
        }, { enableHighAccuracy: false, timeout: 10000, maximumAge: 60000 });
      });
    }

    // Alleen tonen als er iets te doen valt (zoeken of de locatieknop).
    if (searchBtn || (locateBtn && !locateBtn.hidden)) { geo.hidden = false; }
  }
})();
