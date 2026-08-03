/* Score a report inside the browser.

   The extension cannot read a TLS handshake and cannot see its own source
   address, so it scores seven of the nine layers. Send the report to the
   harness and the server adds the tls and network layers to these.

   The order below is the order a production stack meets a client, so the
   first layer with a positive signal is the one that would have caught it. */

export const LAYERS = ["http", "browser", "worlds", "runtime", "environment",
  "behavior", "consistency"];

/* Plain-language descriptions, shown when the reader hovers a layer name in
   the popup or the report. The two harness-only layers are here too, because
   the report lists them even when nothing measured them. */
export const LAYER_INFO = {
  network:
    "Where the request came from. A datacentre address is a weaker sign than a " +
    "home connection. Only the harness can read this.",
  tls:
    "The handshake your browser performs before it says a word. Every browser " +
    "has a distinctive one, and copying headers does not change it. Only the " +
    "harness can read this.",
  http:
    "The headers your browser sent, and the order it sent them in. Real Chrome " +
    "uses a fixed order that most tools get wrong.",
  browser:
    "What a website can see: window size, graphics card, fonts, plugins, canvas. " +
    "Automated browsers leave gaps here.",
  worlds:
    "The same questions asked twice, once the way a website would ask and once " +
    "through a channel a bot cannot reach. Different answers mean something is " +
    "wearing a disguise.",
  runtime:
    "How the JavaScript engine behaves, rather than what it claims. Catches a " +
    "debugger attached to the page and patches that rewrote the browser's own " +
    "functions.",
  environment:
    "What the machine actually has: camera, microphone, system voices, video " +
    "codecs, a working network. A disguise cannot install hardware.",
  behavior:
    "Mouse path, typing rhythm, and whether events came from a hand or a script. " +
    "Straight lines and perfectly even timing are not human.",
  consistency:
    "Every claim checked against every other. A client can pass one layer; it " +
    "struggles when two layers tell different stories about the same machine."
};

const SOFTWARE_RENDERERS = [
  "swiftshader", "llvmpipe", "software rasterizer", "mesa offscreen",
  "virgl", "microsoft basic render"
];

const CHROMIUM_REQUIRED_HEADERS = [
  "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform",
  "sec-fetch-site", "sec-fetch-mode", "sec-fetch-dest", "accept-language"
];

const CHROME_HEADER_ORDER = [
  "host", "connection", "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform",
  "upgrade-insecure-requests", "user-agent", "accept", "sec-fetch-site",
  "sec-fetch-mode", "sec-fetch-user", "sec-fetch-dest", "accept-encoding",
  "accept-language"
];

function signal(layer, id, weight, detail) {
  return { layer, id, weight, detail };
}

function orderDistance(seen, canonical) {
  const index = new Map(canonical.map((name, pos) => [name, pos]));
  const kept = seen.filter((n) => index.has(n)).map((n) => index.get(n));
  if (kept.length < 2) { return 1; }
  let wrong = 0;
  let total = 0;
  for (let i = 0; i < kept.length; i += 1) {
    for (let j = i + 1; j < kept.length; j += 1) {
      total += 1;
      if (kept[i] > kept[j]) { wrong += 1; }
    }
  }
  return total ? wrong / total : 1;
}

function pathStraightness(points) {
  if (points.length < 3) { return null; }
  let traveled = 0;
  for (let i = 1; i < points.length; i += 1) {
    traveled += Math.hypot(points[i].x - points[i - 1].x, points[i].y - points[i - 1].y);
  }
  if (traveled === 0) { return null; }
  const direct = Math.hypot(
    points[points.length - 1].x - points[0].x,
    points[points.length - 1].y - points[0].y
  );
  return direct / traveled;
}

function spread(values) {
  if (values.length < 2) { return null; }
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  const variance = values.reduce((a, b) => a + (b - mean) ** 2, 0) / values.length;
  return Math.sqrt(variance);
}

