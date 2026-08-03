# botlab probe — the extension

The probe measures the browser that runs it. Load it in a normal Chrome. Load
it in an automated Chrome. Compare the two reports.

The extension detects automation. It does not evade detection. It observes
request headers. It never changes a request.

## Why an extension finds what a web page cannot

A content script runs in an **isolated world**. The page runs in the **main
world**. Both worlds share the same DOM. They do not share the same JavaScript
globals.

A stealth tool patches the main world, because the website reads that world.
The patch arrives through the automation control channel, and the isolated
world never receives it. The extension therefore reads the true value while the
page reads the false one.

The probe reads eighteen properties in both worlds and reports every field that
differs. A single divergence is direct evidence of a patch. Only an extension
can measure it.

Measured example, with a real browser transport in both rows:

| Client | Page-only view | With the probe |
|---|---|---|
| Real Chrome | 97 (likely human) | 98 (likely human) |
| Patched stealth browser | 97 (likely human) | 1 (automated), caught by `worlds` |

The stealth browser hides from the page. It does not hide from the probe.

## Install

1. Open `chrome://extensions` in Chrome 111 or later.
2. Turn on **Developer mode**.
3. Press **Load unpacked**.
4. Choose this `extension` folder.
5. Open any page. Press the extension icon.

The badge on the icon shows the score for the active tab. Press **Open full
report** in the popup for the evidence behind it.

## Load the probe in an automated browser

This step turns the probe into a research instrument. The automation loads the
probe, and the probe reports what the automation did to the browser.

Playwright:
```
chromium.launchPersistentContext("/tmp/profile", {
  headless: false,
  args: [
    "--disable-extensions-except=/path/to/botlab/extension",
    "--load-extension=/path/to/botlab/extension"
  ]
})
```

Puppeteer:
```
puppeteer.launch({
  headless: false,
  args: [
    "--disable-extensions-except=/path/to/botlab/extension",
    "--load-extension=/path/to/botlab/extension"
  ]
})
```

Headless Chrome loads extensions from Chrome 112. Older headless modes do not.
Run the trial in headed mode if the version refuses the extension.

## The seven layers the extension measures

| Layer | Source |
|---|---|
| http | The real navigation header order, read with `chrome.webRequest` |
| browser | The main-world fingerprint: WebGL, canvas, fonts, plugins, window |
| worlds | The difference between the main world and the isolated world |
| runtime | How the engine behaves: CDP, descriptor placement, stack shape, frame clock |
| environment | What the machine has: media devices, voices, codecs, WebRTC, storage |
| behavior | Pointer path, key timing, wheel deltas, and the `isTrusted` flag |
| consistency | The User-Agent against every other claim |

The `behavior` layer holds one signal a page cannot trust. A content script
reads `isTrusted` before page code can replace the event object. An event with
`isTrusted` set to false came from a script, not from a hand.

### What runtime probes

- **`runtime.cdp_attached`** — a console call does not format its argument until
  something reads it. Nothing reads it in a plain browser. A CDP client
  serializes the error the moment it is logged, and that read fires a getter the
  probe planted on `stack`. An open DevTools window fires it too, so record
  whether one was open.
- **`runtime.webdriver_relocated`** — Chrome defines `webdriver` on
  `Navigator.prototype`. A stealth patch usually redefines it on the `navigator`
  instance, which leaves the property in the wrong place.
- **`runtime.prepare_stack_trace_set`** — Chrome leaves `Error.prepareStackTrace`
  undefined. A stealth plugin sets it to scrub its own frames out of traces.
- **`runtime.tostring_chain_patched`** — a patch that hides other patches must
  survive being asked about itself. Most forget.
- **`runtime.no_animation_frame`** — a window with no compositor never paints.
  The probe skips this when the tab was hidden, because a background tab looks
  the same.

### What environment probes

A stealth patch rewrites what the browser says. It does not install a sound
card, a camera, a voice pack, or a licensed codec.

- **`environment.no_proprietary_codecs`** — Chrome ships licensed H.264 and AAC.
  The plain Chromium build that Puppeteer and Playwright download does not.
- **`environment.no_media_devices`** — no camera and no microphone enumerated.
- **`environment.no_speech_voices`** — no system voice pack.
- **`environment.no_ice_candidates`** — WebRTC gathering finished with nothing,
  so the host has no reachable network interface.
- **`environment.no_pdf_viewer`**, **`environment.no_battery_api`** — present in
  desktop Chrome, absent in many automated builds.

Each of these also emits a negative signal when it passes, so a real browser
earns credit rather than merely avoiding a penalty.

## The full report

The popup gives the verdict. **Open full report** gives the evidence:

- every signal grouped by layer, with its detection ID and weight
- the world comparison, field by field
- the raw runtime and environment probe output
- the main-world snapshot against the isolated-world snapshot, with the
  differing rows marked
- the request headers in the order the browser sent them
- the harness block with JA4, JA4_r, JA3, ALPN and GREASE, when a harness
  scored the same report
- **Download JSON**, **Download CSV row**, and **Print**

The network and TLS rows of the ladder read *not measured* until a harness
scores the report.

## Connect the probe to the backend

The extension cannot read the TLS handshake, so it scores seven layers. With the
backend it is nine.

1. Start the backend.
   ```
   python3 server.py --host 127.0.0.1 --port 8443
   ```
2. Open the popup. Type `https://127.0.0.1:8443` in the harness field.
3. Type a run label, such as `chrome-141-stealth`.
4. Turn on **Send every report to the harness**.
5. Browse. Each report reaches the backend and joins the session table.

Trust the certificate first. Open `https://127.0.0.1:8443/dashboard` in the same
browser and accept the warning. The extension cannot accept it for you.

## Permissions and privacy

| Permission | Reason |
|---|---|
| `webRequest` | Read the header order of the top-level request |
| `storage` | Hold the harness URL, the run label, the history, the last report |
| `tabs` | Match a report to the tab that produced it, and open the report page |
| `<all_urls>` | Measure the browser on the page under test |

The probe sends nothing anywhere until you set a harness URL. The history stays
in local storage. Remove it by removing the extension.

## Limits

1. The extension reads no TLS handshake. A browser gives no API for it.
2. A page cannot install the probe. This is a laboratory instrument, not a
   production detector. Report it as such.
3. The world comparison finds a patch that the control channel applied. It does
   not find a patch built into a compiled browser. An anti-detect browser that
   changes the source patches both worlds at once. The `runtime` and
   `environment` layers exist to cover that case, because they read engine
   behaviour and machine capability rather than property values.

The third limit is a finding, not a weakness. State it in the writeup. It marks
the boundary between a scripted stealth plugin and a rebuilt browser, and it
explains why the second class costs so much more to produce.
