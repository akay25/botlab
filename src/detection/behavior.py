"""Derive behavioural metrics from raw interaction telemetry, then judge them.

The page records raw events and sends them untouched. Every number below is
computed here, on the server, so a run can be re-scored later from the stored
telemetry when the rules change. That property matters more than speed: a
metric computed in the browser and thrown away cannot be checked by a reader.

Two ideas carry most of the weight.

A hand moves a pointer under a control loop. It accelerates, overshoots,
notices, and corrects, so the speed profile has several peaks and the step
lengths vary continuously. An automation tool interpolates between two points,
so its steps are equal and its clock is even.

A hand presses a key and holds it for a while. The hold time varies by finger
and by key. A driver that synthesises key events often releases in the same
millisecond it pressed, and repeats that exactly.
"""

import math
import statistics

# A step longer than this, with no event between, is a jump rather than a move.
TELEPORT_PX = 150.0
# A gap longer than this in the middle of a movement is a pause, not a sample.
PAUSE_MS = 120.0
# Two vectors that differ by more than this have changed direction.
TURN_DEGREES = 20.0
# A key held for less than this was not held at all.
ZERO_DWELL_MS = 1.0
# The range a finger holds a key for. Published keystroke-dynamics work puts
# the mean near 100 ms; anything under about 25 ms is not a finger. Measure
# your own control group and change these before reporting a result.
HUMAN_DWELL_MS = (25, 200)
# Spread divided by mean, below which a timing series is too even to be a hand.
# A driver that sleeps a fixed interval between keys lands near zero; published
# keystroke-dynamics work puts human flight variation far above these. They are
# reasoned, not measured: set them from your own control group before reporting.
MIN_HUMAN_FLIGHT_CV = 0.15
MIN_HUMAN_DWELL_CV = 0.12
# Below this many presses the spread of a series means nothing.
MIN_TIMING_SAMPLES = 5
# A modifier is held while the next key lands, so the gap from Shift-down to
# letter-down is near zero and says nothing about typing rhythm. Flight is
# measured between non-modifier presses only.
MODIFIER_KEYS = {"Shift", "Control", "Alt", "Meta", "CapsLock", "AltGraph"}

# Fitts's law. The time to acquire a target grows with the index of difficulty,
# ID = log2(2D/W), where D is the distance the hand travels and W the width of
# the target. For a hand the relationship is a straight line, MT = a + b·ID,
# and it holds tightly. A tool that jumps the pointer to a coordinate takes the
# same time whatever it is aiming at, so its slope is flat and its throughput is
# not physical.
MIN_FITTS_SAMPLES = 5
# Throughput, ID over MT, in bits per second. ISO 9241-9 studies put a mouse at
# roughly 3.7 to 10 bits per second. Above this is not a hand on a mouse.
MAX_HUMAN_THROUGHPUT = 14.0
# Milliseconds of movement time per bit of difficulty. A hand is around 100 to
# 200. A tool that ignores the target reads near zero.
MIN_FITTS_SLOPE_MS = 40.0
# How well the straight line has to fit before the fit is worth crediting.
MIN_FITTS_FIT = 0.5
# The window before a click in which a hand is still approaching the target.
APPROACH_MS = 250.0
# Below this sampling density a path has no readable shape, only endpoints.
MIN_SAMPLES_PER_100PX = 3.0


def _stdev(values):
    return statistics.pstdev(values) if len(values) >= 2 else 0.0


def _mean(values):
    return statistics.fmean(values) if values else 0.0


def _round_key(value, places=2):
    return round(float(value), places)


def _modal_share(values, places=2):
    """Return the share of values taken by the single most common value."""
    if not values:
        return 0.0
    counts = {}
    for value in values:
        key = _round_key(value, places)
        counts[key] = counts.get(key, 0) + 1
    return max(counts.values()) / len(values)


def _smooth(values, window=5):
    """Return a moving average, so that sample noise is not read as structure."""
    if len(values) < window:
        return list(values)
    half = window // 2
    out = []
    for index in range(len(values)):
        low = max(0, index - half)
        high = min(len(values), index + half + 1)
        out.append(sum(values[low:high]) / (high - low))
    return out


def _segments(points, click_times):
    """Split a path into the separate movements that make it up.

    Straightness across a whole session is meaningless: a path that visits
    three targets in different corners is bent by the task, not by a hand.
    A movement ends when the pointer clicks or when it rests.
    """
    breaks = set()
    for index in range(1, len(points)):
        if float(points[index].get("t", 0)) - float(points[index - 1].get("t", 0)) > PAUSE_MS:
            breaks.add(index)
    for when in click_times:
        for index, point in enumerate(points):
            if float(point.get("t", 0)) >= when:
                breaks.add(index)
                break

    out = []
    start = 0
    for index in sorted(breaks):
        if index - start >= 2:
            out.append(points[start:index])
        start = index
    if len(points) - start >= 2:
        out.append(points[start:])
    return out


