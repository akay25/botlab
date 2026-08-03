/* Render the full detection report for one measured browser instance.

   The popup shows the verdict. This page shows the evidence behind it: every
   signal with its detection ID and weight, both world snapshots side by side,
   the raw probe output, and the header order the browser actually sent. */

import { LAYERS, LAYER_INFO } from "./scorer.js";

/* The two layers only the harness can measure sit ahead of the local ones,
   because a production stack meets a client in this order. */
const SERVER_ONLY = ["network", "tls"];
const ALL_LAYERS = [...SERVER_ONLY, ...LAYERS];

const $ = (id) => document.getElementById(id);
const text = (value) => (value === undefined || value === null || value === ""
  ? "—" : String(value));

function colorFor(score) {
  if (score <= 10) { return "var(--bot)"; }
  if (score <= 30) { return "var(--warn)"; }
  if (score <= 60) { return "var(--ink)"; }
  return "var(--human)";
}

function row(cells, className) {
  const tr = document.createElement("tr");
  cells.forEach((cell, index) => {
    const td = document.createElement("td");
    if (index === 0) { td.className = "k"; }
    if (className && index > 0) { td.className = className; }
    td.textContent = cell;
    tr.appendChild(td);
  });
  return tr;
}

function fillTable(id, pairs, emptyNote) {
  const body = $(id).querySelector("tbody");
  body.innerHTML = "";
  if (!pairs.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 3;
    td.textContent = emptyNote;
    tr.appendChild(td);
    body.appendChild(tr);
    return;
  }
  pairs.forEach((pair) => body.appendChild(row(pair)));
}

/* Flatten a probe object so nested maps read as one key per line. */
function flatten(source, prefix = "") {
  const out = [];
  Object.entries(source || {}).forEach(([key, value]) => {
    const name = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === "object" && !Array.isArray(value)) {
      out.push(...flatten(value, name));
    } else if (Array.isArray(value)) {
      out.push([name, value.length ? value.join(", ") : "—"]);
    } else {
      out.push([name, text(value)]);
    }
  });
  return out;
}

function drawLadder(local, server) {
  const host = $("ladder");
  host.innerHTML = "";
  let peak = 4;
  ALL_LAYERS.forEach((name) => {
    const entry = server[name] || local[name];
    peak = Math.max(peak, Math.abs((entry || {}).weight || 0));
  });

  ALL_LAYERS.forEach((name) => {
    const fromServer = Object.prototype.hasOwnProperty.call(server, name);
    const entry = fromServer ? server[name] : local[name];
    const div = document.createElement("div");
    div.className = "row";

    const label = document.createElement("div");
    label.textContent = name;
    label.className = "n";
    if (LAYER_INFO[name]) {
      label.setAttribute("data-tip", LAYER_INFO[name]);
      label.setAttribute("tabindex", "0");
    }

    const axis = document.createElement("div");
    axis.className = "axis";
    const value = document.createElement("div");
    value.className = "v";
    const source = document.createElement("div");
    source.className = "src";

    if (!entry) {
      label.className = "n off";
      axis.innerHTML = '<div class="z"></div>';
      value.textContent = "—";
      source.textContent = "not measured";
    } else {
      const weight = entry.weight || 0;
      const pct = Math.min(50, (Math.abs(weight) / peak) * 50);
      if ((entry.ids || []).length) { label.className = "n hit"; }
      axis.innerHTML = '<div class="z"></div>' +
        `<div class="b" style="background:${weight >= 0 ? "var(--bot)" : "var(--human)"};` +
        `left:${weight >= 0 ? 50 : 50 - pct}%;width:${pct}%"></div>`;
      value.textContent = `${weight > 0 ? "+" : ""}${weight.toFixed(1)}`;
      source.textContent = fromServer ? "harness" : "extension";
    }

    div.append(label, axis, value, source);
    host.appendChild(div);
  });
}

