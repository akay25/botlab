# botlab — a bot detection instrument

botlab is a test origin that automation tools visit. It gives each visitor
three tasks to perform, watches how they were performed, and reports which
detection layer identified the visitor first, with the evidence behind the
verdict.

botlab detects automation. It does not evade detection. The code contains no
evasion tool.

## How it works

Point Selenium, Playwright, or any other tool at `https://127.0.0.1:8443/`.
The page asks it to type into two fields, click three targets, and drag a
slider. Every pointer and key event is recorded raw and posted back. The
harness scores eight layers and returns a verdict the script can read.

```
  automation tool ──→ task page ──→ eight layers ──→ report, dashboard, CSV
```

## Install

Python 3.14, per the `Pipfile`. `Pipfile.lock` is committed, so an install
resolves to the versions the measurements below were taken with.

```
cp example.env .env
pipenv install --dev
```

Or without pipenv:

```
python3 -m venv .venv && source .venv/bin/activate
pip install fastapi uvicorn pydantic-settings python-json-logger cryptography
cp example.env .env
```

The `--dev` group holds Playwright and Selenium, which only the scripts in
`examples/` need. Leave it out to run the harness alone.

Every `pipenv run <name>` below is a shortcut defined in the `Pipfile`. Without
pipenv, run the underlying command instead: `pipenv run start` is
`python -m src`, `pipenv run naive` is `python examples/playwright_naive.py`,
and so on.

## Run

```
pipenv run start
```

Then point a tool at it. Ready-to-run examples live in `examples/`:

```
pipenv run naive  --url https://127.0.0.1:8443
pipenv run human  --url https://127.0.0.1:8443 --seed 7
python examples/selenium_naive.py --url https://127.0.0.1:8443
```

Each prints the score and a report URL. Open the URL for the evidence, or open
`/dashboard` to compare runs.

| Command | Runs |
|---|---|
| `pipenv run start` | The harness |
| `pipenv run naive` | `examples/playwright_naive.py` |
| `pipenv run human` | `examples/playwright_human.py` |
| `pipenv run matrix` | `tools/client_matrix.py` |
| `pipenv run calibrate` | `tools/calibrate.py` |

## Driving the page

Selectors are stable, so every tool performs the identical task and the reports
compare like for like: `#field-name`, `#field-email`, `#target-1` through
`#target-3`, `#slider`, `#submit-run`.

```js
window.botlab.sessionId   // the run id, also the report URL
window.botlab.tasks()     // {typing, targets, drag, ready, submitted}
window.botlab.finish()    // returns a promise of the scored result
window.botlab.result      // the same result once it has arrived
```

A script can read its own verdict and fail a build on it:

```python
result = page.evaluate("window.botlab.finish()")
assert result["score"] < 30, result["first_catching_layer"]
```

If a script never calls `finish()`, the page sends itself once the required
tasks are done and it has been quiet for 1.5 seconds, so a tool that knows
nothing about the API still produces a report. Pass `?label=` to name a run;
`/api/export.csv` groups by it.

## The eight layers

| Layer | What it reads | Example signal |
|---|---|---|
| network | The source address | Reputation of the address range |
| tls | The raw ClientHello | The client sends no GREASE value |
| http | The navigation headers and their order | The header order does not match Chrome |
| browser | The page-visible fingerprint | The WebGL renderer is a software rasterizer |
| runtime | How the engine behaves | A CDP client is attached; `Error.prepareStackTrace` is set |
| environment | What the machine actually has | No camera, no voices, no licensed H.264 |
| behavior | Pointer kinematics and keystroke dynamics | Keys were held for 3 ms; the pointer was placed, not moved |
| consistency | Every claim against every other | The User-Agent and `navigator.platform` disagree |

The order is the order a production stack meets a client, so the first layer
with a positive signal is the layer that would have caught it. The report names
that layer.

`runtime` and `environment` matter most against a tool that has been taught to
lie. A stealth patch rewrites what the browser says about itself, but it does
not change how the engine behaves under a debugger, and it does not install a
camera, a voice pack, or a licensed H.264 decoder.

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

