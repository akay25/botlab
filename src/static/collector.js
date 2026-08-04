/* Record how the tasks on this page were performed, then report it.

   The page keeps raw events. It computes nothing and judges nothing. The
   server derives every metric from the raw stream, so a stored run can be
   re-scored later when the rules change, and a reader can check the numbers.

   Every probe below is page-visible, so a tool that patches the main world
   consistently can defeat what this file reports. What it cannot reach is the
   handshake read before any script runs, and the shape of the raw events. */

(function () {
  "use strict";

  var START = performance.now();
  var MAX_POINTER = 3000;
  var MAX_KEYS = 800;
  var MAX_INPUT = 200;
  var MAX_WHEEL = 300;

  var telemetry = {
    version: 2,
    pointer: [],
    keys: [],
    clicks: [],
    inputs: [],
    wheel: [],
    targets: [],
    fitts: [],
    honeypots: [],
    keypress_count: 0,
    duration_ms: 0
  };

  function now() { return Math.round((performance.now() - START) * 100) / 100; }

  /* An element carrying data-honeypot is hidden from sight, removed from the tab
     order and hidden from assistive technology. Nothing that can see the page
     can reach one, so anything that touches one found it by reading the DOM.
     Walk up from the event target, because a click can land on a child. */
  function honeypotFor(node) {
    var depth = 0;
    while (node && node.getAttribute && depth < 6) {
      var kind = node.getAttribute("data-honeypot");
      if (kind) { return { kind: kind, id: node.id || "" }; }
      node = node.parentNode;
      depth += 1;
    }
    return null;
  }

  function recordHoneypot(type, event) {
    if (telemetry.honeypots.length >= 40) { return; }
    var trap = honeypotFor(event.target);
    if (!trap) { return; }
    telemetry.honeypots.push({
      t: now(), type: type, kind: trap.kind, id: trap.id,
      tr: event.isTrusted === true
    });
  }

  /* ------------------------------------------------------------ capture */

  function recordPointer(e) {
    if (telemetry.pointer.length >= MAX_POINTER) { return; }
    telemetry.pointer.push({
      t: now(),
      x: e.clientX,
      y: e.clientY,
      sx: e.screenX,
      sy: e.screenY,
      mx: typeof e.movementX === "number" ? e.movementX : null,
      my: typeof e.movementY === "number" ? e.movementY : null,
      p: typeof e.pressure === "number" ? e.pressure : null,
      pt: e.pointerType || "mouse",
      b: e.buttons,
      tr: e.isTrusted === true
    });
  }

  if (window.PointerEvent) {
    document.addEventListener("pointermove", recordPointer, { capture: true, passive: true });
  } else {
    document.addEventListener("mousemove", recordPointer, { capture: true, passive: true });
  }

  document.addEventListener("click", function (e) {
    recordHoneypot("click", e);
    if (telemetry.clicks.length >= 200) { return; }
    var target = e.target && e.target.id ? e.target.id : "";
    telemetry.clicks.push({
      t: now(), x: e.clientX, y: e.clientY, detail: e.detail,
      target: target, tr: e.isTrusted === true
    });
  }, true);

  document.addEventListener("focusin", function (e) {
    recordHoneypot("focus", e);
  }, true);

  function recordKey(type) {
    return function (e) {
      if (telemetry.keys.length >= MAX_KEYS) { return; }
      telemetry.keys.push({
        t: now(), type: type, key: e.key, code: e.code,
        loc: e.location, rep: e.repeat === true, tr: e.isTrusted === true
      });
    };
  }

  document.addEventListener("keydown", recordKey("down"), true);
  document.addEventListener("keyup", recordKey("up"), true);
  document.addEventListener("keypress", function () { telemetry.keypress_count += 1; }, true);

  document.addEventListener("input", function (e) {
    recordHoneypot("input", e);
    if (telemetry.inputs.length >= MAX_INPUT) { return; }
    telemetry.inputs.push({
      t: now(),
      type: e.inputType || "",
      data: e.data === null || e.data === undefined ? null : String(e.data).length,
      len: e.target && typeof e.target.value === "string" ? e.target.value.length : null,
      target: e.target && e.target.id ? e.target.id : "",
      tr: e.isTrusted === true
    });
  }, true);

  document.addEventListener("wheel", function (e) {
    if (telemetry.wheel.length >= MAX_WHEEL) { return; }
    telemetry.wheel.push({ t: now(), dy: e.deltaY, dm: e.deltaMode, tr: e.isTrusted === true });
  }, { capture: true, passive: true });

  document.addEventListener("paste", function (e) {
    telemetry.pasted = true;
    void e;
  }, true);

  /* ------------------------------------------------------------- probes */

  var AUTOMATION_KEYS = [
    "cdc_adoQpoasnfa76pfcZLmcfl_Array", "cdc_adoQpoasnfa76pfcZLmcfl_Promise",
    "cdc_adoQpoasnfa76pfcZLmcfl_Symbol", "$cdc_asdjflasutopfhvcZLmcfl_",
    "__webdriver_evaluate", "__selenium_evaluate", "__driver_evaluate",
    "__webdriver_script_function", "__fxdriver_evaluate", "__driver_unwrapped",
    "_phantom", "callPhantom", "domAutomation", "domAutomationController",
    "__nightmare", "_Selenium_IDE_Recorder", "__playwright__binding__",
    "__pw_manual", "__puppeteer_evaluation_script__"
  ];

  var STACK_MARKERS = ["puppeteer", "playwright", "selenium", "webdriver",
    "nightmare", "phantomjs", "evaluation_script", "__pw_", "cdp_"];

  function findAutomationKeys() {
    var found = [];
    var i;
    for (i = 0; i < AUTOMATION_KEYS.length; i++) {
      try {
        if (AUTOMATION_KEYS[i] in window || AUTOMATION_KEYS[i] in document) {
          found.push(AUTOMATION_KEYS[i]);
        }
      } catch (err) { /* not readable */ }
    }
    try {
      var names = Object.getOwnPropertyNames(document);
      for (i = 0; i < names.length; i++) {
        if (/^\$?cdc_|^\$\$?wdc_|selenium|webdriver/i.test(names[i]) &&
            found.indexOf(names[i]) === -1) {
          found.push(names[i]);
        }
      }
    } catch (err) { /* not readable */ }
    return found;
  }

  function nativeState(fn) {
    try {
      if (typeof fn !== "function") { return "absent"; }
      return Function.prototype.toString.call(fn).indexOf("[native code]") === -1
        ? "patched" : "native";
    } catch (err) { return "unreadable"; }
  }

  function findPatchedNatives() {
    var targets = [
      ["Function.prototype.toString", Function.prototype.toString],
      ["navigator.permissions.query", navigator.permissions && navigator.permissions.query],
      ["WebGLRenderingContext.getParameter", window.WebGLRenderingContext &&
        WebGLRenderingContext.prototype.getParameter],
      ["HTMLCanvasElement.toDataURL", HTMLCanvasElement.prototype.toDataURL],
      ["Object.getOwnPropertyDescriptor", Object.getOwnPropertyDescriptor],
      ["Error.captureStackTrace", Error.captureStackTrace]
    ];
    var patched = [];
    for (var i = 0; i < targets.length; i++) {
      if (nativeState(targets[i][1]) === "patched") { patched.push(targets[i][0]); }
    }
    return patched;
  }

  function readWebgl() {
    /* Report the adapter, and whether the unmasked names were readable. A
       masked renderer says "WebKit WebGL" whatever the machine has, so the
       server must know not to read it as evidence either way. */
    var out = { vendor: "", renderer: "", unmasked: false, supported: false };
    try {
      var canvas = document.createElement("canvas");
      var gl = canvas.getContext("webgl") || canvas.getContext("experimental-webgl");
      if (!gl) { return out; }
      out.supported = true;
      var info = gl.getExtension("WEBGL_debug_renderer_info");
      if (info) {
        out.unmasked = true;
        out.vendor = String(gl.getParameter(info.UNMASKED_VENDOR_WEBGL) || "");
        out.renderer = String(gl.getParameter(info.UNMASKED_RENDERER_WEBGL) || "");
      } else {
        out.vendor = String(gl.getParameter(gl.VENDOR) || "");
        out.renderer = String(gl.getParameter(gl.RENDERER) || "");
      }
    } catch (err) { /* no WebGL */ }
    return out;
  }

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
      ctx.fillText("botlab fingerprint ✓ éñ", 2, 18);
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

  /* Every name the font probe tests for. PLATFORM_FONTS in
     src/detection/reference.py reads these names, so a font named there must
     appear here or it can never be resolved. */
  var FONT_PROBES = ["Arial", "Verdana", "Times New Roman", "Courier New", "Georgia",
    "Trebuchet MS", "Comic Sans MS", "Impact", "Tahoma", "Segoe UI",
    "Helvetica Neue", "Cambria", "Consolas", "Palatino Linotype",
    "Lucida Console", "Franklin Gothic Medium", "Candara", "Optima",
    "Menlo", "Roboto", "Calibri", "Geneva", "Monaco", "Courier",
    "Lucida Grande", "MS Gothic", "Noto Sans", "DejaVu Sans", "Liberation Sans",
    "Ubuntu"];

  function probeFonts() {
    /* Report which fonts resolved, not how many. Which ones a machine has is
       evidence about the machine: a name that ships only with one desktop
       platform contradicts a User-Agent that claims another. The server counts
       them and compares them, so a stored run can be re-read when the rules
       change. */
    var base = ["monospace", "sans-serif", "serif"];
    try {
      if (!document.body) { return null; }
      var span = document.createElement("span");
      span.style.position = "absolute";
      span.style.left = "-9999px";
      span.style.fontSize = "72px";
      span.textContent = "mmmmmmmmmmlli";
      document.body.appendChild(span);
      var control = {};
      var i;
      for (i = 0; i < base.length; i++) {
        span.style.fontFamily = base[i];
        control[base[i]] = [span.offsetWidth, span.offsetHeight];
      }
      var found = [];
      for (i = 0; i < FONT_PROBES.length; i++) {
        for (var j = 0; j < base.length; j++) {
          span.style.fontFamily = "'" + FONT_PROBES[i] + "'," + base[j];
          if (span.offsetWidth !== control[base[j]][0] ||
              span.offsetHeight !== control[base[j]][1]) {
            found.push(FONT_PROBES[i]);
            break;
          }
        }
      }
      document.body.removeChild(span);
      return { fonts: found, checked: FONT_PROBES.length };
    } catch (err) { return null; }
  }

  function probeCdpAttached() {
    var read = false;
    try {
      var probe = new Error("botlab");
      Object.defineProperty(probe, "stack", {
        configurable: false, enumerable: false,
        get: function () { read = true; return ""; }
      });
      console.debug(probe);
    } catch (err) { /* console refused */ }
    return read;
  }

  function probeWebdriverPlacement() {
    var out = { own: false, proto: false };
    try {
      out.own = Object.getOwnPropertyDescriptor(navigator, "webdriver") !== undefined;
    } catch (err) { /* not readable */ }
    try {
      out.proto = !!(window.Navigator &&
        Object.getOwnPropertyDescriptor(Navigator.prototype, "webdriver") !== undefined);
    } catch (err) { /* not readable */ }
    return out;
  }

  function toStringChainNative() {
    try {
      var toString = Function.prototype.toString;
      if (toString.call(toString).indexOf("[native code]") === -1) { return false; }
      if (toString.call(Object.getOwnPropertyDescriptor).indexOf("[native code]") === -1) {
        return false;
      }
      return true;
    } catch (err) { return false; }
  }

  function readStackMarkers() {
    var found = [];
    try {
      var stack = String(new Error("botlab").stack || "").toLowerCase();
      for (var i = 0; i < STACK_MARKERS.length; i++) {
        if (stack.indexOf(STACK_MARKERS[i]) !== -1) { found.push(STACK_MARKERS[i]); }
      }
    } catch (err) { /* no stack */ }
    return found;
  }

  function measureFrames(budgetMs) {
    return new Promise(function (resolve) {
      var stamps = [];
      var settled = false;
      function finish() {
        if (settled) { return; }
        settled = true;
        var deltas = [];
        for (var i = 1; i < stamps.length; i++) {
          var d = stamps[i] - stamps[i - 1];
          if (d > 0) { deltas.push(d); }
        }
        if (!deltas.length) {
          return resolve({ frame_count: stamps.length, frame_mean_ms: null, frame_stdev_ms: null });
        }
        var sum = 0, j;
        for (j = 0; j < deltas.length; j++) { sum += deltas[j]; }
        var mean = sum / deltas.length;
        var variance = 0;
        for (j = 0; j < deltas.length; j++) {
          variance += (deltas[j] - mean) * (deltas[j] - mean);
        }
        resolve({
          frame_count: stamps.length,
          frame_mean_ms: Math.round(mean * 1000) / 1000,
          frame_stdev_ms: Math.round(Math.sqrt(variance / deltas.length) * 1000) / 1000
        });
      }
      if (typeof requestAnimationFrame !== "function") {
        return resolve({ frame_count: 0, frame_mean_ms: null, frame_stdev_ms: null });
      }
      var began = performance.now();
      requestAnimationFrame(function tick(t) {
        stamps.push(t);
        if (performance.now() - began < budgetMs && stamps.length < 90) {
          requestAnimationFrame(tick);
        } else { finish(); }
      });
      setTimeout(finish, budgetMs + 600);
    });
  }

  function withTimeout(promise, ms, fallback) {
    return new Promise(function (resolve) {
      var done = false;
      function settle(v) { if (!done) { done = true; resolve(v); } }
      setTimeout(function () { settle(fallback); }, ms);
      try { Promise.resolve(promise).then(settle, function () { settle(fallback); }); }
      catch (err) { settle(fallback); }
    });
  }

  function probeMediaDevices() {
    /* Report the device kinds, not only how many there are. A microphone and a
       camera are hardware a container does not have, and enumerateDevices
       reports the kind of each device even before permission is granted; only
       the labels stay blank until then. */
    var EMPTY = {
      media_device_count: null, media_device_kinds: "",
      media_devices: null, media_devices_labelled: null
    };
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) {
      return Promise.resolve(EMPTY);
    }
    return withTimeout(navigator.mediaDevices.enumerateDevices().then(function (list) {
      var kinds = {};
      var labelled = 0;
      list.forEach(function (d) {
        kinds[d.kind] = (kinds[d.kind] || 0) + 1;
        if (d.label) { labelled += 1; }
      });
      return {
        media_device_count: list.length,
        media_devices: kinds,
        media_devices_labelled: labelled,
        media_device_kinds: Object.keys(kinds).map(function (k) {
          return k + ":" + kinds[k];
        }).join(",")
      };
    }), 1200, EMPTY);
  }

  function probeVoices() {
    return new Promise(function (resolve) {
      if (!window.speechSynthesis || !speechSynthesis.getVoices) {
        return resolve({ voice_count: null });
      }
      var waited = 0;
      function poll() {
        var voices = [];
        try { voices = speechSynthesis.getVoices() || []; } catch (err) { voices = []; }
        if (voices.length || waited >= 900) { return resolve({ voice_count: voices.length }); }
        waited += 150;
        setTimeout(poll, 150);
      }
      poll();
    });
  }

  function probeCodecs() {
    var out = { h264: "", aac: "", mp3: "", webm: "", ogg: "" };
    try {
      var video = document.createElement("video");
      var audio = document.createElement("audio");
      out.h264 = video.canPlayType('video/mp4; codecs="avc1.42E01E"') || "";
      out.webm = video.canPlayType('video/webm; codecs="vp8, vorbis"') || "";
      out.aac = audio.canPlayType('audio/mp4; codecs="mp4a.40.2"') || "";
      out.mp3 = audio.canPlayType("audio/mpeg") || "";
      out.ogg = audio.canPlayType('audio/ogg; codecs="vorbis"') || "";
    } catch (err) { /* no media element */ }
    return out;
  }

  function probeIce() {
    var Ctor = window.RTCPeerConnection || window.webkitRTCPeerConnection;
    if (!Ctor) {
      return Promise.resolve({
        webrtc_supported: false, ice_candidate_count: null, ice_host_candidate: false
      });
    }
    return new Promise(function (resolve) {
      var candidates = [];
      var settled = false;
      var pc = null;
      function finish() {
        if (settled) { return; }
        settled = true;
        try { if (pc) { pc.close(); } } catch (err) { /* closed */ }
        resolve({
          webrtc_supported: true,
          ice_candidate_count: candidates.length,
          ice_host_candidate: candidates.some(function (c) {
            return c.indexOf("typ host") !== -1;
          })
        });
      }
      try {
        pc = new Ctor({ iceServers: [] });
        pc.onicecandidate = function (event) {
          if (!event.candidate) { return finish(); }
          candidates.push(String(event.candidate.candidate || ""));
        };
        pc.createDataChannel("botlab");
        pc.createOffer().then(function (offer) {
          return pc.setLocalDescription(offer);
        }).catch(function () { finish(); });
      } catch (err) { return finish(); }
      setTimeout(finish, 1500);
    });
  }

  function probePermissions() {
    var names = ["notifications", "geolocation", "camera", "microphone", "midi"];
    if (!navigator.permissions || !navigator.permissions.query) {
      return Promise.resolve({ permissions: {}, permission_mismatch: false });
    }
    return Promise.all(names.map(function (name) {
      return withTimeout(navigator.permissions.query({ name: name }).then(function (s) {
        return [name, s.state];
      }), 800, null);
    })).then(function (pairs) {
      var out = {};
      pairs.forEach(function (p) { if (p) { out[p[0]] = p[1]; } });
      var mismatch = false;
      try {
        mismatch = !!(window.Notification && Notification.permission === "denied" &&
          out.notifications === "prompt");
      } catch (err) { mismatch = false; }
      return { permissions: out, permission_mismatch: mismatch };
    });
  }

  /* Key systems worth asking about. Clear Key is the control: the EME spec
     mandates it and it needs no licensed component, so a client that grants
     Clear Key and refuses Widevine is running an engine that does EME with no
     DRM module behind it. That is the plain Chromium automation downloads. */
  var DRM_SYSTEMS = [
    ["widevine", "com.widevine.alpha"],
    ["playready", "com.microsoft.playready"],
    ["fairplay", "com.apple.fps.1_0"],
    ["clearkey", "org.w3.clearkey"]
  ];

  /* Widevine robustness levels, weakest first. SW_ is a software decrypt path;
     HW_ means the keys never leave the trusted execution environment, which a
     container has no access to. */
  var WIDEVINE_ROBUSTNESS = ["SW_SECURE_CRYPTO", "SW_SECURE_DECODE",
    "HW_SECURE_CRYPTO", "HW_SECURE_DECODE", "HW_SECURE_ALL"];

  function probeDrm() {
    var out = {
      secure_context: window.isSecureContext === true,
      eme_supported: typeof navigator.requestMediaKeySystemAccess === "function",
      key_systems: {},
      widevine_robustness: null
    };
    /* EME is gated on a secure context. Over plain HTTP the API is simply
       absent, which says nothing about the client, so record why. */
    if (!out.eme_supported) { return Promise.resolve(out); }

    function ask(system, robustness) {
      /* Offer VP8 as well as H.264 so this does not quietly re-test whether the
         build carries the licensed codecs. That is a separate probe. */
      var video = [{ contentType: 'video/webm; codecs="vp8"' },
                   { contentType: 'video/mp4; codecs="avc1.42E01E"' }];
      if (robustness) {
        video = video.map(function (c) {
          return { contentType: c.contentType, robustness: robustness };
        });
      }
      var config = [{
        initDataTypes: ["cenc", "webm", "keyids"],
        videoCapabilities: video
      }];
      var attempt;
      try {
        attempt = navigator.requestMediaKeySystemAccess(system, config).then(
          function () { return true; }, function () { return false; });
      } catch (err) { return Promise.resolve(false); }
      /* null means the question was never answered, which is not the same as a
         refusal, so the server can decline to read anything into it. */
      return withTimeout(attempt, 1500, null);
    }

    return Promise.all(DRM_SYSTEMS.map(function (entry) {
      return ask(entry[1], "").then(function (state) { return [entry[0], state]; });
    })).then(function (pairs) {
      pairs.forEach(function (pair) { out.key_systems[pair[0]] = pair[1]; });
      if (out.key_systems.widevine !== true) { return out; }

      // Walk down from the strongest level and keep the first one granted.
      var levels = WIDEVINE_ROBUSTNESS.slice().reverse();
      var index = 0;
      function next() {
        if (index >= levels.length) { return out; }
        var level = levels[index++];
        return ask("com.widevine.alpha", level).then(function (granted) {
          if (granted === true) { out.widevine_robustness = level; return out; }
          return next();
        });
      }
      return next();
    }, function () { return out; });
  }

  function probeStorage() {
    if (!navigator.storage || !navigator.storage.estimate) {
      return Promise.resolve({ storage_quota: null });
    }
    return withTimeout(navigator.storage.estimate().then(function (e) {
      return { storage_quota: e && typeof e.quota === "number" ? e.quota : null };
    }), 900, { storage_quota: null });
  }

  /* Runtime facts that must be read before page script could change them. */
  var earlyRuntime = (function () {
    var placement = probeWebdriverPlacement();
    var stack = "";
    try { stack = String(new Error("botlab").stack || ""); } catch (err) { stack = ""; }
    return {
      cdp_runtime_enabled: probeCdpAttached(),
      webdriver_own_property: placement.own,
      webdriver_on_prototype: placement.proto,
      prepare_stack_trace_set: (function () {
        try { return Error.prepareStackTrace !== undefined; } catch (err) { return false; }
      })(),
      stack_markers: readStackMarkers(),
      stack_depth: stack ? stack.split("\n").length : 0,
      tostring_chain_native: toStringChainNative(),
      visibility: document.visibilityState || "unknown"
    };
  })();

  var slowProbes = null;

  function startSlowProbes() {
    if (slowProbes) { return slowProbes; }
    slowProbes = Promise.all([
      measureFrames(700), probeMediaDevices(), probeVoices(),
      probeIce(), probePermissions(), probeStorage(), probeDrm()
    ]).then(function (parts) {
      var permissions = parts[4];
      return {
        runtime: {
          frame_count: parts[0].frame_count,
          frame_mean_ms: parts[0].frame_mean_ms,
          frame_stdev_ms: parts[0].frame_stdev_ms,
          visibility: document.visibilityState || "unknown"
        },
        environment: Object.assign({}, parts[1], parts[2], parts[3],
          { permissions: permissions.permissions }, parts[5], {
            drm: parts[6],
            codecs: probeCodecs(),
            pdf_viewer_enabled: navigator.pdfViewerEnabled === true,
            battery_api: typeof navigator.getBattery === "function",
            gamepad_api: typeof navigator.getGamepads === "function",
            font_api: !!document.fonts
          }),
        permission_mismatch: permissions.permission_mismatch
      };
    });
    return slowProbes;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", startSlowProbes, { once: true });
  } else {
    startSlowProbes();
  }

  function buildFingerprint(mismatch) {
    var gl = readWebgl();
    var fonts = probeFonts();
    return {
      webdriver: navigator.webdriver === true,
      automation_keys: findAutomationKeys(),
      patched_natives: findPatchedNatives(),
      webgl_vendor: gl.vendor,
      webgl_renderer: gl.renderer,
      webgl_unmasked: gl.unmasked,
      webgl_supported: gl.supported,
      canvas_hash: canvasHash(),
      fonts: fonts ? fonts.fonts : null,
      fonts_checked: fonts ? fonts.checked : null,
      font_count: fonts ? fonts.fonts.length : null,
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
      inner_width: window.innerWidth,
      inner_height: window.innerHeight,
      outer_width: window.outerWidth,
      outer_height: window.outerHeight,
      timezone: (Intl.DateTimeFormat().resolvedOptions() || {}).timeZone || "",
      timezone_offset: new Date().getTimezoneOffset(),
      user_agent: navigator.userAgent
    };
  }

  /* --------------------------------------------------------------- send */

  function send(label) {
    telemetry.duration_ms = Math.round(performance.now() - START);
    return startSlowProbes().then(function (slow) {
      var payload = {
        session: window.botlab.sessionId,
        label: label || "",
        source: "page",
        reason: "tasks",
        page_url: location.href,
        js: buildFingerprint(slow.permission_mismatch),
        runtime: Object.assign({}, earlyRuntime, slow.runtime),
        environment: slow.environment,
        behavior: telemetry
      };
      return fetch("/api/collect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      }).then(function (r) { return r.json(); }).then(function (envelope) {
        /* The API wraps every reply as {success, message, data}. */
        var result = envelope && envelope.data ? envelope.data : envelope;
        window.botlab.result = result;
        return result;
      });
    });
  }

  /* The pointer position when a target appeared is where the hand started from,
     which is the D in Fitts's law. Keep the last one seen so an acquisition can
     be stamped with it. */
  var lastPointer = { x: null, y: null };
  function trackPointer(e) { lastPointer = { x: e.clientX, y: e.clientY }; }
  document.addEventListener(window.PointerEvent ? "pointermove" : "mousemove",
    trackPointer, { capture: true, passive: true });

  var shownFrom = { x: null, y: null };

  window.botlab = {
    sessionId: window.__BOTLAB_SESSION__ || "",
    result: null,
    send: send,
    telemetry: telemetry,
    now: now,
    markTarget: function (id, rect) {
      telemetry.targets.push({
        id: id, t: now(),
        cx: Math.round(rect.left + rect.width / 2),
        cy: Math.round(rect.top + rect.height / 2)
      });
    },
    /* Called as each acquisition target appears: freeze where the pointer was
       at that instant, before it starts travelling. */
    markTargetShown: function () {
      shownFrom = { x: lastPointer.x, y: lastPointer.y };
    },
    markAcquisition: function (record) {
      if (telemetry.fitts.length >= 60) { return; }
      telemetry.fitts.push({
        i: record.i, cx: record.cx, cy: record.cy, w: record.w,
        shown: record.shown, t: now(),
        hx: record.hx, hy: record.hy,
        fx: shownFrom.x, fy: shownFrom.y,
        miss: record.miss || 0
      });
    }
  };
})();
