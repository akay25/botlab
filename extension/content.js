/* Run in the isolated world. Read the same properties as the main world.

   A stealth patch applied through the automation control channel lands in the
   main world only. This script therefore sees the unpatched values. Any field
   that differs between the two worlds is evidence of a patch.

   This world also owns the behaviour telemetry, because a listener here reads
   isTrusted before page script can replace the event object. */

(function () {
  "use strict";

  var START = performance.now();
  var behavior = {
    mouse: [], clicks: 0, key_intervals: [], scroll_deltas: [],
    first_interaction_ms: null, untrusted_events: 0
  };
  var lastKey = null;

  function markFirst() {
    if (behavior.first_interaction_ms === null) {
      behavior.first_interaction_ms = Math.round(performance.now() - START);
    }
  }

  document.addEventListener("mousemove", function (e) {
    markFirst();
    if (e.isTrusted !== true) { behavior.untrusted_events += 1; }
    if (behavior.mouse.length < 600) {
      behavior.mouse.push({ x: e.clientX, y: e.clientY, t: Math.round(performance.now()) });
    }
  }, true);

  document.addEventListener("click", function (e) {
    markFirst();
    behavior.clicks += 1;
    if (e.isTrusted !== true) { behavior.untrusted_events += 1; }
  }, true);

  document.addEventListener("keydown", function (e) {
    markFirst();
    if (e.isTrusted !== true) { behavior.untrusted_events += 1; }
    var now = performance.now();
    if (lastKey !== null) { behavior.key_intervals.push(Math.round(now - lastKey)); }
    lastKey = now;
  }, true);

  document.addEventListener("wheel", function (e) {
    markFirst();
    if (e.isTrusted !== true) { behavior.untrusted_events += 1; }
    if (behavior.scroll_deltas.length < 200) { behavior.scroll_deltas.push(e.deltaY); }
  }, true);

  function nativeState(fn) {
    try {
      if (typeof fn !== "function") { return "absent"; }
      return Function.prototype.toString.call(fn).indexOf("[native code]") === -1
        ? "patched" : "native";
    } catch (err) { return "unreadable"; }
  }

  /* Read the isolated view of the same fields that the main world reported. */
  function isolatedSnapshot() {
    return {
      world: "isolated",
      webdriver: navigator.webdriver === true,
      user_agent: navigator.userAgent,
      platform: navigator.platform || "",
      vendor: navigator.vendor || "",
      language: navigator.language || "",
      languages: (navigator.languages || []).join(","),
      hardware_concurrency: navigator.hardwareConcurrency || 0,
      device_memory: navigator.deviceMemory || 0,
      max_touch_points: navigator.maxTouchPoints || 0,
      plugin_count: navigator.plugins ? navigator.plugins.length : 0,
      mime_count: navigator.mimeTypes ? navigator.mimeTypes.length : 0,
      pdf_viewer_enabled: navigator.pdfViewerEnabled === true,
      battery_api: typeof navigator.getBattery === "function",
      screen_width: screen.width,
      screen_height: screen.height,
      outer_width: window.outerWidth,
      outer_height: window.outerHeight,
      timezone: (Intl.DateTimeFormat().resolvedOptions() || {}).timeZone || "",
      natives: {
        "Function.prototype.toString": nativeState(Function.prototype.toString),
        "HTMLCanvasElement.toDataURL": nativeState(HTMLCanvasElement.prototype.toDataURL),
        "Object.getOwnPropertyDescriptor": nativeState(Object.getOwnPropertyDescriptor)
      }
    };
  }

  var COMPARED = [
    "webdriver", "user_agent", "platform", "vendor", "language", "languages",
    "hardware_concurrency", "device_memory", "max_touch_points", "plugin_count",
    "mime_count", "pdf_viewer_enabled", "battery_api", "screen_width",
    "screen_height", "outer_width", "outer_height", "timezone"
  ];

  /* Return every field where the two worlds disagree. */
  function compare(main, isolated) {
    var out = [];
    if (!main) { return out; }
    COMPARED.forEach(function (field) {
      var a = main[field];
      var b = isolated[field];
      if (a === undefined || b === undefined) { return; }
      if (String(a) !== String(b)) {
        out.push({ field: field, main: String(a), isolated: String(b) });
      }
    });
    Object.keys(isolated.natives).forEach(function (name) {
      var a = (main.natives || {})[name];
      var b = isolated.natives[name];
      if (a && b && a !== b) {
        out.push({ field: "native:" + name, main: a, isolated: b });
      }
    });
    return out;
  }

  /* The main world publishes once. Keep what it said, because the popup can
     ask for a second measurement long after the attribute is gone. */
  var cachedMain = null;
  var cachedAsync = null;

  function readPublished(name) {
    try {
      var raw = document.documentElement.getAttribute(name);
      if (!raw) { return null; }
      document.documentElement.removeAttribute(name);
      return JSON.parse(raw);
    } catch (err) { return null; }
  }

  function collectPublished() {
    cachedMain = readPublished("data-botlab-main") || cachedMain;
    cachedAsync = readPublished("data-botlab-main-async") || cachedAsync;
  }

  /* Wait for the second main-world pass, which needs time for its probes. */
  function waitForSlowProbes(timeoutMs) {
    return new Promise(function (resolve) {
      collectPublished();
      if (cachedAsync) { return resolve(); }
      var settled = false;
      function finish() {
        if (settled) { return; }
        settled = true;
        collectPublished();
        resolve();
      }
      document.addEventListener("botlab-main-async", finish, { once: true });
      setTimeout(finish, timeoutMs);
    });
  }

  function buildReport() {
    collectPublished();
    var isolated = isolatedSnapshot();
    var main = cachedMain;
    var slow = cachedAsync || {};
    var runtime = Object.assign({}, (main && main.runtime) || {}, slow.runtime || {});

    /* The browser layer reads these from the main-world view. */
    if (main && slow.font_count !== undefined && slow.font_count !== null) {
      main.font_count = slow.font_count;
    }
    if (main && slow.permission_mismatch !== undefined) {
      main.permission_mismatch = slow.permission_mismatch;
    }

    return {
      url: location.href,
      origin: location.origin,
      title: document.title,
      collected_at: new Date().toISOString(),
      main_world: main,
      isolated_world: isolated,
      runtime: runtime,
      environment: slow.environment || null,
      divergences: compare(main, isolated),
      behavior: behavior
    };
  }

  function send(reason) {
    var report = buildReport();
    report.reason = reason;
    try {
      chrome.runtime.sendMessage({ type: "botlab-report", report: report }, function () {
        void chrome.runtime.lastError;   /* the popup may be closed */
      });
    } catch (err) { /* the extension context reloaded */ }
  }

  chrome.runtime.onMessage.addListener(function (message, sender, reply) {
    if (message && message.type === "botlab-collect-now") {
      send("manual");
      reply({ ok: true });
    }
    return true;
  });

  function firstReport() {
    waitForSlowProbes(3000).then(function () { send("load"); });
  }

  if (document.readyState === "complete") {
    setTimeout(firstReport, 300);
  } else {
    window.addEventListener("load", function () { setTimeout(firstReport, 300); });
  }
})();
