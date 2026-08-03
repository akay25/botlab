/* Record the outgoing request headers, score each report, and keep the result.

   The service worker observes headers. It does not change them. The extension
   measures the browser. It never modifies a request. */

import { evaluateReport, LAYERS } from "./scorer.js";

const REQUESTS = new Map();   /* tab id -> the headers of the last top-level request */
const RESULTS = new Map();    /* tab id -> the last scored result */

/* Record the header order of every top-level navigation. */
chrome.webRequest.onSendHeaders.addListener(
  (details) => {
    if (details.type !== "main_frame" || details.tabId < 0) { return; }
    const order = [];
    const headers = {};
    (details.requestHeaders || []).forEach((h) => {
      const name = h.name.toLowerCase();
      order.push(name);
      headers[name] = h.value || "";
    });
    REQUESTS.set(details.tabId, { url: details.url, order, headers });
  },
  { urls: ["<all_urls>"] },
  ["requestHeaders"]
);

async function settings() {
  const stored = await chrome.storage.local.get(["harnessUrl", "runLabel", "autoSend"]);
  return {
    harnessUrl: stored.harnessUrl || "",
    runLabel: stored.runLabel || "",
    autoSend: stored.autoSend === true
  };
}

function paintBadge(tabId, result) {
  let color = "#1f5c8c";
  if (result.score <= 10) { color = "#b4331f"; }
  else if (result.score <= 30) { color = "#c67a12"; }
  else if (result.score <= 60) { color = "#6f6c62"; }
  chrome.action.setBadgeText({ tabId, text: String(result.score) });
  chrome.action.setBadgeBackgroundColor({ tabId, color });
}

/* Send the report to the harness so the server can add the tls and network
   layers. Every field below is measured. The harness scores a session on
   what it receives, so a placeholder here would become a false result. */
async function forward(report, config, request) {
  if (!config.harnessUrl) { return { sent: false, reason: "No harness URL is set." }; }
  const main = report.main_world || {};
  const payload = {
    /* The harness must score the page navigation, not this fetch. */
    request: request ? { url: request.url, order: request.order, headers: request.headers } : null,
    reason: report.reason || "extension",
    label: config.runLabel,
    source: "extension",
    page_url: report.url,
    extension: {
      divergences: report.divergences,
      isolated_world: report.isolated_world,
      page_url: report.url
    },
    js: {
      webdriver: main.webdriver,
      automation_keys: main.automation_keys || [],
      patched_natives: Object.entries(main.natives || {})
        .filter(([, s]) => s === "patched").map(([n]) => n),
      webgl_vendor: main.webgl_vendor,
      webgl_renderer: main.webgl_renderer,
      canvas_hash: main.canvas_hash,
      font_count: main.font_count,
      permission_mismatch: main.permission_mismatch === true,
      has_chrome_object: main.has_chrome_object,
      plugin_count: main.plugin_count,
      platform: main.platform,
      language: main.language,
      hardware_concurrency: main.hardware_concurrency,
      device_memory: main.device_memory,
      max_touch_points: main.max_touch_points,
      screen_width: main.screen_width,
      screen_height: main.screen_height,
      outer_width: main.outer_width,
      outer_height: main.outer_height,
      timezone: main.timezone,
      user_agent: main.user_agent
    },
    runtime: report.runtime || null,
    environment: report.environment || null,
    behavior: report.behavior
  };
  try {
    const response = await fetch(config.harnessUrl.replace(/\/$/, "") + "/collect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const serverResult = await response.json();
    return { sent: true, serverScore: serverResult.score, serverResult };
  } catch (error) {
    return { sent: false, reason: "The harness did not answer. Check the URL." };
  }
}

chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (message && message.type === "botlab-report") {
    const tabId = sender.tab ? sender.tab.id : -1;
    const request = REQUESTS.get(tabId) || null;
    const result = evaluateReport(message.report, request);

    (async () => {
      const config = await settings();
      let delivery = { sent: false, reason: "Automatic sending is off." };
      if (config.autoSend) { delivery = await forward(message.report, config, request); }
      const record = {
        tabId,
        report: message.report,
        url: message.report.url,
        time: message.report.collected_at,
        label: config.runLabel,
        result,
        divergences: message.report.divergences,
        request,
        delivery
      };
      RESULTS.set(tabId, record);
      paintBadge(tabId, result);

      /* The service worker sleeps and takes RESULTS with it. Keep the last
         record on disk so the report page still has something to render. */
      const history = (await chrome.storage.local.get("history")).history || [];
      history.unshift({
        time: record.time, url: record.url, label: record.label,
        score: result.score, verdict: result.verdict,
        earliest: result.first_catching_layer,
        strongest: result.strongest_layer,
        total_weight: result.total_weight,
        harness_score: delivery.sent ? delivery.serverScore : "",
        detection_ids: LAYERS.flatMap((n) => (result.layers[n] || {}).ids || []).join(" "),
        divergences: (message.report.divergences || []).map((d) => d.field).join(" ")
      });
      await chrome.storage.local.set({
        history: history.slice(0, 300),
        lastRecord: record
      });
      reply({ ok: true, score: result.score });
    })();
    return true;
  }

  if (message && message.type === "botlab-get-result") {
    (async () => {
      const live = RESULTS.get(message.tabId);
      if (live) { reply(live); return; }
      /* The worker may have restarted since the report arrived. */
      const stored = (await chrome.storage.local.get("lastRecord")).lastRecord || null;
      reply(stored && (message.tabId === undefined || stored.tabId === message.tabId)
        ? stored : null);
    })();
    return true;
  }

  if (message && message.type === "botlab-send-now") {
    (async () => {
      const config = await settings();
      const record = RESULTS.get(message.tabId);
      if (!record) { reply({ sent: false, reason: "No report exists for this tab." }); return; }
      const delivery = await forward(record.report, config, record.request);
      record.delivery = delivery;
      RESULTS.set(message.tabId, record);
      await chrome.storage.local.set({ lastRecord: record });
      reply(delivery);
    })();
    return true;
  }
  return false;
});

chrome.tabs.onRemoved.addListener((tabId) => {
  REQUESTS.delete(tabId);
  RESULTS.delete(tabId);
});