function scoreHttp(headerOrder, headers) {
  const out = [];
  if (!headerOrder || !headerOrder.length) { return out; }
  const missing = CHROMIUM_REQUIRED_HEADERS.filter((h) => !(h in headers));
  if (missing.length) {
    out.push(signal("http", "http.missing_chromium_headers", 0.5 * missing.length,
      `A Chromium browser sends every client hint. This request omitted ${missing.join(", ")}.`));
  }
  const distance = orderDistance(headerOrder, CHROME_HEADER_ORDER);
  if (distance > 0.25) {
    out.push(signal("http", "http.header_order_mismatch", 1.4,
      `The header order does not match Chrome. Distance ${distance.toFixed(2)}.`));
  } else if (distance === 0) {
    out.push(signal("http", "http.header_order_match", -0.7,
      "The header order matches Chrome."));
  }
  return out;
}

function scoreBrowser(main) {
  const out = [];
  if (!main) {
    return [signal("browser", "browser.no_main_world_report", 1.5,
      "The main world script produced no report.")];
  }
  if (main.webdriver) {
    out.push(signal("browser", "browser.webdriver_flag", 2.6,
      "The navigator.webdriver flag is true in the main world."));
  }
  if (main.webdriver_descriptor === "patched-getter") {
    out.push(signal("browser", "browser.patched_webdriver_getter", 2.5,
      "The navigator.webdriver getter is not native code. A stealth patch replaced it."));
  }
  if ((main.automation_keys || []).length) {
    out.push(signal("browser", "browser.automation_globals", 2.8,
      `The page holds automation properties: ${main.automation_keys.slice(0, 4).join(", ")}.`));
  }
  const renderer = (main.webgl_renderer || "").toLowerCase();
  if (!renderer) {
    out.push(signal("browser", "browser.no_webgl", 1.3, "WebGL returned no renderer name."));
  } else if (SOFTWARE_RENDERERS.some((m) => renderer.includes(m))) {
    out.push(signal("browser", "browser.software_renderer", 1.9,
      `The WebGL renderer is a software rasterizer: ${main.webgl_renderer}.`));
  }
  const patched = Object.entries(main.natives || {})
    .filter(([, state]) => state === "patched").map(([name]) => name);
  if (patched.length) {
    out.push(signal("browser", "browser.patched_natives", 2.4,
      `A native function is not native code: ${patched.join(", ")}.`));
  }
  if (main.outer_width === 0 || main.outer_height === 0) {
    out.push(signal("browser", "browser.zero_outer_window", 1.6,
      "The outer window size is zero. A headless window reports this."));
  }
  if (!main.has_chrome_object) {
    out.push(signal("browser", "browser.missing_chrome_object", 1.5,
      "The window.chrome object is absent in a Chromium browser."));
  }
  if (main.plugin_count === 0) {
    out.push(signal("browser", "browser.no_plugins", 0.8,
      "The browser reports no plugins. A desktop Chrome reports several."));
  }
  if ([0, 1].includes(main.hardware_concurrency)) {
    out.push(signal("browser", "browser.low_concurrency", 0.7,
      "The browser reports one CPU thread or none."));
  }
  if (main.permission_mismatch) {
    out.push(signal("browser", "browser.permission_mismatch", 1.7,
      "The Permissions API and Notification.permission disagree."));
  }
  if (typeof main.font_count === "number" && main.font_count < 8) {
    out.push(signal("browser", "browser.few_fonts", 1.1,
      `The client resolved ${main.font_count} fonts. A desktop install resolves many more.`));
  }
  if (!main.canvas_hash || main.canvas_hash === "0") {
    out.push(signal("browser", "browser.no_canvas", 1.2, "Canvas rendering returned nothing."));
  } else {
    out.push(signal("browser", "browser.canvas_present", -0.4, "Canvas returned a stable hash."));
  }
  return out;
}

/* Read how the engine behaves, not what it claims. A client that rewrites
   every property still fails here unless it also rebuilds the engine. */
