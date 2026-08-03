"""Drive the task page the obvious way, with no attempt to look human.

This is the baseline. It uses the calls a script reaches for first: fill() to
put text in a field and click() to hit a target. Neither one moves a pointer
or presses a key, so the behaviour layer has almost nothing that looks like a
person, and several signals fire.

    pip install playwright && playwright install chromium
    python3 examples/playwright_naive.py --url https://127.0.0.1:8443

Compare the score with playwright_human.py against the same harness.
"""

import argparse

from playwright.sync_api import sync_playwright

NAME = "Ada Lovelace"
EMAIL = "ada@example.org"


def run(url, label, headless, executable=None):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, executable_path=executable)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()
        page.goto("%s/?label=%s" % (url.rstrip("/"), label))

        # fill() sets the value through the debugger. No key is ever pressed.
        page.fill("#field-name", NAME)
        page.fill("#field-email", EMAIL)

        # click() jumps straight to the element centre and clicks it.
        for target in ("#target-1", "#target-2", "#target-3"):
            page.click(target)

        result = page.evaluate("window.botlab.finish()")
        browser.close()
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://127.0.0.1:8443")
    parser.add_argument("--label", default="playwright-naive")
    parser.add_argument("--headed", action="store_true", help="Show the browser window.")
    parser.add_argument("--executable", default=None,
                        help="Path to a specific Chrome build. Record the version you used.")
    args = parser.parse_args()

    result = run(args.url, args.label, headless=not args.headed, executable=args.executable)
    print("score    %s  (%s)" % (result["score"], result["verdict"]))
    print("caught   %s, strongest %s"
          % (result["first_catching_layer"], result["strongest_layer"]))
    print("report   %s/report/%s" % (args.url.rstrip("/"), result.get("session_id", "")))
    print("\nbehaviour signals")
    for signal in result["signals"]:
        if signal["layer"] == "behavior":
            print("  %-38s %+.1f  %s" % (signal["id"], signal["weight"], signal["detail"]))


if __name__ == "__main__":
    main()
