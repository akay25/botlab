"""Complete every task on the page with Selenium, naively or as a hand would.

    python3 tests/selenium_tasks.py --url https://127.0.0.1:8443
    python3 tests/selenium_tasks.py --mode human --seed 7

Selenium differs from Playwright in one way that matters to the behaviour
layer: send_keys goes through the WebDriver key protocol, so real keydown,
keypress and keyup events reach the page even in naive mode. The harness
therefore sees keystrokes rather than a value appearing from nowhere, and
judges their timing instead.

It differs in a second way that matters to the pointer. WebDriver has no
"move to an absolute viewport coordinate" command: every move is relative to
where the pointer already is. The Pointer class below tracks that position, so
a path can be issued as a sequence of small offsets. Each offset produces
exactly one mousemove, so the sampling density of the path is decided entirely
by how many steps the script chooses to issue.

Needs Selenium 4.6 or later, which fetches a matching chromedriver through
Selenium Manager. Record the Chrome version you used: a JA4 hash and a
fingerprint are worthless without one.
"""

import argparse
import math
import random
import sys
import time

from selenium import webdriver
from selenium.webdriver import ActionChains
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import WebDriverWait

NAME = "Ada Lovelace"
EMAIL = "ada@example.org"

# Never reach for these. They are invisible, outside the tab order and hidden
# from assistive technology, so touching one is scored as near-conclusive
# evidence of automation. In Task 4 that means selecting #fitts-target by id,
# never .fitts-target by class: one element of that class is a decoy.
HONEYPOTS = ("fitts-decoy", "hp-email", "hp-submit")


class Pointer:
    """A virtual pointer, because WebDriver only moves relative to itself."""

    def __init__(self, driver):
        self.driver = driver
        self.x = None
        self.y = None

    def centre_of(self, element):
        """Return the element's centre in viewport coordinates."""
        return self.driver.execute_script(
            "var r = arguments[0].getBoundingClientRect();"
            "return [r.left + r.width / 2, r.top + r.height / 2, r.width];",
            element)

    def anchor(self, element):
        """Put the pointer on an element and learn where that is."""
        ActionChains(self.driver).move_to_element(element).perform()
        centre = self.centre_of(element)
        self.x, self.y = centre[0], centre[1]
        return centre

    def move_to(self, x, y):
        """Move in one jump. One mousemove event reaches the page."""
        if self.x is None:
            raise RuntimeError("anchor() the pointer before moving it")
        ActionChains(self.driver).move_by_offset(
            int(round(x - self.x)), int(round(y - self.y))).perform()
        self.x, self.y = x, y

    def glide(self, x, y, steps=None, pause=(0.008, 0.02)):
        """Move along a curved path issued as many small offsets."""
        if self.x is None:
            raise RuntimeError("anchor() the pointer before moving it")
        start = (self.x, self.y)
        distance = math.dist(start, (x, y))
        if distance < 1:
            return
        if steps is None:
            steps = max(10, min(70, int(distance / 9)))
        middle = ((start[0] + x) / 2, (start[1] + y) / 2)
        bulge = max(18.0, distance * 0.16)
        control = (middle[0] + random.uniform(-bulge, bulge),
                   middle[1] + random.uniform(-bulge, bulge))

        for index in range(1, steps + 1):
            fraction = index / steps
            eased = 3 * fraction ** 2 - 2 * fraction ** 3
            inverse = 1 - eased
            px = (inverse * inverse * start[0] + 2 * inverse * eased * control[0]
                  + eased * eased * x)
            py = (inverse * inverse * start[1] + 2 * inverse * eased * control[1]
                  + eased * eased * y)
            self.move_to(px + random.gauss(0, 0.6), py + random.gauss(0, 0.6))
            time.sleep(random.uniform(*pause))

    def press(self, hold=(0.04, 0.09)):
        ActionChains(self.driver).click_and_hold().perform()
        time.sleep(random.uniform(*hold))
        ActionChains(self.driver).release().perform()

    def acquire(self, centre, width):
        """Overshoot the target, correct back onto it, then click."""
        radius = max(4.0, width / 2)
        scatter = max(6.0, radius * 0.55)
        self.glide(centre[0] + random.uniform(-scatter, scatter),
                   centre[1] + random.uniform(-scatter, scatter))
        time.sleep(random.uniform(0.04, 0.11))
        self.glide(centre[0] + random.uniform(-radius * 0.3, radius * 0.3),
                   centre[1] + random.uniform(-radius * 0.3, radius * 0.3),
                   steps=random.randint(5, 12))
        time.sleep(random.uniform(0.03, 0.09))
        self.press()


# ----------------------------------------------------------------- tasks

def task_typing(driver, mode):
    """Task 1. send_keys presses each key in turn in either mode."""
    name = driver.find_element(By.ID, "field-name")
    email = driver.find_element(By.ID, "field-email")
    if mode == "naive":
        name.send_keys(NAME)
        email.send_keys(EMAIL)
        return

    for field, words in ((name, NAME), (email, EMAIL)):
        field.click()
        time.sleep(random.uniform(0.08, 0.2))
        for character in words:
            field.send_keys(character)
            pause = random.gauss(0.11, 0.045)
            if character in " @.":
                pause += random.uniform(0.04, 0.13)
            time.sleep(max(0.03, pause))
        time.sleep(random.uniform(0.2, 0.5))