function scoreRuntime(runtime) {
  const out = [];
  if (!runtime || !Object.keys(runtime).length) { return out; }

  if (runtime.cdp_runtime_enabled) {
    out.push(signal("runtime", "runtime.cdp_attached", 2.9,
      "Logging an Error read its stack getter. A Chrome DevTools Protocol client " +
      "is attached. An open DevTools window reads it the same way, so record " +
      "whether one was open."));
  }
  if (runtime.webdriver_own_property) {
    out.push(signal("runtime", "runtime.webdriver_relocated", 2.8,
      "navigator.webdriver is an own property of the instance. Chrome defines it " +
      "on Navigator.prototype. A patch moved it."));
  } else if (runtime.webdriver_on_prototype === false) {
    out.push(signal("runtime", "runtime.webdriver_deleted", 1.8,
      "Navigator.prototype carries no webdriver property at all. A patch deleted it."));
  }
  if ((runtime.stack_markers || []).length) {
    out.push(signal("runtime", "runtime.injected_stack", 3.0,
      `A stack trace names an injected script: ${runtime.stack_markers.slice(0, 3).join(", ")}.`));
  }
  if (runtime.prepare_stack_trace_set) {
    out.push(signal("runtime", "runtime.prepare_stack_trace_set", 2.6,
      "Error.prepareStackTrace is defined. Chrome leaves it undefined. A stealth " +
      "plugin sets it to scrub its own frames from traces."));
  }
  if (runtime.tostring_chain_native === false) {
    out.push(signal("runtime", "runtime.tostring_chain_patched", 2.6,
      "Function.prototype.toString has itself been replaced. A stealth patch hides " +
      "other patches and forgets to hide this one."));
  }

  /* A hidden tab throttles its frame clock to nothing, so a real browser in a
     background tab looks like a window with no compositor. Read these only
     when the page was visible while they were measured. */
  const visible = runtime.visibility === undefined ||
    runtime.visibility === "visible" || runtime.visibility === "unknown";
  if (!visible) {
    out.push(signal("runtime", "runtime.frame_clock_not_measured", 0,
      "The page was hidden during the probe. The frame clock says nothing here."));
  } else if (runtime.frame_count === 0) {
    out.push(signal("runtime", "runtime.no_animation_frame", 1.7,
      "requestAnimationFrame never fired. A window with no compositor reports this."));
  } else if (runtime.frame_count) {
    if (runtime.frame_stdev_ms !== null && runtime.frame_stdev_ms < 0.2) {
      out.push(signal("runtime", "runtime.synthetic_frame_clock", 0.8,
        `The frame interval never varies. Spread ${runtime.frame_stdev_ms} ms. A display ` +
        "refresh jitters; a generated clock does not."));
    } else {
      out.push(signal("runtime", "runtime.frame_clock_present", -0.5,
        "The frame clock runs and jitters as a display does."));
    }
  }
  return out;
}

/* A stealth patch rewrites what the browser says. It does not install a sound
   card, a camera, a voice pack, or a licensed codec. */
function scoreEnvironment(environment, main) {
  const out = [];
  if (!environment) { return out; }
  const ua = ((main && main.user_agent) || "").toLowerCase();
  const isChrome = ua.includes("chrome/") || ua.includes("chromium") || ua.includes("edg/");

  if (environment.media_device_count === 0) {
    out.push(signal("environment", "environment.no_media_devices", 1.6,
      "The browser enumerated no camera and no microphone. A desktop install " +
      "reports at least one."));
  } else if (environment.media_device_count) {
    out.push(signal("environment", "environment.media_devices_present", -0.5,
      `The browser enumerated ${environment.media_device_count} media devices.`));
  }

  if (environment.voice_count === 0) {
    out.push(signal("environment", "environment.no_speech_voices", 1.3,
      "The speech synthesizer holds no voices. A desktop install carries the " +
      "system voice pack."));
  } else if (environment.voice_count) {
    out.push(signal("environment", "environment.speech_voices_present", -0.4,
      `The speech synthesizer holds ${environment.voice_count} voices.`));
  }

  const codecs = environment.codecs || {};
  if (Object.keys(codecs).length && !codecs.h264) {
    out.push(signal("environment", "environment.no_proprietary_codecs", 2.2,
      "The build cannot play H.264. Chrome ships the licensed codecs. The plain " +
      "Chromium build that automation downloads does not."));
  } else if (codecs.h264) {
    out.push(signal("environment", "environment.proprietary_codecs_present", -0.6,
      "The build plays H.264, as a released Chrome does."));
  }

  if (isChrome && environment.pdf_viewer_enabled === false) {
    out.push(signal("environment", "environment.no_pdf_viewer", 1.2,
      "navigator.pdfViewerEnabled is false. Desktop Chrome ships the PDF viewer " +
      "and reports true."));
  }
  if (isChrome && environment.battery_api === false) {
    out.push(signal("environment", "environment.no_battery_api", 0.9,
      "navigator.getBattery is absent. Desktop Chrome exposes it."));
  }

  if (environment.ice_candidate_count === 0 && environment.webrtc_supported) {
    out.push(signal("environment", "environment.no_ice_candidates", 1.4,
      "WebRTC gathering finished with no candidate. The host has no reachable " +
      "network interface."));
  } else if (environment.ice_candidate_count) {
    out.push(signal("environment", "environment.ice_candidates_present", -0.4,
      `WebRTC gathered ${environment.ice_candidate_count} candidates.`));
  }

  if (environment.storage_quota === 0) {
    out.push(signal("environment", "environment.no_storage_quota", 0.7,
      "The origin was granted no storage quota."));
  }

  const states = Object.values(environment.permissions || {});
  if (states.length >= 3 && states.every((s) => s === "denied")) {
    out.push(signal("environment", "environment.all_permissions_denied", 1.0,
      "Every queried permission returned denied. A headless profile answers this way."));
  }
  return out;
}