function drawSignals(signals) {
  const host = $("signals");
  host.innerHTML = "";
  if (!signals || !signals.length) {
    host.innerHTML = '<div class="empty">The scorer produced no signals.</div>';
    return;
  }
  ALL_LAYERS.forEach((layer) => {
    const rows = signals.filter((s) => s.layer === layer);
    if (!rows.length) { return; }
    const weight = rows.reduce((sum, s) => sum + s.weight, 0);
    const group = document.createElement("div");
    group.className = "group";
    const heading = document.createElement("h3");
    heading.textContent = `${layer} · ${weight > 0 ? "+" : ""}${weight.toFixed(1)}`;
    const list = document.createElement("ul");
    list.className = "sig";
    rows.sort((a, b) => b.weight - a.weight).forEach((s) => {
      const li = document.createElement("li");
      li.className = s.weight > 0 ? "bot" : "human";
      const code = document.createElement("code");
      code.textContent = `${s.id}  ${s.weight > 0 ? "+" : ""}${s.weight}`;
      const detail = document.createElement("span");
      detail.textContent = s.detail;
      li.append(code, detail);
      list.appendChild(li);
    });
    group.append(heading, list);
    host.appendChild(group);
  });
}

function drawDivergences(list) {
  const host = $("divergences");
  host.innerHTML = "";
  if (!list || !list.length) {
    host.innerHTML = '<div class="clean">Both worlds report the same values. ' +
      'This probe found no patch applied through the control channel.</div>';
    return;
  }
  list.forEach((d) => {
    const box = document.createElement("div");
    box.className = "divergence";
    const field = document.createElement("div");
    field.className = "f";
    field.textContent = d.field;
    const main = document.createElement("div");
    main.className = "d";
    main.textContent = `page sees: ${d.main}`;
    const isolated = document.createElement("div");
    isolated.className = "d";
    isolated.textContent = `browser reports: ${d.isolated}`;
    box.append(field, main, isolated);
    host.appendChild(box);
  });
}

function drawWorlds(main, isolated) {
  const body = $("worlds").querySelector("tbody");
  body.innerHTML = "";
  if (!main && !isolated) {
    body.appendChild(row(["No world snapshot arrived.", "", ""]));
    return;
  }
  const fields = new Set([
    ...Object.keys(main || {}), ...Object.keys(isolated || {})
  ]);
  [...fields].sort().forEach((field) => {
    const a = (main || {})[field];
    const b = (isolated || {})[field];
    if (a && typeof a === "object" && !Array.isArray(a)) { return; }
    const left = Array.isArray(a) ? a.join(", ") : text(a);
    const right = b === undefined ? "not read" : (Array.isArray(b) ? b.join(", ") : text(b));
    const differs = b !== undefined && String(a) !== String(b);
    body.appendChild(row([field, left, right], differs ? "differs" : ""));
  });
}

function drawHeaders(request) {
  const body = $("headers").querySelector("tbody");
  body.innerHTML = "";
  if (!request || !request.order || !request.order.length) {
    body.appendChild(row([
      "No header capture", "The worker saw no top-level request for this tab.", ""
    ]));
    return;
  }
  request.order.forEach((name, index) => {
    body.appendChild(row([String(index + 1), name, text(request.headers[name])]));
  });
}

function drawHarness(delivery) {
  const host = $("harness");
  host.innerHTML = "";
  if (!delivery || !delivery.sent) {
    const note = document.createElement("div");
    note.className = "clean";
    note.textContent = (delivery && delivery.reason) ||
      "This report never reached the harness, so the TLS and network layers are unmeasured.";
    host.appendChild(note);
    return;
  }
  const server = delivery.serverResult || {};
  const tls = server.tls || {};
  const table = document.createElement("table");
  const body = document.createElement("tbody");
  [
    ["harness score", `${text(server.score)}  (${text(server.verdict)})`],
    ["first catching layer", text(server.first_catching_layer)],
    ["strongest layer", text(server.strongest_layer)],
    ["total weight", text(server.total_weight)],
    ["session id", text(server.session_id)],
    ["source address", text(server.ip)],
    ["http layer scored", text(server.header_source)],
    ["ja4", text(tls.ja4)],
    ["ja4_r", text(tls.ja4_r)],
    ["ja3", text(tls.ja3)],
    ["alpn", (tls.alpn || []).join(", ") || "—"],
    ["grease", tls.grease === undefined ? "—" : String(tls.grease)]
  ].forEach((pair) => body.appendChild(row(pair)));
  table.appendChild(body);
  host.appendChild(table);
}

