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
})();