Both are also kept as a per-keystroke series, one entry per press in the order
it was typed, so the report can draw the timing of every key and a reader can
recompute any point of it. The report's **How the keyboard was typed on** chart
draws that series as two lines. A hand makes both ragged: hold times differ by
finger and by key, and the gaps stretch at word boundaries and after punctuation
then close up inside a familiar word. A driver that sleeps a fixed interval
between keys draws two almost flat lines.

The judgement uses spread divided by the mean rather than raw milliseconds,
because a fixed threshold misreads fast and slow typists in opposite directions:
8 ms of variation is nothing around a 200 ms mean and a great deal around a
20 ms one. Below `MIN_HUMAN_FLIGHT_CV` the run carries
`behavior.metronomic_typing_rhythm`, and below `MIN_HUMAN_DWELL_CV`,
`behavior.metronomic_dwell`. These catch the driver that jitters its delay by a
few milliseconds around a fixed value — not identical, so the older
`constant_typing_rhythm` and `uniform_keystrokes` rules both miss it, but far
too even for a hand.

Movements are judged one at a time. A path that visits three targets in three
corners is bent by the task, not by a hand, so a whole-session straightness
ratio says nothing.

### What the hardware checks read

Three of these read the machine rather than what the browser says about it.
A stealth patch rewrites a property; it does not fit a graphics card, install
a font, or wire up a microphone.

**GPU or CPU.** `reference.gpu_class` reads the WebGL vendor and renderer
together, because Chrome reports the adapter through ANGLE: the vendor carries
`Google Inc. (NVIDIA)` and the renderer carries the board name. A machine
drawing on a card scores `browser.hardware_renderer` at −0.9. A machine drawing
on the CPU — SwiftShader, llvmpipe, lavapipe, WARP — scores
`browser.software_renderer` at +1.9, and a client that also claims a desktop
platform adds `consistency.desktop_without_gpu`. Software is tested before
hardware: a rasterizer never names a real card, but the box it runs on might,
and testing the other way round would read a CPU renderer as a GPU. When
`WEBGL_debug_renderer_info` is unavailable the renderer name is generic, so the
run carries `browser.renderer_masked` at weight 0 rather than a guess — the
same distinction `tls.not_measured` draws.

**Fonts.** The page reports which fonts resolved, not how many, and the server
counts them. Under `FEW_FONTS` is `browser.few_fonts`; at or above `MANY_FONTS`
is `browser.rich_font_set`. Which ones resolved is the stronger signal:
`PLATFORM_FONTS` lists names that ship with one desktop platform only, so a
client claiming Windows while resolving Menlo and Optima and no Windows font at
all scores `consistency.font_platform_mismatch`. That fires only when the
claimed platform's fonts are all absent *and* another platform's are present, so
a machine that simply carries few fonts is not accused of lying.

**Media devices.** `enumerateDevices` reports the kind of every device before
permission is granted; only the labels stay blank. A microphone scores
`environment.microphone_present` at −0.8 and a camera
`environment.camera_present` at −0.5, because a container has no sound card to
enumerate one from. No devices at all remains `environment.no_media_devices`.

**DRM.** Widevine is a signed binary that ships with released browsers and with
the Chromium builds a distribution signs. The plain Chromium that Playwright and
Puppeteer download carries no CDM, and no patch installs one, which puts it in
the same class as the licensed codecs. Holding one scores
`environment.widevine_present` at −1.0, with a further −0.5 for
`environment.widevine_hardware_backed` when the CDM grants an `HW_` robustness
level, since that means the keys never leave a trusted execution environment.

Clear Key is the control, and it is what makes the absence readable. The EME
specification mandates Clear Key and it needs no licensed component, so a client
that grants Clear Key and refuses Widevine is an engine doing EME with nothing
behind it: `environment.no_widevine` at +2.0. Reading Widevine on its own could
not tell that apart from a browser with EME disabled. Granting no key system at
all, not even Clear Key, is `environment.no_key_systems` at +1.2.

Three cases are deliberately not charged. Safari uses FairPlay and Firefox
fetches its module on first use, so a missing Widevine outside Chrome is
`environment.no_widevine_expected` at weight 0. EME is gated on a secure
context, so with `TLS_ENABLED=false` the API is absent for a reason that has
nothing to do with the client, and a query that never answers is not a refusal —
both become `environment.drm_not_measured` at weight 0, on the same principle as
`tls.not_measured`.

