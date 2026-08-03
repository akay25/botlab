/* Run in the main world. Record what a website sees, and probe the engine.

   A stealth plugin patches this world, because this is where page code runs.
   The isolated world reads the same properties without those patches, so the
   difference between the two reports is direct evidence of a patch.

   The script publishes two reports. The first is synchronous and lands at
   document_start, before page script can touch anything. The second carries
   the probes that need time or a document body. Both travel to the isolated
   world on a document attribute, which avoids a race between two scripts that
   start together. */

(function () {
  "use strict";

  var AUTOMATION_KEYS = [
    "cdc_adoQpoasnfa76pfcZLmcfl_Array", "cdc_adoQpoasnfa76pfcZLmcfl_Promise",
    "cdc_adoQpoasnfa76pfcZLmcfl_Symbol", "$cdc_asdjflasutopfhvcZLmcfl_",
    "__webdriver_evaluate", "__selenium_evaluate", "__driver_evaluate",
    "__webdriver_script_function", "__fxdriver_evaluate", "__driver_unwrapped",
    "_phantom", "callPhantom", "domAutomation", "domAutomationController",
    "__nightmare", "_Selenium_IDE_Recorder", "__playwright__binding__",
    "__pw_manual", "__puppeteer_evaluation_script__"
  ];

  /* Names that only a driver puts on a call stack. The list holds no
     chrome-extension marker on purpose: this probe is itself an extension,
     and its own frames would match one. */
  var STACK_MARKERS = [
    "puppeteer", "playwright", "selenium", "webdriver", "nightmare",
    "phantomjs", "evaluation_script", "__pw_", "cdp_"
  ];

  function readAutomationKeys() {
    var found = [];
    for (var i = 0; i < AUTOMATION_KEYS.length; i++) {
      try {
        if (AUTOMATION_KEYS[i] in window || AUTOMATION_KEYS[i] in document) {
          found.push(AUTOMATION_KEYS[i]);
        }
      } catch (err) { /* the property is not readable */ }
    }
    try {
      var names = Object.getOwnPropertyNames(document);
      for (var j = 0; j < names.length; j++) {
        if (/^\$?cdc_|^\$\$?wdc_|selenium|webdriver/i.test(names[j]) &&
            found.indexOf(names[j]) === -1) {
          found.push(names[j]);
        }
      }
    } catch (err) { /* the list is not readable */ }
    return found;
  }

  /* Return the descriptor state of a property. A patch changes this shape. */
  function describe(target, name) {
    try {
      var owner = target;
      var descriptor = null;
      while (owner && !descriptor) {
        descriptor = Object.getOwnPropertyDescriptor(owner, name);
        owner = Object.getPrototypeOf(owner);
      }
      if (!descriptor) { return "absent"; }
      if (descriptor.get) {
        var text = Function.prototype.toString.call(descriptor.get);
        return text.indexOf("[native code]") === -1 ? "patched-getter" : "native-getter";
      }
      return descriptor.writable === false ? "value-frozen" : "value";
    } catch (err) { return "unreadable"; }
  }

  function nativeState(fn) {
    try {
      if (typeof fn !== "function") { return "absent"; }
      return Function.prototype.toString.call(fn).indexOf("[native code]") === -1
        ? "patched" : "native";
    } catch (err) { return "unreadable"; }
  }

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

  /* ------------------------------------------------------------ runtime */

  /* Detect an attached Chrome DevTools Protocol client.

     A console call does not format its argument until something reads it.
     Nothing reads it in a plain browser, so the stack getter below never
     runs. A CDP client serializes the error the moment it is logged, and
     that serialization reads the stack. An open DevTools window does the
     same, so the signal names a debugger, not an automation tool alone. */
  function probeCdpAttached() {
    var read = false;
    try {
      var probe = new Error("botlab");
      Object.defineProperty(probe, "stack", {
        configurable: false,
        enumerable: false,
        get: function () { read = true; return ""; }
      });
      console.debug(probe);
    } catch (err) { /* the console refused the call */ }
    return read;
  }

  /* Chrome defines webdriver on Navigator.prototype as a native getter. A
     stealth patch usually redefines it on the navigator instance instead,
     which leaves the property in the wrong place. */
  function probeWebdriverPlacement() {
    var out = { own: false, proto: false };
    try {
      out.own = Object.getOwnPropertyDescriptor(navigator, "webdriver") !== undefined;
    } catch (err) { /* the descriptor is not readable */ }
    try {
      out.proto = window.Navigator &&
        Object.getOwnPropertyDescriptor(Navigator.prototype, "webdriver") !== undefined;
    } catch (err) { /* the prototype is not readable */ }
    return out;
  }

  /* A patch that hides other patches must survive being asked about itself. */
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
    } catch (err) { /* the stack is not readable */ }
    return found;
  }

  function syncRuntime() {
    var placement = probeWebdriverPlacement();
    var stack = "";
    try { stack = String(new Error("botlab").stack || ""); } catch (err) { stack = ""; }
    return {
      cdp_runtime_enabled: probeCdpAttached(),
      webdriver_own_property: placement.own,
      webdriver_on_prototype: placement.proto,
      prepare_stack_trace_set: (function () {
        try { return Error.prepareStackTrace !== undefined; }
        catch (err) { return false; }
      })(),
      stack_markers: readStackMarkers(),
      stack_depth: stack ? stack.split("\n").length : 0,
      tostring_chain_native: toStringChainNative(),
      visibility: document.visibilityState || "unknown"
    };
  }

  /* Measure the frame clock. A window with no compositor never paints, and a
     generated clock does not jitter the way a display refresh does. */
  function measureFrames(budgetMs, done) {
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
        return done({ frame_count: stamps.length, frame_mean_ms: null, frame_stdev_ms: null });
      }
      var sum = 0;
      for (var j = 0; j < deltas.length; j++) { sum += deltas[j]; }
      var mean = sum / deltas.length;
      var variance = 0;
      for (var k = 0; k < deltas.length; k++) {
        variance += (deltas[k] - mean) * (deltas[k] - mean);
      }
      done({
        frame_count: stamps.length,
        frame_mean_ms: Math.round(mean * 1000) / 1000,
        frame_stdev_ms: Math.round(Math.sqrt(variance / deltas.length) * 1000) / 1000
      });
    }
    if (typeof requestAnimationFrame !== "function") {
      return done({ frame_count: 0, frame_mean_ms: null, frame_stdev_ms: null });
    }
    var start = 0;
    try { start = performance.now(); } catch (err) { start = 0; }
    requestAnimationFrame(function tick(t) {
      stamps.push(t);
      var elapsed = performance.now() - start;
      if (elapsed < budgetMs && stamps.length < 90) { requestAnimationFrame(tick); }
      else { finish(); }
    });
    setTimeout(finish, budgetMs + 600);
  }

  /* -------------------------------------------------------- environment */

  function withTimeout(promise, ms, fallback) {
    return new Promise(function (resolve) {
      var done = false;
      function settle(value) { if (!done) { done = true; resolve(value); } }
      setTimeout(function () { settle(fallback); }, ms);
      try {
        Promise.resolve(promise).then(settle, function () { settle(fallback); });
      } catch (err) { settle(fallback); }
    });
  }

  function probeMediaDevices() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) {
      return Promise.resolve({ media_device_count: null, media_device_kinds: "" });
    }
    return withTimeout(
      navigator.mediaDevices.enumerateDevices().then(function (list) {
        var kinds = {};
        list.forEach(function (d) { kinds[d.kind] = (kinds[d.kind] || 0) + 1; });
        return {
          media_device_count: list.length,
          media_device_kinds: Object.keys(kinds).map(function (k) {
            return k + ":" + kinds[k];
          }).join(",")
        };
      }),
      1200,
      { media_device_count: null, media_device_kinds: "" }
    );
  }

  /* The voice list often arrives after the first call returns empty. */
  function probeVoices() {
    return new Promise(function (resolve) {
      if (!window.speechSynthesis || !speechSynthesis.getVoices) {
        return resolve({ voice_count: null });
      }
      var deadline = 900;
      var waited = 0;
      function poll() {
        var voices = [];
        try { voices = speechSynthesis.getVoices() || []; } catch (err) { voices = []; }
        if (voices.length || waited >= deadline) {
          return resolve({ voice_count: voices.length });
        }
        waited += 150;
        setTimeout(poll, 150);
      }
      poll();
    });
  }

  /* Chrome ships licensed H.264 and AAC. The plain Chromium build that
     Puppeteer and Playwright download does not. */
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
        try { if (pc) { pc.close(); } } catch (err) { /* already closed */ }
        resolve({
          webrtc_supported: true,
          ice_candidate_count: candidates.length,
          ice_host_candidate: candidates.some(function (c) {
            return c.indexOf(" host ") !== -1 || c.indexOf("typ host") !== -1;
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
    var jobs = names.map(function (name) {
      return withTimeout(
        navigator.permissions.query({ name: name }).then(function (status) {
          return [name, status.state];
        }),
        800,
        null
      );
    });
    return Promise.all(jobs).then(function (pairs) {
      var out = {};
      pairs.forEach(function (pair) { if (pair) { out[pair[0]] = pair[1]; } });
      /* A headless browser answers denied here and default there at once. */
      var mismatch = false;
      try {
        mismatch = window.Notification && Notification.permission === "denied" &&
          out.notifications === "prompt";
      } catch (err) { mismatch = false; }
      return { permissions: out, permission_mismatch: !!mismatch };
    });
  }

  function probeStorage() {
    if (!navigator.storage || !navigator.storage.estimate) {
      return Promise.resolve({ storage_quota: null });
    }
    return withTimeout(
      navigator.storage.estimate().then(function (e) {
        return { storage_quota: e && typeof e.quota === "number" ? e.quota : null };
      }),
      900,
      { storage_quota: null }
    );
  }

  /* Count how many probe fonts render at a different size than the fallback.
     The span needs a body, so this runs in the second pass. */
  function countFonts() {
    var probes = ["Arial", "Verdana", "Times New Roman", "Courier New", "Georgia",
      "Trebuchet MS", "Comic Sans MS", "Impact", "Tahoma", "Segoe UI",
      "Helvetica Neue", "Cambria", "Consolas", "Palatino Linotype",
      "Lucida Console", "Franklin Gothic Medium", "Candara", "Optima",
      "Menlo", "Roboto"];
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
      var found = 0;
      for (i = 0; i < probes.length; i++) {
        for (var j = 0; j < base.length; j++) {
          span.style.fontFamily = "'" + probes[i] + "'," + base[j];
          if (span.offsetWidth !== control[base[j]][0] ||
              span.offsetHeight !== control[base[j]][1]) {
            found += 1;
            break;
          }
        }
      }
      document.body.removeChild(span);
      return found;
    } catch (err) { return null; }
  }

  /* ------------------------------------------------------------ reports */

  function snapshot() {
    var gl = readWebgl();
    return {
      world: "main",
      webdriver: navigator.webdriver === true,
      webdriver_descriptor: describe(navigator, "webdriver"),
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
      has_chrome_object: typeof window.chrome === "object" && window.chrome !== null,
      has_chrome_runtime: !!(window.chrome && window.chrome.runtime),
      pdf_viewer_enabled: navigator.pdfViewerEnabled === true,
      battery_api: typeof navigator.getBattery === "function",
      webgl_vendor: gl.vendor,
      webgl_renderer: gl.renderer,
      canvas_hash: canvasHash(),
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
      automation_keys: readAutomationKeys(),
      natives: {
        "Function.prototype.toString": nativeState(Function.prototype.toString),
        "navigator.permissions.query": nativeState(navigator.permissions && navigator.permissions.query),
        "WebGLRenderingContext.getParameter": nativeState(window.WebGLRenderingContext &&
          WebGLRenderingContext.prototype.getParameter),
        "HTMLCanvasElement.toDataURL": nativeState(HTMLCanvasElement.prototype.toDataURL),
        "Object.getOwnPropertyDescriptor": nativeState(Object.getOwnPropertyDescriptor),
        "Error.captureStackTrace": nativeState(Error.captureStackTrace)
      },
      runtime: syncRuntime(),
      error_stack_depth: (function () {
        try { return (new Error("botlab").stack || "").split("\n").length; }
        catch (err) { return 0; }
      })()
    };
  }

  function publish(name, value) {
    try {
      document.documentElement.setAttribute(name, JSON.stringify(value));
    } catch (err) { /* the document is not writable */ }
  }

  /* First pass. Everything that must be read before page script runs. */
  publish("data-botlab-main", snapshot());

  /* Second pass. The probes that need time, a body, or a promise. */
  function runSlowProbes() {
    var frames = new Promise(function (resolve) { measureFrames(700, resolve); });
    Promise.all([
      frames,
      probeMediaDevices(),
      probeVoices(),
      probeIce(),
      probePermissions(),
      probeStorage()
    ]).then(function (parts) {
      var frameStats = parts[0];
      var permissions = parts[4];
      publish("data-botlab-main-async", {
        runtime: {
          frame_count: frameStats.frame_count,
          frame_mean_ms: frameStats.frame_mean_ms,
          frame_stdev_ms: frameStats.frame_stdev_ms,
          visibility: document.visibilityState || "unknown"
        },
        environment: Object.assign(
          {},
          parts[1],
          parts[2],
          parts[3],
          { permissions: permissions.permissions },
          parts[5],
          {
            codecs: probeCodecs(),
            pdf_viewer_enabled: navigator.pdfViewerEnabled === true,
            battery_api: typeof navigator.getBattery === "function",
            gamepad_api: typeof navigator.getGamepads === "function",
            font_api: !!document.fonts
          }
        ),
        font_count: countFonts(),
        permission_mismatch: permissions.permission_mismatch
      });
      try {
        document.dispatchEvent(new CustomEvent("botlab-main-async"));
      } catch (err) { /* the isolated world falls back to polling */ }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", runSlowProbes, { once: true });
  } else {
    runSlowProbes();
  }
})();