def task_targets(driver, mode, pointer):
    """Task 2. Click the three circles."""
    for identifier in ("target-1", "target-2", "target-3"):
        element = driver.find_element(By.ID, identifier)
        if mode == "naive":
            # click() jumps to the element centre. No path is produced.
            element.click()
            pointer.anchor(element)
            continue
        centre = pointer.centre_of(element)
        pointer.acquire((centre[0], centre[1]), centre[2])
        pointer.x, pointer.y = centre[0], centre[1]
        time.sleep(random.uniform(0.15, 0.4))


def task_slider(driver, mode, pointer):
    """Task 3, optional. Drag the slider into the 55 to 85 band."""
    slider = driver.find_element(By.ID, "slider")
    box = driver.execute_script(
        "var r = arguments[0].getBoundingClientRect();"
        "return [r.left, r.top, r.width, r.height];", slider)
    left, top, width, height = box
    y = top + height / 2
    value = random.uniform(64, 76) if mode == "human" else 70
    end_x = left + width * value / 100.0

    pointer.anchor(slider)
    pointer.move_to(left + 2, y)
    ActionChains(driver).click_and_hold().perform()
    if mode == "naive":
        pointer.move_to(end_x, y)
    else:
        time.sleep(random.uniform(0.05, 0.12))
        pointer.glide(end_x, y, steps=random.randint(18, 40))
        time.sleep(random.uniform(0.04, 0.1))
    ActionChains(driver).release().perform()
    time.sleep(random.uniform(0.2, 0.45))


def task_acquisition(driver, mode, pointer):
    """Task 4, optional. Acquire the ten targets, one at a time.

    #fitts-target moves and resizes after every hit, so read its box each time
    rather than caching it, and find it by id so the decoy is never touched.
    """
    total = driver.execute_script(
        "return window.botlab.tasks().acquisitions_total;") or 10
    for _ in range(total * 3):          # bounded, never a while True
        done = driver.execute_script("return window.botlab.tasks().acquisitions;")
        if done >= total:
            break
        element = driver.find_element(By.ID, "fitts-target")
        if not element.is_displayed():
            break
        centre = pointer.centre_of(element)
        if mode == "naive":
            element.click()
            pointer.x, pointer.y = centre[0], centre[1]
        else:
            pointer.acquire((centre[0], centre[1]), centre[2])
            pointer.x, pointer.y = centre[0], centre[1]
            time.sleep(random.uniform(0.08, 0.22))


# ------------------------------------------------------------------- run

def run(url, label, mode, headless):
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1440,1000")
    # The harness serves a certificate it signed itself.
    options.add_argument("--ignore-certificate-errors")
    options.set_capability("acceptInsecureCerts", True)

    driver = webdriver.Chrome(options=options)
    try:
        driver.get("%s/?label=%s" % (url.rstrip("/"), label))
        WebDriverWait(driver, 15).until(
            expected_conditions.presence_of_element_located((By.ID, "fitts-target")))
        if mode == "human":
            time.sleep(random.uniform(0.4, 0.9))

        pointer = Pointer(driver)
        pointer.anchor(driver.find_element(By.ID, "field-name"))

        task_typing(driver, mode)
        task_targets(driver, mode, pointer)
        task_slider(driver, mode, pointer)
        task_acquisition(driver, mode, pointer)

        tasks = driver.execute_script("return window.botlab.tasks();")
        # finish() returns a promise, so hand the result back through a callback.
        result = driver.execute_async_script(
            "const done = arguments[arguments.length - 1];"
            "window.botlab.finish().then(done);")
        return result, tasks
    finally:
        driver.quit()


def report(result, tasks, url, mode):
    print("mode     %s" % mode)
    print("tasks    typing %s, targets %s/3, drag %s, acquisitions %s/%s"
          % (tasks.get("typing"), tasks.get("targets"), tasks.get("drag"),
             tasks.get("acquisitions"), tasks.get("acquisitions_total")))
    print("score    %s  (%s)" % (result["score"], result["verdict"]))
    print("caught   %s, strongest %s"
          % (result["first_catching_layer"], result["strongest_layer"]))
    print("report   %s/report/%s" % (url.rstrip("/"), result.get("session_id", "")))

    print("\nbehaviour signals")
    for signal in result["signals"]:
        if signal["layer"] == "behavior":
            print("  %-40s %+.1f  %s"
                  % (signal["id"], signal["weight"], signal["detail"]))

    metrics = result.get("behavior_metrics") or {}
    law = metrics.get("fitts") or {}
    if law.get("measured"):
        print("\nfitts's law over %d targets" % law["measured"])
        print("  %-24s %s ms per bit" % ("slope", law.get("slope_ms_per_bit")))
        print("  %-24s %s" % ("fit r squared", law.get("r_squared")))
        print("  %-24s %s" % ("throughput bits/s", law.get("throughput_bits_per_s")))

    traps = (metrics.get("honeypots") or {}).get("count", 0)
    print("\nhoneypots touched: %d%s"
          % (traps, "" if not traps else "   <-- the script has a bug, fix it"))
    return traps


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://127.0.0.1:8443")
    parser.add_argument("--mode", choices=["naive", "human"], default="naive")
    parser.add_argument("--label", default="")
    parser.add_argument("--headed", action="store_true", help="Show the browser window.")
    parser.add_argument("--seed", type=int, default=None, help="Make a run repeatable.")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)
    label = args.label or ("selenium-" + args.mode)

    result, tasks = run(args.url, label, args.mode, headless=not args.headed)
    traps = report(result, tasks, args.url, args.mode)

    if traps:
        return 1
    if not tasks.get("ready"):
        print("\nThe required tasks were not completed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
