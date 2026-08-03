/* Collect the browser fingerprint and the interaction telemetry.
   The script posts one report to /collect. It stores nothing on the client. */

(function () {
  "use strict";

  var START = performance.now();
  var behavior = {
    mouse: [],
    clicks: 0,
    key_intervals: [],
    scroll_deltas: [],
    first_interaction_ms: null
  };
  var lastKeyTime = null;

  var AUTOMATION_KEYS = [
    "cdc_adoQpoasnfa76pfcZLmcfl_Array", "cdc_adoQpoasnfa76pfcZLmcfl_Promise",
    "cdc_adoQpoasnfa76pfcZLmcfl_Symbol", "$cdc_asdjflasutopfhvcZLmcfl_",
    "__webdriver_evaluate", "__selenium_evaluate", "__driver_evaluate",
    "__webdriver_script_function", "__fxdriver_evaluate", "__driver_unwrapped",
    "_phantom", "callPhantom", "domAutomation", "domAutomationController",
    "__nightmare", "_Selenium_IDE_Recorder", "__playwright__binding__",
    "__pw_manual", "__puppeteer_evaluation_script__"
  ];

  function markFirst() {
    if (behavior.first_interaction_ms === null) {
      behavior.first_interaction_ms = Math.round(performance.now() - START);
    }
  }

  document.addEventListener("mousemove", function (e) {
    markFirst();
    if (behavior.mouse.length < 600) {
      behavior.mouse.push({
        x: e.clientX,
        y: e.clientY,
        t: Math.round(performance.now()),
        trusted: e.isTrusted === true
      });
    }
  }, { passive: true });

  document.addEventListener("click", function (e) {
    markFirst();
    behavior.clicks += 1;
    if (e.isTrusted !== true) { behavior.untrusted_click = true; }
  }, { passive: true });

  document.addEventListener("keydown", function () {
    markFirst();
    var now = performance.now();
    if (lastKeyTime !== null) { behavior.key_intervals.push(Math.round(now - lastKeyTime)); }
    lastKeyTime = now;
  }, { passive: true });

  document.addEventListener("wheel", function (e) {
    markFirst();
    if (behavior.scroll_deltas.length < 200) { behavior.scroll_deltas.push(e.deltaY); }
  }, { passive: true });

  /* Return the automation properties that exist on the window object. */
  function findAutomationKeys() {
    var found = [];
    var i;
    for (i = 0; i < AUTOMATION_KEYS.length; i++) {
      try {
        if (AUTOMATION_KEYS[i] in window || AUTOMATION_KEYS[i] in document) {
          found.push(AUTOMATION_KEYS[i]);
        }
      } catch (err) { /* the property is not readable */ }
    }
    try {
      var docKeys = Object.getOwnPropertyNames(document);
      for (i = 0; i < docKeys.length; i++) {
        if (/^\$?cdc_|^\$\$?wdc_|selenium|webdriver/i.test(docKeys[i])) {
          if (found.indexOf(docKeys[i]) === -1) { found.push(docKeys[i]); }
        }
      }
    } catch (err) { /* the list is not readable */ }
    return found;
  }

  /* Return the names of native functions that no longer report native code.
     A stealth plugin replaces these functions to hide an automation marker. */
  function findPatchedNatives() {
    var targets = [
      ["navigator.permissions.query", function () { return navigator.permissions && navigator.permissions.query; }],
      ["Function.prototype.toString", function () { return Function.prototype.toString; }],
      ["navigator.plugins.item", function () { return navigator.plugins && navigator.plugins.item; }],
      ["WebGLRenderingContext.getParameter", function () { return WebGLRenderingContext.prototype.getParameter; }],
      ["HTMLCanvasElement.toDataURL", function () { return HTMLCanvasElement.prototype.toDataURL; }],
      ["Notification.requestPermission", function () { return Notification.requestPermission; }],
      ["Object.getOwnPropertyDescriptor", function () { return Object.getOwnPropertyDescriptor; }]
    ];
    var patched = [];
    for (var i = 0; i < targets.length; i++) {
      try {
        var fn = targets[i][1]();
        if (typeof fn !== "function") { continue; }
        var text = Function.prototype.toString.call(fn);
        if (text.indexOf("[native code]") === -1) { patched.push(targets[i][0]); }
      } catch (err) { /* the function is not reachable */ }
    }
    return patched;
  }

  /* Return the WebGL vendor and renderer strings. */
  function readWebgl() {
    var out = { vendor: "", renderer: "" };
    try {
      var canvas = document.createElement("canvas");
      var gl = canvas.getContext("webgl") || canvas.getContext("experimental-webgl");
      if (!gl) { return out; }
      var info = gl.getExtension("WEBGL_debug_renderer_info");
      if (info) {
        out.vendor = String(gl.getParameter(info.UNMASKED_VENDOR_WEBGL) || "");
        out.renderer = String(gl.getParameter(info.UNMASKED_RENDERER_WEBGL) || "");
      } else {
        out.vendor = String(gl.getParameter(gl.VENDOR) || "");
        out.renderer = String(gl.getParameter(gl.RENDERER) || "");
      }
    } catch (err) { /* WebGL is not available */ }
    return out;
  }

  /* Draw text and shapes, then return a hash of the pixels. */
  function canvasHash() {
    try {
      var canvas = document.createElement("canvas");
      canvas.width = 260;
      canvas.height = 60;
      var ctx = canvas.getContext("2d");
      ctx.textBaseline = "top";
      ctx.font = "16px 'Arial'";
      ctx.fillStyle = "#f60";
      ctx.fillRect(0, 0, 120, 24);
      ctx.fillStyle = "#069";
      ctx.fillText("botlab fingerprint \u2713 \u00e9\u00f1", 2, 18);
      ctx.globalCompositeOperation = "multiply";
      ctx.beginPath();
      ctx.arc(60, 40, 18, 0, Math.PI * 2, true);
      ctx.fill();
      var data = canvas.toDataURL();
      var hash = 5381;
      for (var i = 0; i < data.length; i++) {
        hash = ((hash << 5) + hash + data.charCodeAt(i)) >>> 0;
      }
      return String(hash);
    } catch (err) { return null; }
  }

  /* Count how many of a probe list render at a different width than the fallback. */
  function countFonts() {
    var probes = ["Arial", "Verdana", "Times New Roman", "Courier New", "Georgia",
      "Trebuchet MS", "Comic Sans MS", "Impact", "Tahoma", "Segoe UI",
      "Helvetica Neue", "Cambria", "Consolas", "Palatino Linotype",
      "Lucida Console", "Franklin Gothic Medium", "Candara", "Optima",
      "Menlo", "Roboto"];
    var base = ["monospace", "sans-serif", "serif"];
    var span = document.createElement("span");
    span.style.position = "absolute";
    span.style.left = "-9999px";
    span.style.fontSize = "72px";
    span.textContent = "mmmmmmmmmmlli";
    document.body.appendChild(span);

    var reference = {};
    var i;
    for (i = 0; i < base.length; i++) {
      span.style.fontFamily = base[i];
      reference[base[i]] = [span.offsetWidth, span.offsetHeight];
    }
    var found = 0;
    for (i = 0; i < probes.length; i++) {
      for (var j = 0; j < base.length; j++) {
        span.style.fontFamily = "'" + probes[i] + "'," + base[j];
        if (span.offsetWidth !== reference[base[j]][0] ||
            span.offsetHeight !== reference[base[j]][1]) {
          found += 1;
          break;
        }
      }
    }
    document.body.removeChild(span);
    return found;
  }

  /* Compare the Permissions API with Notification.permission.
     A headless browser reports denied and prompt at the same time. */
  function permissionMismatch() {
    return new Promise(function (resolve) {
      if (!navigator.permissions || !window.Notification) { return resolve(false); }
      navigator.permissions.query({ name: "notifications" }).then(function (result) {
        resolve(Notification.permission === "denied" && result.state === "prompt");
      }).catch(function () { resolve(false); });
    });
  }

  function buildReport(mismatch) {
    var gl = readWebgl();
    return {
      webdriver: navigator.webdriver === true,
      automation_keys: findAutomationKeys(),
      patched_natives: findPatchedNatives(),
      webgl_vendor: gl.vendor,
      webgl_renderer: gl.renderer,
      canvas_hash: canvasHash(),
      font_count: countFonts(),
      permission_mismatch: mismatch,
      has_chrome_object: typeof window.chrome === "object" && window.chrome !== null,
      plugin_count: navigator.plugins ? navigator.plugins.length : 0,
      platform: navigator.platform || "",
      language: navigator.language || "",
      languages: (navigator.languages || []).join(","),
      hardware_concurrency: navigator.hardwareConcurrency || 0,
      device_memory: navigator.deviceMemory || 0,
      max_touch_points: navigator.maxTouchPoints || 0,
      screen_width: screen.width,
      screen_height: screen.height,
      color_depth: screen.colorDepth,
      pixel_ratio: window.devicePixelRatio,
      outer_width: window.outerWidth,
      outer_height: window.outerHeight,
      inner_width: window.innerWidth,
      inner_height: window.innerHeight,
      timezone: (Intl.DateTimeFormat().resolvedOptions() || {}).timeZone || "",
      timezone_offset: new Date().getTimezoneOffset(),
      user_agent: navigator.userAgent
    };
  }

  function send(reason) {
    permissionMismatch().then(function (mismatch) {
      var payload = {
        reason: reason,
        session: window.__BOTLAB_SESSION__ || "",
        label: window.__BOTLAB_LABEL__ || "",
        js: buildReport(mismatch),
        behavior: behavior
      };
      fetch("/collect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      }).then(function (r) { return r.json(); }).then(function (result) {
        if (window.__BOTLAB_ON_RESULT__) { window.__BOTLAB_ON_RESULT__(result); }
      }).catch(function () { /* the report did not reach the server */ });
    });
  }

  window.__BOTLAB_SEND__ = send;
  window.addEventListener("load", function () { setTimeout(function () { send("load"); }, 400); });
})();
