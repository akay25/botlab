"""Drive the task page while imitating a hand, and see what still gives it away.

This is the interesting row of the evasion ladder. The script does everything
the naive version does not:

  - types key by key, with a varying delay, so real key events are produced
  - moves the pointer along a curved path built from a bezier, with easing so
    the step lengths vary, jitter on every point, and a varying frame delay
  - overshoots each target and corrects, the way an arm does
  - pauses between tasks

Nothing here defeats an access control. It changes only the timing and the
path of the tool's own input, against a harness the researcher runs.

    python3 examples/playwright_human.py --url https://127.0.0.1:8443

Run playwright_naive.py against the same harness and compare the two reports.
"""

import argparse
import math
import random
import time

from playwright.sync_api import sync_playwright

NAME = "Ada Lovelace"
EMAIL = "ada@example.org"


def ease(t):
    """Return an ease-in-out position for a fraction of the way through."""
    return 3 * t * t - 2 * t * t * t


def bezier(start, control, end, t):
    inverse = 1 - t
    x = inverse * inverse * start[0] + 2 * inverse * t * control[0] + t * t * end[0]
    y = inverse * inverse * start[1] + 2 * inverse * t * control[1] + t * t * end[1]
    return x, y


def glide(page, start, end, steps=None):
    """Move the pointer along a curved, unevenly sampled path."""
    distance = math.dist(start, end)
    if steps is None:
        # Roughly what a 60 Hz device would report over this distance.
        steps = max(12, min(90, int(distance / 7)))
    midpoint = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
    offset = max(24.0, distance * 0.18)
    control = (midpoint[0] + random.uniform(-offset, offset),
               midpoint[1] + random.uniform(-offset, offset))

    for index in range(1, steps + 1):
        fraction = ease(index / steps)
        x, y = bezier(start, control, end, fraction)
        x += random.gauss(0, 0.7)
        y += random.gauss(0, 0.7)
        page.mouse.move(x, y)
        time.sleep(random.uniform(0.008, 0.021))
    return end


def approach(page, position, locator):
    """Glide to a target, overshoot it, then correct back onto it."""
    box = locator.bounding_box()
    centre = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)

    # Aim slightly past the target, as an arm under momentum does.
    overshoot = (centre[0] + random.uniform(-26, 26),
                 centre[1] + random.uniform(-22, 22))
    position = glide(page, position, overshoot)
    time.sleep(random.uniform(0.04, 0.11))

    # Then make the short corrective move onto it.
    landing = (centre[0] + random.uniform(-4, 4), centre[1] + random.uniform(-4, 4))
    position = glide(page, position, landing, steps=random.randint(6, 12))
    time.sleep(random.uniform(0.03, 0.09))
    page.mouse.down()
    time.sleep(random.uniform(0.04, 0.09))
    page.mouse.up()
    return position


def human_type(page, selector, words):
    """Type key by key, pausing longer between words and after punctuation."""
    page.click(selector)
    time.sleep(random.uniform(0.08, 0.2))
    for character in words:
        # keyboard.type sends a real keydown, keypress and keyup for the
        # character. keyboard.insert_text would not, and the harness reads
        # exactly that difference.
        page.keyboard.type(character, delay=0)
        pause = random.gauss(0.11, 0.045)
        if character in " @.":
            pause += random.uniform(0.04, 0.13)
        time.sleep(max(0.03, pause))


def run(url, label, headless, executable=None):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, executable_path=executable)
        context = browser.new_context(ignore_https_errors=True,
                                      viewport={"width": 1280, "height": 900})
        page = context.new_page()
        page.goto("%s/?label=%s" % (url.rstrip("/"), label))
        page.wait_for_selector("#target-1")
        time.sleep(random.uniform(0.4, 0.9))

        position = (random.uniform(200, 500), random.uniform(120, 260))
        page.mouse.move(position[0], position[1])

        human_type(page, "#field-name", NAME)
        time.sleep(random.uniform(0.2, 0.5))
        human_type(page, "#field-email", EMAIL)
        time.sleep(random.uniform(0.3, 0.7))

        for selector in ("#target-1", "#target-2", "#target-3"):
            position = approach(page, position, page.locator(selector))
            time.sleep(random.uniform(0.15, 0.4))

        result = page.evaluate("window.botlab.finish()")
        browser.close()
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://127.0.0.1:8443")
    parser.add_argument("--label", default="playwright-human")
    parser.add_argument("--headed", action="store_true", help="Show the browser window.")
    parser.add_argument("--executable", default=None,
                        help="Path to a specific Chrome build. Record the version you used.")
    parser.add_argument("--seed", type=int, default=None, help="Make a run repeatable.")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

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
