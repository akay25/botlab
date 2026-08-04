# tests

Two clients that complete every task on the page, so a run produces all four
measurements rather than only the ones a script happened to reach.

```
pipenv run pw-tasks                        # playwright, naive
pipenv run pw-tasks  --mode human --seed 7 # playwright, imitating a hand
pipenv run se-tasks                        # selenium, naive
pipenv run se-tasks  --mode human --seed 7 # selenium, imitating a hand
```

Without pipenv, run `python3 tests/playwright_tasks.py` and
`python3 tests/selenium_tasks.py` directly. Start the harness first.

Each script exits non-zero if it tripped a honeypot or left a required task
undone. Both of those say the script is wrong, not the harness.

## The four rows

| | typing | pointer path | task 4 |
|---|---|---|---|
| `playwright --mode naive` | `fill()`, no key events at all | `click()`, no path | straight to the centre |
| `playwright --mode human` | key by key, varying delay | curved, overshoot, correct | same approach, per target |
| `selenium --mode naive` | `send_keys`, real key events | `click()`, no path | straight to the centre |
| `selenium --mode human` | key by key, varying delay | curved, issued as offsets | same approach, per target |

The Playwright and Selenium naive rows are not the same experiment. `fill()`
sets a value through the debugger and produces no key events, so it earns
`behavior.input_without_keystroke`. `send_keys` goes through the WebDriver key
protocol and produces real ones, so it is judged on their timing instead. That
difference is the point of running both.

## What to watch in task 4

Fitts's law says acquisition time grows with `log₂(2D/W)`. The `human` mode
scales its movement with **distance**, because that is what interpolating a
path does — but it never pays for the **width** of the target. Whether that is
enough to earn `behavior.fitts_obeys`, or whether the run still flattens into
`behavior.fitts_no_scaling`, is the measurement. Read `slope`, `r²` and
`throughput` in the printed output, and the scatter in the report.

If you want a further rung on the evasion ladder in `PROTOCOL.md`, the next one
is a timing model that scales with difficulty rather than with distance. That is
deliberately not implemented here: the value of this harness is the measurement,
not the defeat.

## Honeypots

Three controls on the page are invisible, carry `tabindex="-1"` and are hidden
from assistive technology: `#fitts-decoy`, `#hp-email` and `#hp-submit`. Both
scripts avoid them by selecting `#fitts-target` by id rather than
`.fitts-target` by class, since one element of that class is the decoy. A script
that collects task 4's targets by class will click four of them and score
`behavior.honeypot_click` at +3.2.

## Status

**Neither script has been executed.** They are written against the documented
API and statically reviewed — every selector resolves against `index.html`,
neither acts on a honeypot or selects task 4 by class, the acquisition loops are
bounded, and the target box is re-read on each pass — but a static review cannot
tell you that Selenium's `move_by_offset` rounding, or Playwright's
`bounding_box()` on a target that has just moved, behave the way the code
assumes. Run each one once by hand before you trust a row of results from it.

The first run is also where the harness itself gets checked: if a script reports
`honeypots touched: 0` and all four tasks done, both sides agree.
