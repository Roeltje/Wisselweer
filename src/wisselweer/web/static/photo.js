/* Voertuigfoto: verkleint de gekozen foto in de browser voordat hij wordt verstuurd.
   Her-encoderen via een canvas laat alle EXIF-gegevens (ook GPS) weg en houdt de upload klein.
   Lukt dat niet (oude browser), dan gaat het originele bestand mee en controleert de server het. */
(function () {
  "use strict";

  var MAX_SIDE = 1200;
  var QUALITY = 0.85;

  var form = document.querySelector("form[data-photo-form]");
  if (!form) { return; }
  var input = form.querySelector("[data-photo-input]");
  var preview = form.querySelector("[data-photo-preview]");
  var status = form.querySelector("[data-photo-status]");
  var submit = form.querySelector("[data-photo-submit]");
  if (!input || !preview || !status) { return; }

  var supported = typeof window.createImageBitmap === "function" &&
    typeof window.DataTransfer === "function" && typeof window.File === "function";
  var run = 0;

  var say = function (key) { status.textContent = form.getAttribute("data-msg-" + key) || ""; };
  var clearPreview = function () {
    while (preview.firstChild) { preview.removeChild(preview.firstChild); }
    preview.hidden = true;
  };
  var toBlob = function (canvas, type) {
    return new Promise(function (resolve) { canvas.toBlob(resolve, type, QUALITY); });
  };

  // WebP als de browser dat kan maken, anders JPEG (dan met een witte achtergrond onder transparantie).
  var encode = function (canvas) {
    return toBlob(canvas, "image/webp").then(function (blob) {
      if (blob && blob.type === "image/webp") { return blob; }
      var ctx = canvas.getContext("2d");
      ctx.globalCompositeOperation = "destination-over";
      ctx.fillStyle = "#fff";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      return toBlob(canvas, "image/jpeg");
    });
  };

  var process = function (file) {
    var id = ++run;
    var canvas = document.createElement("canvas");
    submit.disabled = true;
    clearPreview();
    say("working");
    // "from-image": de EXIF-oriëntatie wordt toegepast, want die gaat bij het her-encoderen verloren.
    return window.createImageBitmap(file, { imageOrientation: "from-image" }).then(function (bitmap) {
      var scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
      canvas.width = Math.max(1, Math.round(bitmap.width * scale));
      canvas.height = Math.max(1, Math.round(bitmap.height * scale));
      canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      if (bitmap.close) { bitmap.close(); }
      return encode(canvas);
    }).then(function (blob) {
      if (id !== run) { return; }
      if (!blob) { throw new Error("encode"); }
      var name = blob.type === "image/webp" ? "foto.webp" : "foto.jpg";
      var transfer = new window.DataTransfer();
      transfer.items.add(new window.File([blob], name, { type: blob.type }));
      input.files = transfer.files;
      // Voorvertoning op het canvas zelf: een blob:-URL in een <img> staat de CSP niet toe.
      preview.appendChild(canvas);
      preview.hidden = false;
      say("ready");
    }).catch(function () {
      if (id !== run) { return; }
      clearPreview();
      say("failed");
    }).then(function () {
      if (id === run) { submit.disabled = false; }
    });
  };

  input.addEventListener("change", function () {
    run += 1;
    clearPreview();
    status.textContent = "";
    submit.disabled = false;
    if (supported && input.files && input.files.length) { process(input.files[0]); }
  });
})();
