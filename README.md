# botlab — a bot detection instrument

botlab identifies automated browsers and reports which layer identified them,
with the evidence behind the verdict.

botlab detects automation. It does not evade detection. The code contains no
evasion tool.

## Two ways in

**The task page.** Point Selenium, Playwright, or any other tool at
`https://127.0.0.1:8443/`. It performs three tasks — type into two fields,
click three targets, drag a slider — and the harness reports whether a hand or
a script did them. This is the path to use when the thing under test is an
automation tool.

**The extension.** Load `extension/` into a browser and it measures that
browser from the inside, on any page. This is the path to use when the thing
under test is a browser build: a stealth-patched Chrome, an anti-detect
product, a headless variant.

Both post to the same Python backend, which adds the two layers no browser API
can reach — the TLS handshake and the source address — and scores everything
against one signal registry.

```
  automation tool ──→ task page ──┐
                                  ├──→ backend: 9 layers ──→ report, dashboard, CSV
  browser under test ─→ extension ┘
```

## Install

```
pipenv install --dev && pipenv shell
cp example.env .env
```

Or without pipenv:

```
python3 -m venv .venv && source .venv/bin/activate
pip install fastapi uvicorn pydantic-settings python-json-logger cryptography
cp example.env .env
```

## Run an automation tool against the task page

```
python -m src
```

Then point a tool at it. Ready-to-run examples live in `examples/`:

```
python examples/playwright_naive.py --url https://127.0.0.1:8443
python examples/playwright_human.py --url https://127.0.0.1:8443 --seed 7
python examples/selenium_naive.py  --url https://127.0.0.1:8443
```

Each prints the score and a report URL. Open the URL for the evidence, or open
`/dashboard` to compare runs.

The page uses stable selectors — `#field-name`, `#field-email`, `#target-1`
through `#target-3`, `#slider` — so every tool performs the identical task and
the reports compare like for like. Pass `?label=` to name a run.

A script can read its own verdict:

```python
result = page.evaluate("window.botlab.finish()")
assert result["score"] < 30
```

If a script never calls `finish()`, the page sends itself once the required
tasks are done and it has been quiet for 1.5 seconds. See `examples/README.md`.

### What the behaviour layer reads

The page keeps raw events and computes nothing. The server derives every
metric, so a stored run can be re-scored when the rules change and a reader can
recompute any number in a report.

**Pointer.** Sampling density per 100 px travelled, path straightness measured
per movement rather than across the session, step-length variation, speed,
acceleration and jerk, corrective sub-movements, pauses, direction changes,
jumps with no event between, whether coordinates are whole pixels, and whether
`movementX` agrees with the change in position.

**Keys.** Dwell — how long each key was held — and flight, the gap between
presses, each with mean and spread; whether any key was held for zero time;
typing speed; whether `keypress` fired at all; and whether text arrived with no
key event, which is what `fill()` and `Input.insertText` produce.

Movements are judged one at a time. A path that visits three targets in three
corners is bent by the task, not by a hand, so a whole-session straightness
ratio says nothing.

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
python -m src
```

Then in the extension popup, set the harness URL to `https://127.0.0.1:8443`,
type a run label, and turn on **Send every report to the harness**. Load
`https://127.0.0.1:8443/dashboard` once in the same browser and accept the
self-signed certificate, otherwise the extension cannot reach it.

The popup then shows two scores. The local score comes from seven layers. The
harness score adds the TLS layer and the network layer to the same report.

Set `TLS_ENABLED=false` in `.env` to serve plain HTTP while debugging the page.
The TLS layer reports no data in that mode.

## How the TLS layer survives uvicorn

uvicorn hands an accepted socket straight to asyncio's SSL layer, which never
exposes the raw handshake, so a fingerprint cannot be taken from inside the
application. `src/loaders/tls_proxy.py` puts a plain TCP listener in front.

For each connection it reads the first TLS record, computes JA3 and JA4 from
it, then opens a connection to uvicorn, replays the bytes it consumed, and
pipes the two sockets together. The stream stays encrypted the whole way: the
front end never holds the key and never decrypts anything, and uvicorn
completes the handshake exactly as it would have.

A request finds its own handshake again by the source port of the upstream
connection, which is unique per client connection and stable across keep-alive
requests on it. The real client address travels the same way, because uvicorn
sees only the front end.

This is why two ports are involved. Clients talk to `APP_PORT`; uvicorn
listens on `APP_PORT + 1`, or on `TLS_UPSTREAM_PORT` if you set one.

## The nine layers