def _submovement_count(speeds):
    """Count the corrective sub-movements in a speed profile.

    A hand aims, undershoots or overshoots, and corrects. Each correction is a
    fresh acceleration, so the speed profile dips and rises again. A linear
    interpolation between two points has one plateau and no dips.
    """
    if len(speeds) < 5:
        return 0
    peak = max(speeds)
    if peak <= 0:
        return 0
    floor = peak * 0.45
    dips = 0
    descending = False
    for previous, current in zip(speeds, speeds[1:]):
        if current < previous:
            descending = True
        elif current > previous and descending:
            # The profile turned upward again. It is a correction only if it
            # fell far enough to have stopped being one continuous sweep.
            if previous < floor:
                dips += 1
            descending = False
    return dips


def _angle_between(a, b):
    """Return the angle in degrees between two movement vectors."""
    ax, ay = a
    bx, by = b
    la = math.hypot(ax, ay)
    lb = math.hypot(bx, by)
    if la == 0 or lb == 0:
        return 0.0
    cosine = max(-1.0, min(1.0, (ax * bx + ay * by) / (la * lb)))
    return math.degrees(math.acos(cosine))


def _analyse_pointer(points, click_times=None):
    """Return the shape, the timing, and the integrity of a pointer path."""
    out: dict = {"count": len(points)}
    if len(points) < 2:
        return out

    xs = [float(p.get("x", 0)) for p in points]
    ys = [float(p.get("y", 0)) for p in points]
    ts = [float(p.get("t", 0)) for p in points]

    steps = [math.dist((xs[i], ys[i]), (xs[i + 1], ys[i + 1])) for i in range(len(xs) - 1)]
    gaps = [ts[i + 1] - ts[i] for i in range(len(ts) - 1)]
    traveled = sum(steps)
    direct = math.dist((xs[0], ys[0]), (xs[-1], ys[-1]))

    out["duration_ms"] = round(ts[-1] - ts[0], 1)
    out["traveled_px"] = round(traveled, 1)
    out["direct_px"] = round(direct, 1)
    out["straightness"] = round(direct / traveled, 4) if traveled else None

    moving = [s for s in steps if s > 0]
    out["step_px_mean"] = round(_mean(moving), 3)
    out["step_px_stdev"] = round(_stdev(moving), 3)
    out["step_constant_share"] = round(_modal_share(moving), 3)
    out["distinct_step_lengths"] = len({_round_key(s) for s in moving})
    out["teleports"] = sum(1 for s in steps if s > TELEPORT_PX)

    # How finely the path was sampled. A mouse reports at 60 Hz or better, so
    # crossing the screen yields dozens of events. A driver that jumps the
    # pointer to a target reports one. Every judgement about the *shape* of a
    # path is meaningless below a few samples per 100 px, because there is no
    # shape to read, so this value gates those checks.
    out["samples_per_100px"] = (round(len(points) / (traveled / 100.0), 2)
                                if traveled >= 1 else None)

    positive_gaps = [g for g in gaps if g > 0]
    out["interval_ms_mean"] = round(_mean(positive_gaps), 3)
    out["interval_ms_stdev"] = round(_stdev(positive_gaps), 3)
    out["distinct_intervals"] = len({_round_key(g, 1) for g in positive_gaps})
    out["pauses"] = sum(1 for g in gaps if g > PAUSE_MS)

    speeds = [s / g for s, g in zip(steps, gaps) if g > 0]
    out["speed_mean_px_ms"] = round(_mean(speeds), 4)
    out["speed_max_px_ms"] = round(max(speeds), 4) if speeds else 0.0
    out["speed_stdev"] = round(_stdev(speeds), 4)

    # Read shape one movement at a time. The whole-session figures above stay
    # in the report for reference, but the judgement uses these.
    parts = _segments(points, click_times or [])
    straightnesses = []
    corrections = []
    for part in parts:
        px = [float(p.get("x", 0)) for p in part]
        py = [float(p.get("y", 0)) for p in part]
        pt = [float(p.get("t", 0)) for p in part]
        part_steps = [math.dist((px[i], py[i]), (px[i + 1], py[i + 1]))
                      for i in range(len(px) - 1)]
        part_traveled = sum(part_steps)
        if len(part) < 8 or part_traveled < 60:
            continue
        part_direct = math.dist((px[0], py[0]), (px[-1], py[-1]))
        straightnesses.append(part_direct / part_traveled)
        part_gaps = [pt[i + 1] - pt[i] for i in range(len(pt) - 1)]
        part_speeds = [s / g for s, g in zip(part_steps, part_gaps) if g > 0]
        corrections.append(_submovement_count(_smooth(part_speeds)))

    out["segments"] = len(parts)
    out["measured_segments"] = len(straightnesses)
    out["segment_straightness_median"] = (round(statistics.median(straightnesses), 4)
                                          if straightnesses else None)
    out["segment_corrections_median"] = (round(statistics.median(corrections), 1)
                                         if corrections else None)
    out["submovements"] = _submovement_count(_smooth(speeds))

    accels = [(speeds[i + 1] - speeds[i]) / gaps[i + 1]
              for i in range(len(speeds) - 1) if gaps[i + 1] > 0]
    out["accel_stdev"] = round(_stdev(accels), 5)
    jerks = [(accels[i + 1] - accels[i]) for i in range(len(accels) - 1)]
    out["jerk_stdev"] = round(_stdev(jerks), 5)

    turns = 0
    for i in range(len(xs) - 2):
        first = (xs[i + 1] - xs[i], ys[i + 1] - ys[i])
        second = (xs[i + 2] - xs[i + 1], ys[i + 2] - ys[i + 1])
        if _angle_between(first, second) > TURN_DEGREES:
            turns += 1
    out["direction_changes"] = turns

    whole = sum(1 for p in points
                if float(p.get("x", 0)).is_integer() and float(p.get("y", 0)).is_integer())
    out["integer_coord_share"] = round(whole / len(points), 3)

    # A real pointer reports movementX alongside the new position, and the two
    # agree. A synthesised event often leaves movement at zero or stale.
    checked = 0
    mismatched = 0
    for i in range(1, len(points)):
        current = points[i]
        if current.get("mx") is None or current.get("my") is None:
            continue
        checked += 1
        dx = xs[i] - xs[i - 1]
        dy = ys[i] - ys[i - 1]
        if abs(float(current["mx"]) - dx) > 1.5 or abs(float(current["my"]) - dy) > 1.5:
            mismatched += 1
    out["movement_checked"] = checked
    out["movement_mismatch_share"] = round(mismatched / checked, 3) if checked else None

    pressures = [float(p["p"]) for p in points if p.get("p") is not None]
    out["distinct_pressures"] = len({_round_key(v, 3) for v in pressures})
    out["untrusted"] = sum(1 for p in points if p.get("tr") is False)
    return out


