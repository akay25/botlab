# Experimental protocol

This document describes how to turn the harness into a result that a committee
accepts. Follow the order. Each step depends on the step before it.

## 1. Set the research question

Write one question that the harness can answer with a number. A weak question
asks whether a stealth browser works. A strong question asks which layer
identifies a stealth browser first, and how much the evasion costs.

Three questions that the harness answers well:

1. Which detection layer identifies each client class first?
2. How does the score move as a client adds one evasion technique at a time?
3. Which cross-layer inconsistency survives the most evasion effort?

## 2. Define the client classes

Test one client per class. Record the exact version of each one. A JA4 hash is
worthless without a version number.

| Class | Example |
|---|---|
| Plain HTTP client | Python urllib, curl |
| Spoofed HTTP client | curl with the full Chrome header set |
| Headless browser | Chromium in headless mode |
| Patched headless browser | Playwright with a stealth plugin |
| Anti-detect browser | A commercial anti-detect product |
| Real browser, real user | A person at a keyboard |

The last row is the control. Without it you cannot report a false-positive rate.

The browser classes drive the task page. The first two classes run no
JavaScript, so they reach the harness through `tools/client_matrix.py` instead
and are scored on the network, TLS, HTTP and consistency layers alone. Keep
them in the table anyway: they set the floor a spoofed client cannot get under.

## 3. Run the trials

1. Start the backend on a machine you control.
2. Clear `data/sessions.jsonl` before the first trial.
3. Calibrate the real browser and the automation clients.
4. Run each client class thirty times against the task page. Use one run label
   per class, passed as `?label=`.
5. For the control class, perform the tasks by hand. Record whether a DevTools
   window was open: it trips `runtime.cdp_attached` the same way an automation
   driver does.
6. Export the data with `/api/export.csv` and group by the run label.

Thirty runs per class gives enough spread to report a mean and a standard
deviation. Fewer runs give a number that a reviewer can question.

## 4. Report these tables

**Table A — detection by layer.** One row per client class. One column per each
of the nine layers. Each cell holds the share of runs that the layer flagged.
The `w_` columns of the export give the per-layer weights directly. This table
shows where each class fails.

**Table B — score distribution.** One row per client class. Report the mean
score, the standard deviation, and the range. Report the control row first.

**Table C — the evasion ladder.** Start with a plain client. Add one technique
per row. Report the score after each addition. This table shows the cost curve
of evasion.

**Table D — false positives.** Report how often the harness scored a real
browser below the automated threshold. A detector with no false-positive number
is not a result.

## 5. Report the detection IDs

Report the detection IDs, not only the scores. A score is one number, and a
reader cannot check it. A detection ID names the measurement. The CSV export
holds the IDs in the `detection_ids` column.

## 6. Ethics and legal position

State this position in the methods chapter.

1. Every trial ran against an origin that the researcher controls.
2. No trial sent a request to a third-party website.
3. The work builds a detector. It publishes no evasion tool.
4. The harness stores no personal data. It stores a fingerprint of the test
   client only.

The legal line in this field runs through the access control, not through the
data. Courts in the United States held that the collection of public data does
not by itself breach the Computer Fraud and Abuse Act. The defeat of a technical
control is a separate question, and recent claims use the Digital Millennium
Copyright Act instead. A local origin keeps the work clear of both.

Check the rules of your institution as well. Many ethics boards treat any test
against a live third-party service as human-subjects adjacent work.

## 7. Threats to validity

State each threat and how you handled it.

1. **Version drift.** A JA4 hash changes with a browser release. Record the
   version and the date of every trial.
2. **Hand-set weights.** The engine uses fixed weights, not a trained model.
   Report the weights in an appendix so a reader can reproduce the score.
3. **One origin.** Results from one harness do not transfer to a commercial
   system without a caveat. Frame the claim as a mechanism study.
4. **Small behavior sample.** The behavior layer reads one page view. Do not
   claim a result about long-session behavior modeling.
5. **Debugger ambiguity.** `runtime.cdp_attached` fires for any Chrome DevTools
   Protocol client, including an open DevTools window. Record the DevTools state
   of every run, or the control class inherits an automation signal.
6. **Everything here is page-visible.** A tool that patches the main world
   consistently defeats the `browser` and `consistency` layers. What survives
   is `runtime`, `environment`, `behavior` and `tls`. Say which layers carried
   a result, not only that the harness caught the client.