| Layer | Measured by | What it reads | Example signal |
|---|---|---|---|
| network | backend | The source address | Reputation of the address range |
| tls | backend | The raw ClientHello | The client sends no GREASE value |
| http | page, extension | The real navigation headers and their order | The header order does not match Chrome |
| browser | page, extension | The page-visible fingerprint | The WebGL renderer is a software rasterizer |
| worlds | extension only | The two JavaScript worlds | The page and the browser disagree on `navigator.webdriver` |
| runtime | page, extension | How the engine behaves | A CDP client is attached; `Error.prepareStackTrace` is set |
| environment | page, extension | What the machine actually has | No camera, no voices, no licensed H.264 |
| behavior | page, extension | Pointer kinematics, keystroke dynamics, `isTrusted` | Keys were held for 3 ms; the pointer was placed, not moved |
| consistency | page, extension | Every claim against every other | The User-Agent and `navigator.platform` disagree |

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
   python tools/calibrate.py --class human --label "chrome-141-macos"
   python tools/calibrate.py --class automation --label "playwright-chromium-1.49"
   ```
3. Print the table at any time with `--list`.

The structural rules work without calibration. GREASE, ALPN, header order, the
runtime probes, and the environment probes need no table.

## Compare against non-browser clients

The matrix sends a set of non-browser clients to the backend and prints the
result table.

```
python tools/client_matrix.py --url https://127.0.0.1:8443 --csv results.csv
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
| `https://host:port/api/export.csv` | Every session the backend logged, with the TLS columns |

Join the extension export and the harness export on the run label.

## Layout

```
src/
├── main.py                FastAPI app: CORS, exception handlers, routers
├── __main__.py            entry point; starts uvicorn and the TLS front end
├── constants.py           layer order, score bands, CSV columns
├── loaders/
│   ├── config.py          pydantic-settings, reads .env
│   ├── logging.py         JSON logger
│   ├── certificates.py    the self-signed certificate for the test origin
│   ├── storage.py         session cache and the append-only run log
│   ├── tls_proxy.py       reads the ClientHello before uvicorn sees it
│   └── app_lifespan.py    starts and stops the front end
├── detection/
│   ├── scoring.py         the signal registry and the score
│   ├── behavior.py        pointer and keystroke analysis
│   ├── tlsfp.py           ClientHello parser, JA3 and JA4
│   ├── reference.py       header orders, marker lists, calibration table
│   └── session.py         assembles the record that gets scored
├── routes/
│   ├── pages.py           /, /dashboard, /report/{id}, /collector.js
│   ├── collect.py         POST /api/collect
│   ├── sessions.py        /api/sessions, /api/sessions/{id}, /api/probe
│   └── exports.py         /api/export.csv
├── types/
│   ├── input/collect.py   the report payload
│   └── response/detection.py  score, layers, signals, session summary
├── utils/__init__.py      make_response, run tokens, verdict bands
└── static/                task page, collector, report viewer, dashboard

extension/                 the MV3 probe, its own scorer and report page
examples/                  runnable Playwright and Selenium clients
tools/                     calibrate.py, client_matrix.py
data/                      run log, certificate, calibration table
```

`detection/` holds what `models/` holds in a database-backed service: the
domain. The harness stores runs in a JSONL log rather than a database, so
`loaders/storage.py` is the whole persistence layer.

## API

Interactive docs at `/docs`. Every reply is wrapped as
`{success, message, data}`.

| Method | Path | Role |
|---|---|---|
| `GET` | `/` | The task page, with a fresh run token |
| `GET` | `/dashboard` | Every scored session in one table |
| `GET` | `/report/{id}` | The report viewer for one run |
| `POST` | `/api/collect` | Score a report from the page or the extension |
| `GET` | `/api/sessions` | The most recent scored sessions |
| `GET` | `/api/sessions/{id}` | One run, with raw telemetry and probe output |
| `GET` | `/api/probe` | Score the caller itself, for non-browser clients |
| `GET` | `/api/export.csv` | Every logged session as CSV |
| `GET` | `/api/health` | Liveness |

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
8. **The behavioural thresholds have no human control group behind them.** The
   key-dwell range in `src/detection/behavior.py` comes from published keystroke-dynamics
   work, not from runs against this harness, and the pointer thresholds are
   reasoned rather than measured. Before reporting a false-positive rate, run
   the task page yourself thirty times by hand, look at the distributions in
   the reports, and set the constants at the top of `src/detection/behavior.py` from your own
   data. Every threshold is a named constant for exactly this reason.

## Extend the instrument

Add a signal in one place. Write a function in `extension/scorer.js` that
returns signal objects, give each one a layer, a detection ID, a weight, and a
sentence that explains the evidence, then call it from `evaluateReport`. Mirror
it in `src/detection/scoring.py` if the backend should score it too. Keep the detection IDs
and the weights identical across the two, because a run may be scored by either.
