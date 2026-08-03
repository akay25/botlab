"""Drive the task page with Selenium, the obvious way.

Selenium differs from Playwright in one way that matters here: send_keys goes
through the WebDriver key protocol, so real keydown, keypress and keyup events
reach the page. The behaviour layer therefore sees keystrokes rather than a
value appearing from nowhere, and judges their timing instead.

    pip install selenium
    python3 examples/selenium_naive.py --url https://127.0.0.1:8443

Selenium needs a chromedriver matching your Chrome. Selenium 4.6 and later
fetch one for you through Selenium Manager.
"""

import argparse
import json

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import WebDriverWait

NAME = "Ada Lovelace"
EMAIL = "ada@example.org"


def run(url, label, headless):
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    # The harness serves a certificate it signed itself.
    options.add_argument("--ignore-certificate-errors")
    options.set_capability("acceptInsecureCerts", True)

    driver = webdriver.Chrome(options=options)
    try:
        driver.get("%s/?label=%s" % (url.rstrip("/"), label))
        WebDriverWait(driver, 15).until(
            expected_conditions.presence_of_element_located((By.ID, "target-1")))

        # send_keys presses each key in turn, so real key events are produced.
        driver.find_element(By.ID, "field-name").send_keys(NAME)
        driver.find_element(By.ID, "field-email").send_keys(EMAIL)

        # click() jumps to the element centre. No pointer path is produced.
        for target in ("target-1", "target-2", "target-3"):
            driver.find_element(By.ID, target).click()

        # finish() returns a promise, so hand the result back through a callback.
        result = driver.execute_async_script(
            "const done = arguments[arguments.length - 1];"
            "window.botlab.finish().then(done);")
        return result
    finally:
        driver.quit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://127.0.0.1:8443")
    parser.add_argument("--label", default="selenium-naive")
    parser.add_argument("--headed", action="store_true", help="Show the browser window.")
    parser.add_argument("--json", action="store_true", help="Print the whole result.")
    args = parser.parse_args()

    result = run(args.url, args.label, headless=not args.headed)
    if args.json:
        print(json.dumps(result, indent=2))
        return

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
