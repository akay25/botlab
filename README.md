# botlab — a bot detection harness

botlab is a measurement instrument for research on anti-bot systems. It runs a
test origin that you control. The origin inspects each client at six layers and
reports which layer identified the client.

botlab detects automation. It does not evade detection. The code contains no
evasion tool.

## Scope

Run botlab against your own test origin only. Do not point the harness or any
test client at a third-party website. The legal exposure in this field comes
from the defeat of an access control, not from the collection of public data.
A local origin removes that exposure.

## Requirements

- Python 3.10 or later.
- The `cryptography` package. The server uses it to make a self-signed
  certificate.

```
pip install cryptography
```

## Start the harness

1. Start the server.
   ```
   python3 server.py --host 127.0.0.1 --port 8443
   ```
2. Open `https://127.0.0.1:8443/` in the client you want to measure.
3. Accept the self-signed certificate warning.
4. Move the pointer across the interaction area. Click it. Type a few keys.
5. Read the score, the layer ladder, and the signal list.

Open `https://127.0.0.1:8443/dashboard` to see every session in one table.
Open `https://127.0.0.1:8443/export.csv` to download the data for analysis.

Add `--no-tls` to serve plain HTTP. In this mode the TLS layer reports no data.
Use this mode only to debug the page.

## Run the client matrix

The matrix sends a set of non-browser clients to the harness. It then prints the
result table.

```
python3 client_matrix.py --url https://127.0.0.1:8443 --csv results.csv
```

The table shows the central result. A client can copy the User-Agent of Chrome
and copy every Chrome header in the correct order. The TLS layer still
identifies it, because the handshake completes before the first header arrives.

Add a real browser and a stealth browser to the same table by hand. Load the
test page in each one. Type a run label in the label field. Press "Send a new
report".

## Calibrate before you report a result

The reference table starts almost empty. A JA4 hash changes with every browser
release, so a table copied from an article is not evidence.

1. Load the test page in the client you want to record.
2. Record the fingerprint with the correct class and label.
   ```
   python3 calibrate.py --class human --label "chrome-141-macos"
   python3 calibrate.py --class automation --label "playwright-chromium-1.49"
   ```
3. Print the table at any time.
   ```
   python3 calibrate.py --list --class human --label x
   ```

The structural rules work without calibration. GREASE, ALPN, header order, and
the browser checks need no table.

## The Chrome extension

The `extension/` folder holds a Manifest V3 probe. Load it in Chrome, or load it
inside an automated Chrome, and it reports what the automation changed.

The probe compares the main world with the isolated world. A stealth patch
reaches the main world only, so any field that differs proves a patch. See
`extension/README.md`.

## The seven layers

| Layer | What it reads | Example signal |
|---|---|---|
| network | The source address | Reputation of the address range |
| tls | The raw ClientHello | The client sends no GREASE value |
| http | The headers and their order | The header order does not match Chrome |
| browser | The report from the page | The WebGL renderer is a software rasterizer |
| worlds | The two JavaScript worlds | The page and the browser disagree on `navigator.webdriver` |
| behavior | The pointer and key timing | The pointer path is a straight line |
| consistency | Every layer together | The User-Agent and navigator.platform disagree |

The consistency layer carries the heaviest weights. A stealth client can pass
one layer. It fails when two layers tell different stories about one machine.
This result is the main argument that the harness supports.

## How the TLS fingerprint works

The server does not use a normal HTTPS listener. It accepts the raw socket
first. It then reads the ClientHello bytes with a peek operation, which leaves
the bytes in the buffer. The TLS library reads the same bytes afterward and the
handshake completes as usual.

`tlsfp.py` parses the record and computes three values.

- **JA3** is the older MD5 hash of the version, ciphers, extensions, curves, and
  point formats.
- **JA4** is the current format. It resists extension permutation and adds the
  ALPN value and the signature algorithms.
- **JA4_r** keeps the readable field list. Cite this value in a paper, because a
  reader can check it.

## Score

The engine adds the weight of every signal. It maps the total through a logistic
function to a score from 1 to 99. A low score means the client is probably
automated. This range copies the convention that commercial systems use, so your
results map onto their published thresholds.

| Score | Verdict |
|---|---|
| 1 to 10 | automated |
| 11 to 30 | likely automated |
| 31 to 60 | unclear |
| 61 to 99 | likely human |

Each signal carries a detection ID such as `tls.no_grease`. Report the detection
IDs, not only the score. The IDs show a reader what the harness measured.

## Files

| File | Role |
|---|---|
| `server.py` | The listener, the routes, the session store, and the CSV export |
| `tlsfp.py` | The ClientHello parser and the JA3 and JA4 functions |
| `scoring.py` | The signal registry, the layer weights, and the score |
| `reference.py` | The header orders, the marker lists, and the calibration file |
| `calibrate.py` | The tool that files a measured fingerprint |
| `client_matrix.py` | The comparison run across several clients |
| `static/collector.js` | The page script that reports the fingerprint and telemetry |
| `static/index.html` | The test page and the layer ladder |
| `static/dashboard.html` | The session table |
| `extension/` | The Chrome probe and its own scorer |

## Limits

State these limits in the thesis. They set the boundary of the claim.

1. The server speaks HTTP/1.1. It does not compute an HTTP/2 frame
   fingerprint. Add an HTTP/2 layer if the thesis needs one.
2. The network layer has no address reputation feed. A production system buys
   one. The harness records the address only.
3. The weights are hand-set, not learned. A production system trains a model on
   a large traffic sample. Report the weights as a transparent baseline.
4. The behavior layer reads one page view. A production system builds a profile
   across a session and across days.

## Extend the harness

Add a signal in one place. Write a function in `scoring.py` that returns a list
of `Signal` objects. Give each signal a layer, a detection ID, a weight, and a
sentence that explains the evidence. Then call the function from `evaluate`.
