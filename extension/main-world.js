/* Run in the main world. Record the values that a website reads.

   A stealth plugin patches this world, because this is where page code runs.
   The isolated world reads the same properties without those patches.
   The difference between the two reports is the evidence. */

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
      webgl_vendor: gl.vendor,
      webgl_renderer: gl.renderer,
      screen_width: screen.width,
      screen_height: screen.height,
      outer_width: window.outerWidth,
      outer_height: window.outerHeight,
      timezone: (Intl.DateTimeFormat().resolvedOptions() || {}).timeZone || "",
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
      error_stack_depth: (function () {
        try { return (new Error("botlab").stack || "").split("\n").length; }
        catch (err) { return 0; }
      })()
    };
  }

  /* Publish the report on an attribute. The isolated world reads it later.
     An attribute avoids a race between two scripts that start together. */
  try {
    document.documentElement.setAttribute(
      "data-botlab-main", JSON.stringify(snapshot()));
  } catch (err) { /* the document is not ready */ }
})();