def _analyse_keys(events, duration_ms):
    """Pair key presses with their releases and measure the timing of each."""
    out: dict = {"event_count": len(events)}
    downs = [e for e in events if e.get("type") == "down"]
    ups = [e for e in events if e.get("type") == "up"]
    out["down_count"] = len(downs)
    out["up_count"] = len(ups)
    if not downs:
        return out

    # Match each release to the most recent unmatched press of the same key, and
    # keep the pairing in press order so every dwell stays attached to the key
    # it belongs to. The report draws the series from this; the aggregates below
    # are order-independent and unchanged by it.
    pending: dict = {}
    presses = []
    for event in sorted(events, key=lambda e: float(e.get("t", 0))):
        code = event.get("code") or event.get("key")
        if event.get("type") == "down":
            record = {
                "t": float(event.get("t", 0)),
                "key": str(event.get("key", "")),
                "dwell": None,
                "flight": None,
            }
            presses.append(record)
            pending.setdefault(code, []).append(record)
        elif event.get("type") == "up" and pending.get(code):
            record = pending[code].pop(0)
            record["dwell"] = float(event.get("t", 0)) - record["t"]

    typing = [r for r in presses if r["key"] not in MODIFIER_KEYS]
    for previous, current in zip(typing, typing[1:]):
        current["flight"] = current["t"] - previous["t"]

    dwells = [r["dwell"] for r in presses if r["dwell"] is not None]
    flights = [r["flight"] for r in presses if r["flight"] is not None]
    ordered = sorted(downs, key=lambda e: float(e.get("t", 0)))

    out["dwell_count"] = len(dwells)
    out["dwell_ms_mean"] = round(_mean(dwells), 2)
    out["dwell_ms_stdev"] = round(_stdev(dwells), 2)
    out["dwell_ms_min"] = round(min(dwells), 2) if dwells else None
    out["zero_dwell_count"] = sum(1 for d in dwells if d <= ZERO_DWELL_MS)
    out["constant_dwell_share"] = round(_modal_share(dwells, 1), 3)
    out["flight_ms_mean"] = round(_mean(flights), 2)
    out["flight_ms_stdev"] = round(_stdev(flights), 2)
    out["constant_flight_share"] = round(_modal_share(flights, 1), 3)
    out["distinct_flights"] = len({_round_key(f, 1) for f in flights})

    # Spread relative to the mean. Raw spread cannot be judged on its own: 8 ms
    # of variation is nothing around a 200 ms mean and a great deal around a
    # 20 ms one, so a fixed millisecond threshold misreads slow and fast typists
    # in opposite directions. This is the number that says "metronome".
    out["dwell_cv"] = (round(_stdev(dwells) / _mean(dwells), 4)
                       if dwells and _mean(dwells) > 0 else None)
    out["flight_cv"] = (round(_stdev(flights) / _mean(flights), 4)
                        if flights and _mean(flights) > 0 else None)

    # One entry per key press, in the order it was typed, so the report can draw
    # the timing of every keystroke and a reader can recompute any point of it.
    out["series"] = [
        {
            "i": index,
            "key": record["key"],
            "dwell": round(record["dwell"], 2) if record["dwell"] is not None else None,
            "flight": round(record["flight"], 2) if record["flight"] is not None else None,
        }
        for index, record in enumerate(presses)
    ]

    printable = [e for e in ordered if len(str(e.get("key", ""))) == 1]
    out["printable_count"] = len(printable)
    out["backspaces"] = sum(1 for e in ordered if e.get("key") == "Backspace")
    out["repeats"] = sum(1 for e in ordered if e.get("rep"))
    minutes = (duration_ms or 0) / 60000.0
    out["chars_per_minute"] = round(len(printable) / minutes, 1) if minutes > 0 else None
    if flights:
        fastest = min(f for f in flights if f >= 0) if any(f >= 0 for f in flights) else None
        out["fastest_flight_ms"] = round(fastest, 2) if fastest is not None else None
    out["untrusted"] = sum(1 for e in events if e.get("tr") is False)
    return out