Both new thresholds are named constants at the top of `src/detection/scoring.py`
and are reasoned rather than measured, so limit 7 below applies to them exactly
as it applies to the behavioural ones.

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

### Two sign conventions, and which one you are reading

The engine stores a weight where **positive counts against the client**:
`browser.software_renderer` is `+1.9`, `browser.hardware_renderer` is `-0.9`.
That is what `evaluate` sums, and it is what `/api/sessions` and the `w_` columns
of `export.csv` carry. Quote these numbers in a writeup.

The task page and the report viewer show that value **negated**, so that the
number, the bar direction and the colour all agree with the score rail above
them: to the right and blue is evidence of a person, to the left and red is
evidence of automation. A layer that reads `+2.7` on screen is `-2.7` in the
export. Only the two HTML files do this; nothing server-side is affected.

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
connection. That entry is dropped the moment the connection closes: while a
connection is open its port is exclusively its own, which makes the lookup
exact, but the operating system hands out ephemeral ports in sequence and
recycles them quickly, so an entry that outlived its connection would
eventually be found by an unrelated one and handed someone else's handshake.
The real client address travels the same way, because uvicorn sees only the
front end.

### Two ports, and only one of them is yours

Clients talk to `APP_PORT`, which is `8443` by default. uvicorn listens on
`APP_PORT + 1`, or on `TLS_UPSTREAM_PORT` if you set one.

**uvicorn logs the upstream port on startup. Ignore that line.** It reads like
an invitation, but a client that accepts it bypasses the front end, and the
request succeeds while quietly losing its TLS layer.

Anything arriving on the upstream port is redirected to the public port with a
307, which preserves the method and the body, so a report posted to the wrong
port still lands and still gets fingerprinted. A browser that loads the task
page from the wrong port is bounced before the page is served, so everything
it does afterwards is same-origin and correct. Nothing is lost either way.

If a request somehow reaches the app without passing the front end, the run
carries `tls.not_measured` at weight 0 rather than `tls.absent` at weight 1.
The difference matters: `tls.absent` is a claim about the client — it sent no
ClientHello. `tls.not_measured` is a fact about the harness — it was not in a
position to look. Charging a client for the second would quietly corrupt the
run. The same signal appears when `TLS_ENABLED=false`, for the same reason.

## Why the page reports through a run token

The page posts its report with `fetch`, whose headers belong to a background
request and describe nothing about the client. The navigation that served the
page is the request worth reading on the http layer.

So the harness hands each page a run token when it serves it, remembers the
navigation against that token, and takes both back when the report arrives.
The token also becomes the session id, which is why the page can link to its
own report before the report exists. The `header_source` column in the export
says which request was scored.

## Calibrate before you report a result

The reference table starts almost empty. A JA4 hash changes with every browser
release, so a table copied from an article is not evidence.

1. Send a report from the client you want to record, with a run label.
2. File the fingerprint.
   ```
   pipenv run calibrate --class human --label "chrome-141-macos"
   pipenv run calibrate --class automation --label "playwright-chromium-148"
   ```
3. Print the table at any time with `--list`.

Pass `--match-label` to pick a specific run. Without it the tool files the
newest session that carried a handshake, which may not be the one you meant.

The structural rules work without calibration. GREASE, ALPN, header order, the
runtime probes, and the environment probes need no table.

## Compare against non-browser clients

The matrix sends a set of non-browser clients to the harness and prints the
result table.

```
pipenv run matrix --url https://127.0.0.1:8443 --csv results.csv
```

A client can copy the User-Agent of Chrome and every Chrome header in the
correct order. The TLS layer still identifies it, because the handshake
completes before the first header arrives. These clients run no JavaScript, so
they are scored on the network, tls, http and consistency layers alone.

## Configuration

Settings come from `.env`, read by pydantic-settings in
`src/loaders/config.py`. Copy `example.env` to start.

