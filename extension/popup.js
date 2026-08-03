/* Draw the last result for the active tab and hold the harness settings. */

import { LAYERS } from "./scorer.js";

const $ = (id) => document.getElementById(id);

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

function colorFor(score) {
  if (score <= 10) { return "var(--bot)"; }
  if (score <= 30) { return "var(--warn)"; }
  if (score <= 60) { return "var(--ink)"; }
  return "var(--human)";
}

function drawLadder(layers, earliest) {
  const host = $("ladder");
  host.innerHTML = "";
  let peak = 4;
  LAYERS.forEach((name) => {
    peak = Math.max(peak, Math.abs((layers[name] || {}).weight || 0));
  });
  LAYERS.forEach((name) => {
    const weight = (layers[name] || {}).weight || 0;
    const pct = Math.min(50, (Math.abs(weight) / peak) * 50);
    const row = document.createElement("div");
    row.className = "row";
    row.innerHTML =
      `<div class="n${name === earliest ? " hit" : ""}">${name}</div>` +
      `<div class="axis"><div class="z"></div><div class="b" style="background:${
        weight >= 0 ? "var(--bot)" : "var(--human)"};left:${
        weight >= 0 ? 50 : 50 - pct}%;width:${pct}%"></div></div>` +
      `<div class="v">${weight > 0 ? "+" : ""}${weight.toFixed(1)}</div>`;
    host.appendChild(row);
  });
}

function drawDivergences(list) {
  const host = $("divergences");
  host.innerHTML = "";
  if (!list || !list.length) {
    host.innerHTML = '<div class="clean">Both worlds report the same values. ' +
      'The harness found no stealth patch.</div>';
    return;
  }
  list.forEach((d) => {
    const box = document.createElement("div");
    box.className = "div";
    box.innerHTML = `<div class="f">${d.field}</div>` +
      `<div class="d">page sees: ${d.main}</div>` +
      `<div class="d">browser reports: ${d.isolated}</div>`;
    host.appendChild(box);
  });
}

function drawSignals(signals) {
  const host = $("signals");
  host.innerHTML = "";
  if (!signals || !signals.length) {
    host.innerHTML = "<li>The scorer produced no signals.</li>";
    return;
  }
  signals.forEach((s) => {
    const li = document.createElement("li");
    li.className = s.weight > 0 ? "bot" : "human";
    li.innerHTML = `<code>${s.id}  ${s.weight > 0 ? "+" : ""}${s.weight}</code>${s.detail}`;
    host.appendChild(li);
  });
}

function drawResult(record) {
  if (!record) {
    $("host").textContent = "This tab has no report. Reload the page.";
    return;
  }
  const r = record.result;
  $("host").textContent = record.url;
  $("score").textContent = r.score;
  $("score").style.color = colorFor(r.score);
  $("verdict").textContent = r.verdict;
  $("needle").style.left = `${((r.score - 1) / 98) * 100}%`;
  drawDivergences(record.divergences);
  drawLadder(r.layers, r.first_catching_layer);
  drawSignals(r.signals);
  if (record.delivery && record.delivery.sent) {
    $("status").textContent = `Harness score with the TLS layer: ${record.delivery.serverScore}.`;
  } else if (record.delivery && record.delivery.reason) {
    $("status").textContent = record.delivery.reason;
  }
}

async function load() {
  const stored = await chrome.storage.local.get(["harnessUrl", "runLabel", "autoSend"]);
  $("harness").value = stored.harnessUrl || "";
  $("label").value = stored.runLabel || "";
  $("auto").checked = stored.autoSend === true;

  const tab = await activeTab();
  if (!tab) { return; }
  chrome.runtime.sendMessage({ type: "botlab-get-result", tabId: tab.id }, drawResult);
}

$("harness").addEventListener("change", (e) => {
  chrome.storage.local.set({ harnessUrl: e.target.value.trim() });
});
$("label").addEventListener("change", (e) => {
  chrome.storage.local.set({ runLabel: e.target.value.trim() });
});
$("auto").addEventListener("change", (e) => {
  chrome.storage.local.set({ autoSend: e.target.checked });
});

$("report").addEventListener("click", async () => {
  const tab = await activeTab();
  const target = tab ? `report.html?tab=${tab.id}` : "report.html";
  await chrome.tabs.create({ url: chrome.runtime.getURL(target) });
  window.close();
});

$("measure").addEventListener("click", async () => {
  const tab = await activeTab();
  chrome.tabs.sendMessage(tab.id, { type: "botlab-collect-now" }, () => {
    void chrome.runtime.lastError;
    setTimeout(load, 500);
  });
});

$("send").addEventListener("click", async () => {
  const tab = await activeTab();
  $("status").textContent = "Sending the report.";
  chrome.runtime.sendMessage({ type: "botlab-send-now", tabId: tab.id }, (delivery) => {
    if (delivery && delivery.sent) {
      $("status").textContent = `Harness score with the TLS layer: ${delivery.serverScore}.`;
    } else {
      $("status").textContent = (delivery && delivery.reason) || "The harness did not answer.";
    }
  });
});

$("export").addEventListener("click", async () => {
  const history = (await chrome.storage.local.get("history")).history || [];
  if (!history.length) { $("status").textContent = "The history is empty."; return; }
  const columns = ["time", "label", "score", "verdict", "earliest", "divergences", "url"];
  const rows = [columns.join(",")].concat(history.map((h) =>
    columns.map((c) => `"${String(h[c] === undefined ? "" : h[c]).replace(/"/g, '""')}"`).join(",")));
  const blob = new Blob([rows.join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  await chrome.tabs.create({ url });
  $("status").textContent = `Exported ${history.length} rows.`;
});

load();
