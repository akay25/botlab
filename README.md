# botlab — a bot detection instrument

botlab is a Chrome extension that measures the browser it runs in. Load it in a
normal Chrome and it reports a clean browser. Load it inside an automated Chrome
and it reports which layer identified the automation, with the evidence behind
the verdict.

botlab detects automation. It does not evade detection. The code contains no
evasion tool.

## Shape

The extension is the instrument. It scores seven layers from inside the browser
and flags the instance with a full report.

A small Python backend is optional. It exists for the two layers no browser API
can reach: the TLS handshake and the source address. It serves no test page.

```
   Chrome (real, headless, or patched)
   ├── main world  ─┐
   ├── isolated    ─┼─→ extension scores 7 layers ─→ badge, popup, full report
   └── webRequest  ─┘                   │
                                        └─ optional POST ─→ backend adds tls + network
```

## Run the extension alone

1. Open `chrome://extensions` in Chrome 111 or later.
2. Turn on **Developer mode**.
3. Press **Load unpacked** and choose the `extension` folder.
4. Open any page. The badge on the icon shows the score for that tab.
5. Press the icon, then **Open full report** for the evidence.

That is the whole instrument. Nothing is sent anywhere until you set a harness
URL yourself.

## Add the backend for the TLS and network layers

```
pip install cryptography
python3 server.py --host 127.0.0.1 --port 8443
```

Then in the extension popup, set the harness URL to `https://127.0.0.1:8443`,
type a run label, and turn on **Send every report to the harness**. Load
`https://127.0.0.1:8443/dashboard` once in the same browser and accept the
self-signed certificate, otherwise the extension cannot reach it.

The popup then shows two scores. The local score comes from seven layers. The
harness score adds the TLS layer and the network layer to the same report.

`--no-tls` serves plain HTTP for debugging. The TLS layer reports no data in
that mode.

## The nine layers

| Layer | Measured by | What it reads | Example signal |
|---|---|---|---|
| network | backend | The source address | Reputation of the address range |
| tls | backend | The raw ClientHello | The client sends no GREASE value |
| http | extension | The real navigation headers and their order | The header order does not match Chrome |
| browser | extension | The main-world fingerprint | The WebGL renderer is a software rasterizer |
| worlds | extension | The two JavaScript worlds | The page and the browser disagree on `navigator.webdriver` |
| runtime | extension | How the engine behaves | A CDP client is attached; `Error.prepareStackTrace` is set |
| environment | extension | What the machine actually has | No camera, no voices, no licensed H.264 |
| behavior | extension | Pointer path, key timing, `isTrusted` | The pointer path is a straight line |
| consistency | extension | Every claim against every other | The User-Agent and `navigator.platform` disagree |

The order is the order a production stack meets a client, so the first layer
with a positive signal is the layer that would have caught it. The report names
that layer.

The `worlds` layer is the one only an extension can measure, and it is usually
the strongest. The `runtime` and `environment` layers exist because `worlds`
has a blind spot: a browser patched at the source changes both worlds at once.
They read how the engine behaves and what hardware backs it, which a property
rewrite does not change.

## Why the extension forwards its own header capture

The extension reports to the backend over `fetch`. Those are background-request
headers, not navigation headers, so scoring them would fail the http checks for
reasons that say nothing about the client. The extension watches the real
top-level navigation with `chrome.webRequest` and sends what it saw. The
backend scores that and records the POST headers separately, because the
connection they arrived on is what carried the handshake. The `header_source`
column in the export says which request was scored.

## Score

The engine adds the weight of every signal and maps the total through a
logistic function to a score from 1 to 99. A low score means the client is
probably automated. This range copies the convention that commercial systems
use, so results map onto their published thresholds.

| Score | Verdict |
|---|---|
| 1 to 10 | automated |
| 11 to 30 | likely automated |
| 31 to 60 | unclear |
| 61 to 99 | likely human |