| Variable | Default | Role |
|---|---|---|
| `APP_HOST` | `127.0.0.1` | The address to bind. Keep it local |
| `APP_PORT` | `8443` | The port clients talk to |
| `TLS_ENABLED` | `true` | Off serves plain HTTP and leaves the tls layer unmeasured |
| `TLS_UPSTREAM_PORT` | `0` | uvicorn's port; `0` means `APP_PORT + 1` |
| `LOG_LEVEL` | `INFO` | JSON logs on stdout |
| `ALLOWED_HOSTS` | `*` | CORS origins, comma separated |
| `SESSION_CACHE_SIZE` | `500` | Runs kept in memory for the dashboard |
| `DATA_DIR` | `./data` | Run log, certificate, calibration table |

`pipenv run` loads `.env` itself, and what it loads wins over what is already
in your shell. `APP_PORT=9000 pipenv run start` does **not** move the port —
edit `.env` instead. Without pipenv, the shell wins as usual.

## Layout

```
src/
├── main.py                FastAPI app: CORS, redirect, exception handlers
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
| `POST` | `/api/collect` | Score a report from the task page |
| `GET` | `/api/sessions` | The most recent scored sessions |
| `GET` | `/api/sessions/{id}` | One run, with raw telemetry and probe output |
| `GET` | `/api/probe` | Score the caller itself, for non-browser clients |
| `GET` | `/api/export.csv` | Every logged session as CSV |
| `GET` | `/api/health` | Liveness |

## Export

| Source | Holds |
|---|---|
| Report page, **Download JSON** | The whole record, including the raw event stream |
| `https://host:port/api/export.csv` | Every logged session, one row per run |

The CSV carries the per-layer weights and the detection IDs, not only the
score, because a score is one number a reader cannot check.

## Scope

Run botlab against your own test origin only. Do not point the harness or any
test client at a third-party website. The legal exposure in this field comes
from the defeat of an access control, not from the collection of public data.
A local origin removes that exposure.

## Limits

State these limits in any writeup. They set the boundary of the claim.

1. Everything the page measures, page script can see. A tool that patches the
   main world consistently defeats the `browser` and `consistency` layers.
   What survives is `runtime`, `environment`, `behavior` and `tls`, because
   those read engine behaviour, machine capability, human motor control and a
   handshake that happens before any script runs.
2. `runtime.cdp_attached` names a debugger, not an automation tool alone. An
   open DevTools window trips it the same way. Record whether one was open.
3. The harness speaks HTTP/1.1 and computes no HTTP/2 frame fingerprint.
4. The network layer has no address reputation feed. It records the address.
5. The weights are hand-set, not learned. Report them as a transparent
   baseline.
6. The behaviour layer reads one page view, not a profile across a session.
7. **The behavioural thresholds have no human control group behind them.** The
   key-dwell range in `src/detection/behavior.py` comes from published
   keystroke-dynamics work, not from runs against this harness, and the
   pointer thresholds are reasoned rather than measured. Before reporting a
   false-positive rate, run the task page yourself thirty times by hand, look
   at the distributions in the reports, and set the constants at the top of
   that file from your own data. Every threshold is a named constant for
   exactly this reason.
8. `examples/selenium_naive.py` has never been run. Playwright drives the
   verified path; the Selenium script is written against the documented API
   but was not executed, because chromedriver was not available here.

## Extend the instrument

Add a signal in one place. Write a function in `src/detection/scoring.py` that
returns `Signal` objects, give each one a layer, a detection ID, a weight, and
a sentence that explains the evidence, then call it from `evaluate`.

A new layer needs its name adding to `LAYERS` in `src/constants.py`, in the
position a production stack would meet it, and to the matching list in
`src/static/report.html` and `src/static/index.html`.

Behavioural thresholds belong at the top of `src/detection/behavior.py` as
named constants, never inline, so a reader can see what was assumed and change
it.

## The extension

An earlier version shipped a Chrome extension that measured a browser from the
inside and added a `worlds` layer, comparing the main and isolated JavaScript
worlds to catch stealth patches applied through the automation control channel.
It was removed to focus on the task page.

It is in the history, not gone. `git show fd3c523:extension/README.md` reads
its documentation, and `git checkout fd3c523 -- extension/` restores the whole
folder. The `worlds` layer and the payload plumbing that fed it were removed
from the harness in the same commit that deleted it, so bringing it back means
reverting that commit rather than only restoring the folder.