def _analyse_fitts(records):
    """Fit MT = a + b·ID over the acquisition task.

    The page records only what it can see: where each target was, how wide, when
    it appeared, when it was hit, and where the pointer was at the moment it
    appeared. Distance, difficulty, movement time and the fit are all worked out
    here, so a stored run can be re-measured when the constants change.
    """
    out: dict = {"count": len(records or [])}
    samples = []
    for index, record in enumerate(records or []):
        try:
            width = float(record.get("w") or 0)
            cx = float(record.get("cx"))
            cy = float(record.get("cy"))
            movement = float(record.get("t", 0)) - float(record.get("shown", 0))
        except (TypeError, ValueError):
            continue
        if width <= 0 or movement <= 0:
            continue

        start_x, start_y = record.get("fx"), record.get("fy")
        if start_x is None or start_y is None:
            # No pointer event before this target appeared. Fall back to where
            # the previous one was hit, which is where the hand must have been.
            if index == 0:
                continue
            previous = (records or [])[index - 1]
            start_x, start_y = previous.get("hx"), previous.get("hy")
            if start_x is None or start_y is None:
                continue
        try:
            distance = math.dist((float(start_x), float(start_y)), (cx, cy))
        except (TypeError, ValueError):
            continue
        if distance <= 0:
            continue

        difficulty = math.log2(2.0 * distance / width)
        if difficulty <= 0:
            continue
        samples.append({
            "i": index,
            "distance_px": round(distance, 1),
            "width_px": round(width, 1),
            "id_bits": round(difficulty, 3),
            "mt_ms": round(movement, 1),
            "misses": int(record.get("miss") or 0),
        })

    out["measured"] = len(samples)
    out["samples"] = samples
    if not samples:
        return out

    ids = [s["id_bits"] for s in samples]
    times = [s["mt_ms"] for s in samples]
    out["misses"] = sum(s["misses"] for s in samples)
    out["id_bits_mean"] = round(_mean(ids), 3)
    out["mt_ms_mean"] = round(_mean(times), 1)
    out["mt_ms_stdev"] = round(_stdev(times), 1)

    total_seconds = sum(times) / 1000.0
    out["throughput_bits_per_s"] = (round(sum(ids) / total_seconds, 2)
                                    if total_seconds > 0 else None)

    # A slope needs at least two distinct difficulties to exist at all.
    mean_id, mean_mt = _mean(ids), _mean(times)
    sxx = sum((value - mean_id) ** 2 for value in ids)
    if len(samples) < 2 or sxx == 0:
        return out

    slope = sum((a - mean_id) * (b - mean_mt) for a, b in zip(ids, times)) / sxx
    intercept = mean_mt - slope * mean_id
    ss_total = sum((b - mean_mt) ** 2 for b in times)
    ss_residual = sum((b - (intercept + slope * a)) ** 2 for a, b in zip(ids, times))
    out["slope_ms_per_bit"] = round(slope, 1)
    out["intercept_ms"] = round(intercept, 1)
    out["r_squared"] = round(1 - ss_residual / ss_total, 4) if ss_total > 0 else None
    return out