Each signal carries a detection ID such as `runtime.cdp_attached`. Report the
detection IDs, not only the score. The IDs name what the instrument measured;
a score is one number a reader cannot check.

## Calibrate before you report a result

The reference table starts almost empty. A JA4 hash changes with every browser
release, so a table copied from an article is not evidence.

1. Send a report from the client you want to record, with a run label.
2. File the fingerprint.
   ```
   python3 calibrate.py --class human --label "chrome-141-macos"
   python3 calibrate.py --class automation --label "playwright-chromium-1.49"
   ```
3. Print the table at any time with `--list`.

The structural rules work without calibration. GREASE, ALPN, header order, the
runtime probes, and the environment probes need no table.

## Compare against non-browser clients

The matrix sends a set of non-browser clients to the backend and prints the
result table.

```
python3 client_matrix.py --url https://127.0.0.1:8443 --csv results.csv
```

A client can copy the User-Agent of Chrome and every Chrome header in the
correct order. The TLS layer still identifies it, because the handshake
completes before the first header arrives. Add browser rows to the same table
by running the extension with a run label per client.

## Export

| Source | Holds |
|---|---|
| Report page, **Download JSON** | The whole record: both world snapshots, every probe, every signal |
| Report page, **Download CSV row** | One row in the same columns as the harness export |
| Popup, **Export history CSV** | One row per report in this browser |
| `https://host:port/export.csv` | Every session the backend logged, with the TLS columns |

Join the extension export and the harness export on the run label.

## Files

| File | Role |
|---|---|
| `extension/manifest.json` | MV3 manifest, two content scripts in two worlds |
| `extension/main-world.js` | The main-world snapshot and the runtime and environment probes |
| `extension/content.js` | The isolated-world snapshot, the world diff, the behaviour telemetry |
| `extension/scorer.js` | The seven in-browser layers and the score |
| `extension/background.js` | Header capture, scoring, badge, history, harness delivery |
| `extension/popup.html`, `popup.js` | The verdict and the settings |
| `extension/report.html`, `report.js` | The full report and the exports |
| `server.py` | The listener, the routes, the session store, the CSV export |
| `tlsfp.py` | The ClientHello parser and the JA3 and JA4 functions |
| `scoring.py` | The signal registry, the layer weights, and the score |
| `reference.py` | The header orders, the marker lists, the calibration file |
| `calibrate.py` | The tool that files a measured fingerprint |
| `client_matrix.py` | The comparison run across non-browser clients |
| `static/dashboard.html` | The session table the backend serves |

## Scope

Run botlab against your own test origin only. Do not point the backend or any
test client at a third-party website. The legal exposure in this field comes
from the defeat of an access control, not from the collection of public data.
A local origin removes that exposure.

## Limits

State these limits in any writeup. They set the boundary of the claim.

1. A page cannot install the probe. This is a laboratory instrument, not a
   production detector.
2. The `worlds` layer finds a patch applied through the automation control
   channel. It does not find a patch compiled into the browser. An anti-detect
   browser that changes the source patches both worlds at once. This is a
   finding, not a weakness: it marks the boundary between a scripted stealth
   plugin and a rebuilt browser, and it explains why the second class costs so
   much more to produce.
3. `runtime.cdp_attached` names a debugger, not an automation tool alone. An
   open DevTools window trips it the same way. Record whether one was open.
4. The backend speaks HTTP/1.1 and computes no HTTP/2 frame fingerprint.
5. The network layer has no address reputation feed. It records the address.
6. The weights are hand-set, not learned. Report them as a transparent
   baseline.
7. The behaviour layer reads one page view, not a profile across a session.

## Extend the instrument

Add a signal in one place. Write a function in `extension/scorer.js` that
returns signal objects, give each one a layer, a detection ID, a weight, and a
sentence that explains the evidence, then call it from `evaluateReport`. Mirror
it in `scoring.py` if the backend should score it too. Keep the detection IDs
and the weights identical across the two, because a run may be scored by either.