function scoreBehavior(behavior) {
  const out = [];
  if (!behavior) { return out; }
  if (behavior.untrusted_events > 0) {
    out.push(signal("behavior", "behavior.untrusted_events", 2.9,
      `${behavior.untrusted_events} events carried isTrusted false. A script dispatched them.`));
  }
  const scrolls = behavior.scroll_deltas || [];
  if (scrolls.length >= 4 && new Set(scrolls).size === 1) {
    out.push(signal("behavior", "behavior.uniform_scroll", 1.4,
      `Every wheel event carried the same delta of ${scrolls[0]}. A wheel emits a varying delta.`));
  }
  if (behavior.clicks > 0 && behavior.mouse.length < 3) {
    out.push(signal("behavior", "behavior.click_without_move", 2.2,
      "The client clicked without moving the pointer first."));
  }
  if (behavior.mouse.length >= 3) {
    const straight = pathStraightness(behavior.mouse);
    if (straight !== null && straight > 0.97) {
      out.push(signal("behavior", "behavior.linear_path", 2.0,
        `The pointer path is a straight line. Ratio ${straight.toFixed(3)}.`));
    } else if (straight !== null && straight < 0.85) {
      out.push(signal("behavior", "behavior.human_path_curvature", -0.9,
        `The pointer path curves as a hand does. Ratio ${straight.toFixed(3)}.`));
    }
    const deltas = [];
    for (let i = 1; i < behavior.mouse.length; i += 1) {
      const d = behavior.mouse[i].t - behavior.mouse[i - 1].t;
      if (d > 0) { deltas.push(d); }
    }
    if (deltas.length >= 5) {
      const s = spread(deltas);
      if (s !== null && s < 1.5) {
        out.push(signal("behavior", "behavior.uniform_timing", 1.8,
          `The pointer events arrive on a fixed clock. Spread ${s.toFixed(2)} ms.`));
      }
      if (new Set(deltas.map(Math.round)).size <= 2) {
        out.push(signal("behavior", "behavior.quantized_timing", 1.5,
          "The pointer events use two distinct intervals or fewer."));
      }
    }
  }
  if (behavior.key_intervals.length >= 4) {
    const s = spread(behavior.key_intervals);
    if (s !== null && s < 5) {
      out.push(signal("behavior", "behavior.uniform_keystrokes", 1.6,
        `The keystroke intervals are near constant. Spread ${s.toFixed(2)} ms.`));
    }
  }
  if (behavior.first_interaction_ms !== null && behavior.first_interaction_ms < 60) {
    out.push(signal("behavior", "behavior.instant_interaction", 1.4,
      `The first interaction came ${behavior.first_interaction_ms} ms after load.`));
  }
  return out;
}

/* The layer that only an extension can measure. */
function scoreWorlds(divergences) {
  const out = [];
  if (!divergences) { return out; }
  if (!divergences.length) {
    out.push(signal("worlds", "worlds.no_divergence", -1.2,
      "The main world and the isolated world report the same values."));
    return out;
  }
  divergences.forEach((d) => {
    const strong = d.field === "webdriver" || d.field.startsWith("native:");
    out.push(signal("worlds", `worlds.divergence.${d.field}`, strong ? 3.2 : 2.0,
      `The page sees ${d.field} as ${d.main}. The browser reports ${d.isolated}.`));
  });
  return out;
}

