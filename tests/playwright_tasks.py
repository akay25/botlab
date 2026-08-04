"""Complete every task on the page with Playwright, naively or as a hand would.

    python3 tests/playwright_tasks.py --url https://127.0.0.1:8443
    python3 tests/playwright_tasks.py --mode human --seed 7

Both modes perform the identical four tasks, so the two reports compare like
for like. They differ only in how the input is produced.

  naive   fill() for text and click() for targets. Neither presses a key nor
          moves a pointer, so the behaviour layer sees a value appearing from
          nowhere and clicks with no approach.

  human   types key by key with a varying delay, and moves the pointer along a
          curved path with easing, jitter, an overshoot and a correction.

Nothing here defeats an access control. It changes only the timing and the path
of the tool's own input, against a harness the researcher runs. It is the first
two rungs of the evasion ladder in PROTOCOL.md, not an evasion tool.

Task 4 is the interesting one. It shows ten targets that differ in size and in
distance, and Fitts's law says a hand needs measurably longer for a small
distant one. `human` mode scales its movement with distance, because that is
what interpolating a path does, but it never pays for the *width* of the target.
Watch whether that is enough.
"""

import argparse
import math
import random
import sys
import time

from playwright.sync_api import sync_playwright

NAME = "Ada Lovelace"
EMAIL = "ada@example.org"

# The three controls the page hides. Nothing that can see the page can reach
# them, so a script must not touch them either. Selecting by id rather than by
# class is what keeps the decoy out of Task 4.
HONEYPOTS = ("#fitts-decoy", "#hp-email", "#hp-submit")


# --------------------------------------------------------------- pointer

def ease(fraction):
    """Ease in and out, so step length varies instead of being constant."""
    return 3 * fraction * fraction - 2 * fraction * fraction * fraction


def bezier(start, control, end, t):
    inverse = 1 - t
    return (inverse * inverse * start[0] + 2 * inverse * t * control[0] + t * t * end[0],
            inverse * inverse * start[1] + 2 * inverse * t * control[1] + t * t * end[1])


def glide(page, start, end, steps=None):
    """Move along a curved, unevenly sampled path and return where it ended."""
    distance = math.dist(start, end)
    if distance < 1:
        return start
    if steps is None:
        # Roughly what a device reporting at 60 Hz would produce over this far.
        steps = max(10, min(90, int(distance / 7)))
    middle = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
    bulge = max(20.0, distance * 0.16)
    control = (middle[0] + random.uniform(-bulge, bulge),
               middle[1] + random.uniform(-bulge, bulge))

    for index in range(1, steps + 1):
        x, y = bezier(start, control, end, ease(index / steps))
        page.mouse.move(x + random.gauss(0, 0.7), y + random.gauss(0, 0.7))
        time.sleep(random.uniform(0.008, 0.02))
    return end


def approach(page, position, centre, radius):
    """Glide to a target, overshoot it, then correct back onto it."""
    scatter = max(6.0, radius * 0.55)
    overshoot = (centre[0] + random.uniform(-scatter, scatter),
                 centre[1] + random.uniform(-scatter, scatter))
    position = glide(page, position, overshoot)
    time.sleep(random.uniform(0.04, 0.11))

    landing = (centre[0] + random.uniform(-radius * 0.3, radius * 0.3),
               centre[1] + random.uniform(-radius * 0.3, radius * 0.3))
    position = glide(page, position, landing, steps=random.randint(5, 12))
    time.sleep(random.uniform(0.03, 0.09))
    page.mouse.down()
    time.sleep(random.uniform(0.04, 0.09))
    page.mouse.up()
    return position


def centre_of(box):
    return (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)


# ----------------------------------------------------------------- tasks

def task_typing(page, mode):
    """Task 1. Put a name and an email address into the two fields."""
    if mode == "naive":
        # fill() sets the value through the debugger. No key is ever pressed.
        page.fill("#field-name", NAME)
        page.fill("#field-email", EMAIL)
        return

    for selector, words in (("#field-name", NAME), ("#field-email", EMAIL)):
        page.click(selector)
        time.sleep(random.uniform(0.08, 0.2))
        for character in words:
            # keyboard.type emits a real keydown, keypress and keyup, which is
            # what lets the harness measure dwell and flight at all.
            page.keyboard.type(character, delay=0)
            pause = random.gauss(0.11, 0.045)
            if character in " @.":
                pause += random.uniform(0.04, 0.13)
            time.sleep(max(0.03, pause))
        time.sleep(random.uniform(0.2, 0.5))