def _analyse_honeypots(records):
    """Count what touched a control that nothing able to see the page can reach."""
    out: dict = {"count": len(records or []), "types": {}, "ids": []}
    for record in records or []:
        kind = str(record.get("type") or "")
        out["types"][kind] = out["types"].get(kind, 0) + 1
        name = str(record.get("id") or record.get("kind") or "")
        if name and name not in out["ids"]:
            out["ids"].append(name)
    out["untrusted"] = sum(1 for r in records or [] if r.get("tr") is False)
    return out


def analyse(beh):
    """Return every derived metric for one session's telemetry.

    Return None for anything that is not the raw event stream the task page
    sends. `findings` reads that as a session with no interaction data rather
    than guessing at an unknown shape.
    """
    if not beh or (beh.get("version") != 2 and "pointer" not in beh):
        return None
    pointer = beh.get("pointer") or []
    keys = beh.get("keys") or []
    clicks = beh.get("clicks") or []
    inputs = beh.get("inputs") or []
    duration = beh.get("duration_ms") or 0

    click_times = sorted(float(c.get("t", 0)) for c in clicks)
    metrics = {
        "duration_ms": duration,
        "pointer": _analyse_pointer(pointer, click_times),
        "keys": _analyse_keys(keys, duration),
        "clicks": {
            "count": len(clicks),
            "untrusted": sum(1 for c in clicks if c.get("tr") is False),
        },
        "inputs": {
            "count": len(inputs),
            "keypress_count": beh.get("keypress_count", 0),
            "untrusted": sum(1 for i in inputs if i.get("tr") is False),
        },
        "wheel": {"count": len(beh.get("wheel") or [])},
        "fitts": _analyse_fitts(beh.get("fitts")),
        "honeypots": _analyse_honeypots(beh.get("honeypots")),
    }

    first_click = min((float(c.get("t", 0)) for c in clicks), default=None)
    if first_click is not None:
        metrics["clicks"]["moves_before_first"] = sum(
            1 for p in pointer if float(p.get("t", 0)) < first_click)

    # How much movement preceded each click. A hand travels toward a target and
    # keeps reporting the whole way, so the last quarter-second before a click
    # holds many events. A driver that jumps to the target reports one or none.
    if clicks and pointer:
        approaches = []
        for click in clicks:
            when = float(click.get("t", 0))
            approaches.append(sum(1 for p in pointer
                                  if when - APPROACH_MS <= float(p.get("t", 0)) < when))
        metrics["clicks"]["approach_events"] = approaches
        metrics["clicks"]["approach_median"] = statistics.median(approaches)
    return metrics


# ------------------------------------------------------------------ findings

def _finding(detection_id, weight, detail):
    return {"id": detection_id, "weight": weight, "detail": detail}