function scoreConsistency(main, headers) {
  const out = [];
  if (!main) { return out; }
  const ua = (main.user_agent || "").toLowerCase();
  const platform = (main.platform || "").toLowerCase();

  let claimed = "unknown";
  if (ua.includes("windows")) { claimed = "windows"; }
  else if (ua.includes("android")) { claimed = "android"; }
  else if (ua.includes("iphone") || ua.includes("ipad")) { claimed = "ios"; }
  else if (ua.includes("mac os x")) { claimed = "macos"; }
  else if (ua.includes("linux")) { claimed = "linux"; }

  let reported = "unknown";
  if (platform.includes("win")) { reported = "windows"; }
  else if (platform.includes("mac")) { reported = "macos"; }
  else if (platform.includes("linux") || platform.includes("x11")) { reported = "linux"; }
  else if (platform.includes("android")) { reported = "android"; }

  if (claimed !== "unknown" && reported !== "unknown" && claimed !== reported) {
    out.push(signal("consistency", "consistency.platform_mismatch", 2.7,
      `The User-Agent claims ${claimed}. navigator.platform reports ${reported}.`));
  }

  const hint = (headers["sec-ch-ua-platform"] || "").replace(/"/g, "").toLowerCase();
  if (hint && claimed !== "unknown" && !hint.replace(/\s/g, "").includes(claimed.slice(0, 3))) {
    out.push(signal("consistency", "consistency.client_hint_mismatch", 2.2,
      `Sec-CH-UA-Platform says ${hint}. The User-Agent says ${claimed}.`));
  }

  const mobile = ua.includes("mobile") || ua.includes("android") || ua.includes("iphone");
  if (mobile && main.screen_width > 1200) {
    out.push(signal("consistency", "consistency.mobile_ua_desktop_screen", 2.3,
      `The User-Agent claims a mobile device. The screen is ${main.screen_width} pixels wide.`));
  }
  if (mobile && main.max_touch_points === 0) {
    out.push(signal("consistency", "consistency.mobile_without_touch", 1.9,
      "The User-Agent claims a mobile device that reports no touch points."));
  }

  const headerLang = (headers["accept-language"] || "").split(",")[0].trim().toLowerCase();
  const jsLang = (main.language || "").toLowerCase();
  if (headerLang && jsLang && headerLang.split("-")[0] !== jsLang.split("-")[0]) {
    out.push(signal("consistency", "consistency.language_mismatch", 1.3,
      `Accept-Language says ${headerLang}. navigator.language says ${jsLang}.`));
  }
  return out;
}

export function evaluateReport(report, request) {
  const headers = (request && request.headers) || {};
  const order = (request && request.order) || [];

  const signals = [
    ...scoreHttp(order, headers),
    ...scoreBrowser(report.main_world),
    ...scoreWorlds(report.divergences),
    ...scoreRuntime(report.runtime),
    ...scoreEnvironment(report.environment, report.main_world),
    ...scoreBehavior(report.behavior),
    ...scoreConsistency(report.main_world, headers)
  ];

  const total = signals.reduce((sum, s) => sum + s.weight, 0);
  const probability = 1 / (1 + Math.exp(-(total - 1)));
  const score = Math.max(1, Math.min(99, Math.round(99 * (1 - probability))));

  const layers = {};
  LAYERS.forEach((name) => {
    const rows = signals.filter((s) => s.layer === name);
    layers[name] = {
      weight: Number(rows.reduce((sum, s) => sum + s.weight, 0).toFixed(3)),
      count: rows.length,
      ids: rows.filter((s) => s.weight > 0).map((s) => s.id)
    };
  });

  const earliest = LAYERS.find((name) => layers[name].ids.length) || null;
  const positive = signals.filter((s) => s.weight > 0);
  const strongest = positive.length
    ? positive.reduce((a, b) => (b.weight > a.weight ? b : a)).layer : null;

  let verdict = "likely human";
  if (score <= 10) { verdict = "automated"; }
  else if (score <= 30) { verdict = "likely automated"; }
  else if (score <= 60) { verdict = "unclear"; }

  return {
    score,
    verdict,
    total_weight: Number(total.toFixed(3)),
    first_catching_layer: earliest,
    strongest_layer: strongest,
    layers,
    signals: signals.sort((a, b) => b.weight - a.weight)
  };
}
