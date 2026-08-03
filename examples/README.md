# Example clients

Each script drives the task page at `/` end to end and prints the score the
harness returned. Start the harness first:

```
python3 server.py --host 127.0.0.1 --port 8443
```

| Script | Tool | What it does |
|---|---|---|
| `playwright_naive.py` | Playwright | `fill()` and `click()`, the calls a script reaches for first |
| `playwright_human.py` | Playwright | Types key by key, glides the pointer along a curved path, overshoots and corrects |
| `selenium_naive.py` | Selenium | `send_keys()` and `click()` |

```
python3 examples/playwright_naive.py --url https://127.0.0.1:8443
python3 examples/playwright_human.py --url https://127.0.0.1:8443 --seed 7
python3 examples/selenium_naive.py  --url https://127.0.0.1:8443
```

Every script prints a report URL. Open it to see the evidence behind the score.

## Measured runs

Playwright 1.56 driving Chrome for Testing 148, headless, against a local
harness. Your numbers will differ; record your own versions.

| Run | Score | Verdict | Caught first by |
|---|---|---|---|
| `playwright_naive` | 1 | automated | http |
| `playwright_human` | 18 | likely automated | http |

Both were caught at the http layer before any behaviour was read, because
headless Chrome names itself in the User-Agent. The interesting comparison is
the behaviour layer alone:

| Run | behaviour weight | What fired |
|---|---|---|
| `playwright_naive` | +7.6 | `sparse_pointer_sampling`, `pointer_teleport`, `input_without_keystroke` |
| `playwright_human` | +1.2 | `pointer_teleport`, `short_dwell`, against four credits |

The imitation works on almost everything. It fails on key hold time:
`keyboard.type` presses and releases a key in the same breath, so the mean
dwell was 3.3 ms where a finger holds for 60 to 150 ms. Staggering the gaps
*between* keys does not fix the duration of each press.

## Writing your own

The page exposes a small API:

```js
window.botlab.sessionId   // the run id, also the report URL
window.botlab.tasks()     // {typing, targets, drag, ready, submitted}
window.botlab.finish()    // returns a promise of the scored result
window.botlab.result      // the same result once it has arrived
```

Selectors are stable: `#field-name`, `#field-email`, `#target-1`, `#target-2`,
`#target-3`, `#slider`, `#submit-run`.

The page also sends itself once the required tasks are done and the page has
been quiet for 1.5 seconds, so a script that never calls `finish()` still
produces a report.

Pass `?label=` to name the run. Every report carries the label, and
`/export.csv` groups by it.

To assert in CI:

```python
result = page.evaluate("window.botlab.finish()")
assert result["score"] < 30, result["first_catching_layer"]
```

## Scope

These scripts run against a harness you control. They change the timing and
the path of a tool's own input against your own origin. Do not point them at a
third-party website.