function summarise(result, record) {
  const caught = result.first_catching_layer;
  if (!caught) {
    return "No layer flagged this client. Every signal was neutral or counted in its favour.";
  }
  const ids = (result.layers[caught] || {}).ids || [];
  const harness = record.delivery && record.delivery.sent
    ? ` The harness scored the same report ${record.delivery.serverScore} with the TLS and network layers added.`
    : " The TLS and network layers were not measured, so a real stack could have caught this client earlier.";
  return `The ${caught} layer flagged this client first, on ${ids.join(", ")}.${harness}`;
}

function download(name, body, type) {
  const url = URL.createObjectURL(new Blob([body], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

function csvRow(record) {
  const r = record.result;
  const server = (record.delivery && record.delivery.serverResult) || {};
  const tls = server.tls || {};
  const columns = {
    time: record.time,
    label: record.label,
    url: record.url,
    score: r.score,
    verdict: r.verdict,
    first_catching_layer: r.first_catching_layer,
    strongest_layer: r.strongest_layer,
    total_weight: r.total_weight,
    harness_score: server.score === undefined ? "" : server.score,
    ja4: tls.ja4 || "",
    ja3: tls.ja3 || "",
    user_agent: (record.report.main_world || {}).user_agent || "",
    detection_ids: ALL_LAYERS.flatMap((n) => ((r.layers[n] || server.layers?.[n] || {}).ids) || []).join(" "),
    divergences: (record.divergences || []).map((d) => d.field).join(" ")
  };
  ALL_LAYERS.forEach((name) => {
    const entry = r.layers[name] || (server.layers || {})[name];
    columns["w_" + name] = entry ? entry.weight : "";
  });
  const names = Object.keys(columns);
  const escape = (v) => `"${String(v === undefined ? "" : v).replace(/"/g, '""')}"`;
  return `${names.join(",")}\n${names.map((n) => escape(columns[n])).join(",")}\n`;
}

let current = null;

function render(record) {
  if (!record) {
    $("summary").textContent =
      "No report is stored for this tab. Reload the page under test, then reopen this report.";
    return;
  }
  current = record;
  const r = record.result;
  const server = (record.delivery && record.delivery.serverResult) || {};

  $("m-url").textContent = text(record.url);
  $("m-time").textContent = text((record.time || "").replace("T", " ").replace(/\..*$/, ""));
  $("m-label").textContent = text(record.label);
  $("m-reason").textContent = text(record.report.reason);

  $("score").textContent = r.score;
  $("score").style.color = colorFor(r.score);
  $("verdict").textContent = r.verdict;
  $("needle").style.left = `${((r.score - 1) / 98) * 100}%`;
  $("summary").textContent = summarise(r, record);

  drawLadder(r.layers || {}, server.layers || {});
  drawDivergences(record.divergences);
  drawSignals(server.signals && server.signals.length ? server.signals : r.signals);
  drawWorlds(record.report.main_world, record.report.isolated_world);
  drawHeaders(record.request);
  drawHarness(record.delivery);

  fillTable("runtime", flatten(record.report.runtime),
    "The runtime probe returned nothing for this page.");
  fillTable("environment", flatten(record.report.environment),
    "The environment probe returned nothing for this page.");
}

function load() {
  const wanted = new URLSearchParams(location.search).get("tab");
  const tabId = wanted === null ? undefined : Number(wanted);
  chrome.runtime.sendMessage({ type: "botlab-get-result", tabId }, (record) => {
    void chrome.runtime.lastError;
    render(record);
  });
}

$("export-json").addEventListener("click", () => {
  if (!current) { return; }
  download(`botlab-${current.label || "report"}.json`,
    JSON.stringify(current, null, 2), "application/json");
});

$("export-csv").addEventListener("click", () => {
  if (!current) { return; }
  download(`botlab-${current.label || "report"}.csv`, csvRow(current), "text/csv");
});

$("print").addEventListener("click", () => window.print());
$("refresh").addEventListener("click", load);

load();