def findings(beh, metrics):
    """Judge the metrics. Return one entry per piece of evidence."""
    if not beh or not metrics:
        return [_finding("behavior.no_telemetry", 0.6,
                         "The session reported no interaction data.")]

    out = []
    pointer = metrics["pointer"]
    keys = metrics["keys"]
    clicks = metrics["clicks"]
    inputs = metrics["inputs"]

    untrusted = (pointer.get("untrusted", 0) + keys.get("untrusted", 0)
                 + clicks.get("untrusted", 0) + inputs.get("untrusted", 0))
    if untrusted:
        out.append(_finding("behavior.untrusted_events", 2.9,
                            "%d events carried isTrusted false. Page script dispatched them, "
                            "so they never came from a device." % untrusted))

    # ------------------------------------------------------------- pointer
    count = pointer.get("count", 0)
    density = pointer.get("samples_per_100px")
    traveled = pointer.get("traveled_px", 0)

    if count == 0 and clicks.get("count"):
        out.append(_finding("behavior.click_without_move", 2.4,
                            "The client clicked %d times without moving the pointer at all."
                            % clicks["count"]))
    elif count and clicks.get("moves_before_first", 1) == 0:
        out.append(_finding("behavior.click_before_first_move", 2.2,
                            "The first click landed before the pointer had moved once."))

    approach = clicks.get("approach_median")
    if approach is not None and clicks.get("count", 0) >= 2 and approach <= 1:
        out.append(_finding("behavior.click_without_approach", 2.4,
                            "A click was preceded by %g pointer events in the %d ms before it. "
                            "A hand is still moving as it arrives."
                            % (approach, int(APPROACH_MS))))

    # Sparse sampling is judged before path shape, because a path sampled this
    # coarsely has no shape to judge.
    if count >= 2 and traveled >= 200 and density is not None:
        if density < MIN_SAMPLES_PER_100PX:
            out.append(_finding("behavior.sparse_pointer_sampling", 2.6,
                                "The pointer covered %.0f px in %d events, %.2f per 100 px. A "
                                "device reporting at 60 Hz would have produced far more. The "
                                "pointer was placed, not moved."
                                % (traveled, count, density)))
        else:
            out.append(_finding("behavior.dense_pointer_sampling", -0.7,
                                "The pointer was sampled %.1f times per 100 px travelled, as a "
                                "device reports." % density))

    if pointer.get("teleports") and count >= 2:
        out.append(_finding("behavior.pointer_teleport", 2.2,
                            "The pointer jumped more than %d px %d times with no event in "
                            "between." % (int(TELEPORT_PX), pointer["teleports"])))

    # Everything below reads the shape and the rhythm of a path, so it needs
    # enough samples for those to exist.
    readable = (count >= 10 and density is not None
                and density >= MIN_SAMPLES_PER_100PX)
    if readable:
        share = pointer.get("step_constant_share", 0)
        distinct = pointer.get("distinct_step_lengths", 99)
        if share >= 0.8 or distinct <= 2:
            out.append(_finding("behavior.constant_step_length", 2.6,
                                "%.0f%% of pointer steps covered the same distance, across %d "
                                "distinct lengths. A tool interpolating between two points "
                                "produces this; a hand does not."
                                % (share * 100, distinct)))
        elif pointer.get("step_px_stdev", 0) > 0.5:
            out.append(_finding("behavior.varied_step_length", -0.8,
                                "Pointer step length varies continuously. Mean %.1f px, "
                                "spread %.1f px."
                                % (pointer.get("step_px_mean", 0), pointer["step_px_stdev"])))

        spread = pointer.get("interval_ms_stdev")
        if spread is not None and spread < 1.5:
            out.append(_finding("behavior.uniform_pointer_clock", 1.8,
                                "Pointer events arrive on a fixed clock. Spread %.2f ms over "
                                "%d distinct intervals."
                                % (spread, pointer.get("distinct_intervals", 0))))
        if pointer.get("distinct_intervals", 99) <= 2:
            out.append(_finding("behavior.quantized_pointer_clock", 1.5,
                                "The pointer used %d distinct inter-event intervals."
                                % pointer.get("distinct_intervals", 0)))

        # Judge each movement separately. A path that visits three targets in
        # three corners is bent by the task, not by a hand, so the whole-session
        # ratio says nothing.
        straight = pointer.get("segment_straightness_median")
        measured = pointer.get("measured_segments", 0)
        if straight is not None and measured:
            if straight > 0.97:
                out.append(_finding("behavior.linear_path", 2.0,
                                    "Each movement ran dead straight to its destination. "
                                    "Median ratio %.3f across %d movements."
                                    % (straight, measured)))
            elif straight < 0.90:
                out.append(_finding("behavior.curved_path", -0.9,
                                    "Movements bow away from the straight line as an arm "
                                    "does. Median ratio %.3f across %d movements."
                                    % (straight, measured)))

        sub = pointer.get("segment_corrections_median")
        if sub is not None and measured:
            if sub == 0 and pointer.get("traveled_px", 0) > 150:
                out.append(_finding("behavior.no_corrections", 1.6,
                                    "No movement held a corrective sub-movement. A hand aims, "
                                    "overshoots and corrects."))
            elif 1 <= sub <= 12:
                out.append(_finding("behavior.corrections_present", -1.0,
                                    "Movements hold a median of %g corrective sub-movements, "
                                    "in the range aiming produces." % sub))
            elif sub > 12:
                # Not a credit. A hand does not change speed this often; added
                # noise does.
                out.append(_finding("behavior.jittery_path", 1.5,
                                    "Movements hold a median of %g speed reversals each, far "
                                    "more than aiming produces. Noise was added to the path."
                                    % sub))

        if pointer.get("integer_coord_share", 0) == 1.0 and count >= 10:
            out.append(_finding("behavior.integer_coordinates", 1.0,
                                "Every pointer position landed on a whole pixel. A driver "
                                "computes integers; a device reports sub-pixel positions."))

        mismatch = pointer.get("movement_mismatch_share")
        if mismatch is not None and mismatch > 0.5:
            out.append(_finding("behavior.movement_delta_mismatch", 1.6,
                                "movementX disagreed with the change in position on %.0f%% of "
                                "events. A synthesised event often leaves it stale."
                                % (mismatch * 100)))

        if pointer.get("pauses", 0) == 0 and pointer.get("duration_ms", 0) > 1500:
            out.append(_finding("behavior.no_pauses", 0.7,
                                "The pointer moved for %.0f ms without pausing once."
                                % pointer.get("duration_ms", 0)))

    # ---------------------------------------------------------------- keys
    typed = keys.get("printable_count", 0)
    if inputs.get("count", 0) > 0 and keys.get("down_count", 0) == 0:
        out.append(_finding("behavior.input_without_keystroke", 2.8,
                            "Text reached %d field(s) with no key event at all. The value was "
                            "set directly or inserted through the debugger."
                            % inputs["count"]))

    if typed >= 3:
        expected_keypress = inputs.get("keypress_count", 0)
        if expected_keypress == 0:
            out.append(_finding("behavior.no_keypress_events", 2.0,
                                "%d printable keys were pressed and no keypress event fired. "
                                "A real key press emits one." % typed))

        zero = keys.get("zero_dwell_count", 0)
        dwell_mean = keys.get("dwell_ms_mean", 0)
        dwell_spread = keys.get("dwell_ms_stdev", 0)
        if zero and zero >= keys.get("dwell_count", 1) * 0.5:
            out.append(_finding("behavior.zero_dwell_keys", 2.7,
                                "%d of %d keys were pressed and released within %.0f ms. A "
                                "finger holds a key for tens of milliseconds."
                                % (zero, keys.get("dwell_count", 0), ZERO_DWELL_MS)))
        elif keys.get("dwell_count", 0) >= 4:
            if keys.get("constant_dwell_share", 0) >= 0.8:
                out.append(_finding("behavior.constant_dwell", 2.0,
                                    "%.0f%% of keys were held for exactly the same time, "
                                    "%.1f ms." % (keys["constant_dwell_share"] * 100,
                                                  dwell_mean)))
            elif dwell_mean < HUMAN_DWELL_MS[0]:
                # Varying hold times are worth nothing if every one of them is
                # too short to be a finger. A driver that presses and releases
                # in the same breath lands here however it staggers its keys.
                out.append(_finding("behavior.short_dwell", 2.4,
                                    "Keys were held for %.1f ms on average. A finger holds a "
                                    "key for roughly %d to %d ms."
                                    % (dwell_mean, HUMAN_DWELL_MS[0], HUMAN_DWELL_MS[1])))
            elif (keys.get("dwell_cv") is not None
                  and keys.get("dwell_count", 0) >= MIN_TIMING_SAMPLES
                  and keys["dwell_cv"] < MIN_HUMAN_DWELL_CV):
                out.append(_finding("behavior.metronomic_dwell", 1.8,
                                    "Hold times barely move around their own mean: %.0f ms "
                                    "give or take %.0f, a variation of %.0f%%. Fingers do not "
                                    "hold keys this evenly."
                                    % (dwell_mean, dwell_spread, keys["dwell_cv"] * 100)))
            elif dwell_mean > HUMAN_DWELL_MS[1] * 2:
                out.append(_finding("behavior.long_dwell", 1.2,
                                    "Keys were held for %.0f ms on average, far longer than "
                                    "typing produces." % dwell_mean))
            elif dwell_spread >= 8:
                out.append(_finding("behavior.varied_dwell", -1.0,
                                    "Key hold times vary as fingers do. Mean %.0f ms, spread "
                                    "%.0f ms." % (dwell_mean, dwell_spread)))

        flight_spread = keys.get("flight_ms_stdev", 0)
        if keys.get("down_count", 0) >= 5:
            if keys.get("constant_flight_share", 0) >= 0.8:
                out.append(_finding("behavior.constant_typing_rhythm", 2.2,
                                    "%.0f%% of gaps between keys were identical. A typist has "
                                    "no such metronome."
                                    % (keys["constant_flight_share"] * 100)))
            elif (keys.get("flight_cv") is not None
                  and keys["flight_cv"] < MIN_HUMAN_FLIGHT_CV):
                # Catches the driver that jitters its delay by a few milliseconds
                # around a fixed value: not identical, so the share check above
                # misses it, but far too even for a hand.
                out.append(_finding("behavior.metronomic_typing_rhythm", 2.0,
                                    "The gaps between keys hold to %.0f ms give or take %.0f, "
                                    "a variation of %.0f%%. Typing wanders far more than that "
                                    "between letters, words and punctuation."
                                    % (keys.get("flight_ms_mean", 0), flight_spread,
                                       keys["flight_cv"] * 100)))
            elif flight_spread < 5:
                out.append(_finding("behavior.uniform_keystrokes", 1.6,
                                    "The gaps between keys barely vary. Spread %.2f ms."
                                    % flight_spread))
            elif flight_spread >= 25:
                out.append(_finding("behavior.varied_typing_rhythm", -0.9,
                                    "The gaps between keys vary as typing does. Mean %.0f ms, "
                                    "spread %.0f ms."
                                    % (keys.get("flight_ms_mean", 0), flight_spread)))

        speed = keys.get("chars_per_minute")
        if speed is not None and speed > 900:
            out.append(_finding("behavior.impossible_typing_speed", 2.4,
                                "The client typed at %.0f characters per minute. The record "
                                "for a human is near 750." % speed))

        fastest = keys.get("fastest_flight_ms")
        if fastest is not None and fastest < 15 and keys.get("down_count", 0) >= 5:
            out.append(_finding("behavior.superhuman_key_gap", 1.8,
                                "Two keys were pressed %.1f ms apart. A hand needs longer to "
                                "move between keys." % fastest))

        if keys.get("backspaces", 0):
            out.append(_finding("behavior.corrections_typed", -0.6,
                                "The client corrected itself %d times while typing."
                                % keys["backspaces"]))

    out += _honeypot_findings(metrics.get("honeypots") or {})
    out += _fitts_findings(metrics.get("fitts") or {})
    return out