def task_targets(page, mode, position):
    """Task 2. Click the three circles."""
    for selector in ("#target-1", "#target-2", "#target-3"):
        if mode == "naive":
            page.click(selector)
            continue
        box = page.locator(selector).bounding_box()
        position = approach(page, position, centre_of(box), box["width"] / 2)
        time.sleep(random.uniform(0.15, 0.4))
    return position


def task_slider(page, mode, position):
    """Task 3, optional. Drag the slider into the 55 to 85 band."""
    slider = page.locator("#slider")
    box = slider.bounding_box()
    if not box:
        return position
    y = box["y"] + box["height"] / 2
    start = (box["x"] + 2, y)
    target_value = random.uniform(64, 76) if mode == "human" else 70
    end = (box["x"] + box["width"] * target_value / 100.0, y)

    if mode == "naive":
        page.mouse.move(start[0], start[1])
        page.mouse.down()
        page.mouse.move(end[0], end[1])
        page.mouse.up()
        return end

    position = glide(page, position, start)
    page.mouse.down()
    time.sleep(random.uniform(0.05, 0.12))
    position = glide(page, start, end, steps=random.randint(18, 40))
    time.sleep(random.uniform(0.04, 0.1))
    page.mouse.up()
    time.sleep(random.uniform(0.2, 0.45))
    return position


def task_acquisition(page, mode, position):
    """Task 4, optional. Acquire the ten targets, one at a time.

    The single button #fitts-target moves and resizes after every hit, so its
    box has to be read again each time. Never select this task's targets by
    class: one of them is a honeypot that is never displayed.
    """
    total = page.evaluate("window.botlab.tasks().acquisitions_total") or 10
    for _ in range(total * 3):          # a bounded loop, never a while True
        done = page.evaluate("window.botlab.tasks().acquisitions")
        if done >= total:
            break
        target = page.locator("#fitts-target")
        if not target.is_visible():
            break
        box = target.bounding_box()
        if not box:
            break
        if mode == "naive":
            # Straight to the middle, at the same cost whatever the size.
            page.mouse.click(*centre_of(box))
            position = centre_of(box)
        else:
            position = approach(page, position, centre_of(box), box["width"] / 2)
            time.sleep(random.uniform(0.08, 0.22))
    return position


# ------------------------------------------------------------------- run

def run(url, label, mode, headless, executable=None):
    with sync_playwright() as play:
        browser = play.chromium.launch(headless=headless, executable_path=executable)
        context = browser.new_context(ignore_https_errors=True,
                                      viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        page.goto("%s/?label=%s" % (url.rstrip("/"), label))
        page.wait_for_selector("#fitts-target")

        position = (random.uniform(200, 600), random.uniform(120, 260))
        if mode == "human":
            time.sleep(random.uniform(0.4, 0.9))
            page.mouse.move(*position)

        task_typing(page, mode)
        position = task_targets(page, mode, position)
        position = task_slider(page, mode, position)
        task_acquisition(page, mode, position)

        tasks = page.evaluate("window.botlab.tasks()")
        result = page.evaluate("window.botlab.finish()")
        browser.close()
        return result, tasks


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
    parser.add_argument("--executable", default=None,
                        help="Path to a specific Chrome build. Record the version you used.")
    parser.add_argument("--seed", type=int, default=None, help="Make a run repeatable.")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)
    label = args.label or ("playwright-" + args.mode)

    result, tasks = run(args.url, label, args.mode,
                        headless=not args.headed, executable=args.executable)
    traps = report(result, tasks, args.url, args.mode)

    # The script fails if it tripped a honeypot or left a required task undone.
    # Neither says anything about the harness; both say the script is wrong.
    if traps:
        return 1
    if not tasks.get("ready"):
        print("\nThe required tasks were not completed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