def _honeypot_findings(honeypots):
    """Judge contact with a control that nothing able to see the page can reach.

    These carry the heaviest weights in the layer, and they earn them: the
    controls are invisible, outside the tab order and hidden from assistive
    technology, so neither a person nor a screen reader can arrive at one. The
    only way to touch one is to read the DOM and act on what is written there.
    """
    if not honeypots.get("count"):
        return []

    types = honeypots.get("types") or {}
    named = ", ".join(honeypots.get("ids") or []) or "an unnamed control"
    out = []
    if types.get("input"):
        out.append(_finding("behavior.honeypot_filled", 3.4,
                            "Text was entered into a hidden field (%s). It is invisible, "
                            "outside the tab order and hidden from assistive technology, so "
                            "only something reading the DOM could have found it." % named))
    if types.get("click"):
        out.append(_finding("behavior.honeypot_click", 3.2,
                            "A hidden control was clicked (%s). Nothing that can see the "
                            "page can reach it." % named))
    if types.get("focus") and not types.get("input") and not types.get("click"):
        out.append(_finding("behavior.honeypot_focus", 2.0,
                            "A hidden control took focus (%s) without being typed into or "
                            "clicked. It carries tabindex -1, so tabbing does not reach it."
                            % named))
    return out


def _fitts_findings(fitts):
    """Judge the acquisition task against Fitts's law.

    A hand trades speed for accuracy along a line: reaching a small distant
    target takes measurably longer than a large near one, and movement time
    against log2(2D/W) is straight with a slope of roughly 100 to 200 ms per
    bit. A tool that jumps the pointer to a coordinate spends the same time
    whatever it is aiming at, so the line is flat, and it acquires difficulty
    faster than a hand physically can.
    """
    measured = fitts.get("measured", 0)
    if measured < MIN_FITTS_SAMPLES:
        return []

    out = []
    throughput = fitts.get("throughput_bits_per_s")
    if throughput is not None and throughput > MAX_HUMAN_THROUGHPUT:
        out.append(_finding("behavior.superhuman_throughput", 2.8,
                            "The client acquired %.1f bits of difficulty per second across "
                            "%d targets. A mouse in a hand manages roughly 4 to 10, and the "
                            "limit is motor control rather than intent."
                            % (throughput, measured)))

    slope = fitts.get("slope_ms_per_bit")
    fit = fitts.get("r_squared")
    if slope is None:
        return out

    if slope < MIN_FITTS_SLOPE_MS:
        out.append(_finding("behavior.fitts_no_scaling", 2.4,
                            "Movement time barely grew with difficulty: %.0f ms per bit "
                            "across targets from %.1f to %.1f bits. A hand needs roughly "
                            "100 to 200 ms more for every extra bit; a tool that jumps to a "
                            "coordinate needs none, because the size of the target never "
                            "cost it anything."
                            % (slope, min(s["id_bits"] for s in fitts["samples"]),
                               max(s["id_bits"] for s in fitts["samples"]))))
    elif fit is not None and fit >= MIN_FITTS_FIT:
        out.append(_finding("behavior.fitts_obeys", -1.2,
                            "Acquisition time tracks the index of difficulty as a hand does: "
                            "%.0f ms per bit with a fit of %.2f over %d targets."
                            % (slope, fit, measured)))
    return out
