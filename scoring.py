"""Score a session from the signals that the harness collects.

The engine copies the shape of a commercial system. Each layer emits
detection IDs. The engine adds the weights and maps the total to a score
from 1 to 99. A low score means the client is probably automated.

Every signal carries a layer name. The layer name lets you report which
layer caught a client, which is the measurement a thesis needs.
"""

import math
import statistics

import reference

# The order is the order a production stack meets the client. `first_catching
# _layer` reads this list from the top, so the earliest layer that flags a
# client is the one reported. Consistency sits last because it needs the rest.
LAYERS = ["network", "tls", "http", "browser", "worlds", "runtime",
          "environment", "behavior", "consistency"]


class Signal:
    """One piece of evidence about a session."""

    def __init__(self, layer, detection_id, weight, detail=""):
        self.layer = layer
        self.detection_id = detection_id
        self.weight = weight
        self.detail = detail

    def as_dict(self):
        return {
            "layer": self.layer,
            "id": self.detection_id,
            "weight": round(self.weight, 3),
            "detail": self.detail,
        }


# ---------------------------------------------------------------- network

def score_network(session):
    """Check the address that the connection came from."""
    out = []
    ip = session.get("ip", "")
    if ip.startswith("127.") or ip == "::1":
        out.append(Signal("network", "network.loopback", 0.0,
                          "Loopback address. The demo run gives no reputation signal."))
    return out


# -------------------------------------------------------------------- tls

def score_tls(session, calibration):
    """Check the TLS handshake against structural rules and the calibration table."""
    out = []
    tls = session.get("tls")
    if not tls:
        out.append(Signal("tls", "tls.absent", 1.0, "The harness read no ClientHello."))
        return out

    if not tls.get("grease"):
        out.append(Signal("tls", "tls.no_grease", 1.6,
                          "The client sent no GREASE values. Chromium and Firefox send them."))
    else:
        out.append(Signal("tls", "tls.grease_present", -0.8,
                          "The client sent GREASE values, as a real browser does."))

    if not tls.get("alpn"):
        out.append(Signal("tls", "tls.no_alpn", 1.2,
                          "The client offered no ALPN protocol. A browser offers h2."))
    elif "h2" not in tls["alpn"]:
        out.append(Signal("tls", "tls.no_h2_alpn", 0.9,
                          "The client did not offer h2. A current browser offers h2."))

    if tls.get("cipher_count", 0) < 12:
        out.append(Signal("tls", "tls.few_ciphers", 0.8,
                          "The cipher list is short. A browser offers a longer list."))
    if tls.get("ext_count", 0) < 9:
        out.append(Signal("tls", "tls.few_extensions", 0.9,
                          "The extension list is short. A browser sends more extensions."))
    if tls.get("max_version", 0) < 0x0304:
        out.append(Signal("tls", "tls.no_tls13", 1.0,
                          "The client did not offer TLS 1.3."))

    ja4 = tls.get("ja4", "")
    if ja4 in calibration.get("automation_ja4", {}):
        label = calibration["automation_ja4"][ja4]
        out.append(Signal("tls", "tls.known_automation_ja4", 2.5,
                          "The JA4 hash matches the calibrated automation client %s." % label))
    elif ja4 in calibration.get("human_ja4", {}):
        label = calibration["human_ja4"][ja4]
        out.append(Signal("tls", "tls.known_browser_ja4", -1.4,
                          "The JA4 hash matches the calibrated browser %s." % label))
    elif calibration.get("human_ja4"):
        out.append(Signal("tls", "tls.unknown_ja4", 0.6,
                          "The JA4 hash is in no calibrated table."))
    return out


# ------------------------------------------------------------------- http

def _order_distance(seen, canonical):
    """Return how far the seen header order sits from the canonical order.

    The value counts pairs that appear in the wrong relative order.
    A value of 0.0 means a perfect match.
    """
    index = {name: pos for pos, name in enumerate(canonical)}
    kept = [index[name] for name in seen if name in index]
    if len(kept) < 2:
        return 1.0
    wrong = 0
    total = 0
    for i in range(len(kept)):
        for j in range(i + 1, len(kept)):
            total += 1
            if kept[i] > kept[j]:
                wrong += 1
    return wrong / total if total else 1.0


def score_http(session):
    """Check the request headers, their order, and the declared client."""
    out = []
    if session.get("header_source") == "unavailable":
        return [Signal("http", "http.headers_not_captured", 0.0,
                       "The extension captured no top-level navigation for this tab, so the "
                       "http layer read nothing. Reload the page under test.")]
    headers = session.get("headers", {})
    order = session.get("header_order", [])
    user_agent = headers.get("user-agent", "")

    if not user_agent:
        out.append(Signal("http", "http.no_user_agent", 1.5, "The request sent no User-Agent."))
        return out

    low_ua = user_agent.lower()
    for marker in reference.DECLARED_AUTOMATION_MARKERS:
        if marker in low_ua:
            out.append(Signal("http", "http.declared_automation", 3.0,
                              "The User-Agent names the automation client %s." % marker))
            break

    family = reference.ua_family(user_agent)
    if family == "chrome":
        missing = [h for h in reference.CHROMIUM_REQUIRED_HEADERS if h not in headers]
        if missing:
            out.append(Signal("http", "http.missing_chromium_headers", 0.5 * len(missing),
                              "A Chromium User-Agent arrived without %s." % ", ".join(missing)))

    canonical = reference.CANONICAL_HEADER_ORDER.get(family)
    if canonical and order:
        distance = _order_distance(order, canonical)
        if distance > 0.25:
            out.append(Signal("http", "http.header_order_mismatch", 1.4,
                              "The header order does not match %s. Distance %.2f." % (family, distance)))
        elif distance == 0.0:
            out.append(Signal("http", "http.header_order_match", -0.7,
                              "The header order matches %s." % family))

    if "accept-language" not in headers:
        out.append(Signal("http", "http.no_accept_language", 0.9,
                          "The request sent no Accept-Language header."))
    if headers.get("accept", "") in ("*/*", ""):
        out.append(Signal("http", "http.generic_accept", 0.8,
                          "The Accept header is generic. A browser navigation sends a long list."))
    return out


# ---------------------------------------------------------------- browser

def score_browser(session):
    """Check what the collector script reported from inside the page."""
    out = []
    fp = session.get("js")
    if fp is None:
        out.append(Signal("browser", "browser.no_javascript", 1.8,
                          "The client ran no JavaScript. It never returned a fingerprint."))
        return out

    if fp.get("webdriver"):
        out.append(Signal("browser", "browser.webdriver_flag", 2.6,
                          "The navigator.webdriver flag is true."))

    found = fp.get("automation_keys") or []
    if found:
        out.append(Signal("browser", "browser.automation_globals", 2.8,
                          "The page holds automation properties: %s." % ", ".join(found[:4])))

    renderer = (fp.get("webgl_renderer") or "").lower()
    if not renderer:
        out.append(Signal("browser", "browser.no_webgl", 1.3, "WebGL returned no renderer name."))
    else:
        for marker in reference.SOFTWARE_RENDERER_MARKERS:
            if marker in renderer:
                out.append(Signal("browser", "browser.software_renderer", 1.9,
                                  "The WebGL renderer is a software rasterizer: %s." % renderer[:60]))
                break

    if fp.get("patched_natives"):
        out.append(Signal("browser", "browser.patched_natives", 2.4,
                          "A native function is not native code: %s. A stealth patch does this."
                          % ", ".join(fp["patched_natives"][:4])))

    if fp.get("permission_mismatch"):
        out.append(Signal("browser", "browser.permission_mismatch", 1.7,
                          "The Permissions API and Notification.permission disagree."))

    if fp.get("outer_width") == 0 or fp.get("outer_height") == 0:
        out.append(Signal("browser", "browser.zero_outer_window", 1.6,
                          "The outer window size is zero. A headless window reports this."))

    family = reference.ua_family(session.get("headers", {}).get("user-agent", ""))
    if family == "chrome" and not fp.get("has_chrome_object"):
        out.append(Signal("browser", "browser.missing_chrome_object", 1.5,
                          "The User-Agent claims Chrome but window.chrome is absent."))

    # A failed font probe reports nothing rather than zero, so read the count
    # only when the client actually sent a number.
    fonts = fp.get("font_count")
    if isinstance(fonts, int) and fonts < 8:
        out.append(Signal("browser", "browser.few_fonts", 1.1,
                          "The client resolved %d fonts. A desktop install resolves many more."
                          % fonts))

    if fp.get("hardware_concurrency", 0) in (0, 1):
        out.append(Signal("browser", "browser.low_concurrency", 0.7,
                          "The client reports one CPU thread or none."))

    if fp.get("canvas_hash") in (None, "", "0"):
        out.append(Signal("browser", "browser.no_canvas", 1.2, "Canvas rendering returned nothing."))
    else:
        out.append(Signal("browser", "browser.canvas_present", -0.4, "Canvas returned a stable hash."))
    return out


# --------------------------------------------------------------- behavior

def _path_straightness(points):
    """Return the ratio of traveled distance to direct distance.

    A value near 1.0 means a straight line. A human hand does not draw one.
    """
    if len(points) < 3:
        return None
    traveled = 0.0
    for a, b in zip(points, points[1:]):
        traveled += math.dist((a["x"], a["y"]), (b["x"], b["y"]))
    direct = math.dist((points[0]["x"], points[0]["y"]),
                       (points[-1]["x"], points[-1]["y"]))
    if traveled == 0:
        return None
    return direct / traveled


def score_behavior(session):
    """Check the movement and timing that the collector recorded."""
    out = []
    beh = session.get("behavior")
    if beh is None:
        return [Signal("behavior", "behavior.no_telemetry", 0.6,
                       "The session reported no interaction data.")]

    moves = beh.get("mouse", [])
    clicks = beh.get("clicks", 0)
    keys = beh.get("key_intervals", [])

    # An isolated-world listener reads isTrusted before page code can swap the
    # event object. A false flag means a script dispatched the event.
    untrusted = beh.get("untrusted_events", 0)
    if untrusted:
        out.append(Signal("behavior", "behavior.untrusted_events", 2.9,
                          "%d events carried isTrusted false. A script dispatched them."
                          % untrusted))

    scrolls = beh.get("scroll_deltas") or []
    if len(scrolls) >= 4 and len(set(scrolls)) == 1:
        out.append(Signal("behavior", "behavior.uniform_scroll", 1.4,
                          "Every wheel event carried the same delta of %s. A wheel emits a "
                          "varying delta." % scrolls[0]))

    if clicks and len(moves) < 3:
        out.append(Signal("behavior", "behavior.click_without_move", 2.2,
                          "The client clicked without moving the pointer first."))

    if len(moves) >= 3:
        straight = _path_straightness(moves)
        if straight is not None and straight > 0.97:
            out.append(Signal("behavior", "behavior.linear_path", 2.0,
                              "The pointer path is a straight line. Ratio %.3f." % straight))
        elif straight is not None and straight < 0.85:
            out.append(Signal("behavior", "behavior.human_path_curvature", -0.9,
                              "The pointer path curves as a hand does. Ratio %.3f." % straight))

        deltas = [b["t"] - a["t"] for a, b in zip(moves, moves[1:]) if b["t"] > a["t"]]
        if len(deltas) >= 5:
            spread = statistics.pstdev(deltas)
            if spread < 1.5:
                out.append(Signal("behavior", "behavior.uniform_timing", 1.8,
                                  "The pointer events arrive on a fixed clock. Spread %.2f ms." % spread))
            unique = len(set(round(d) for d in deltas))
            if unique <= 2:
                out.append(Signal("behavior", "behavior.quantized_timing", 1.5,
                                  "The pointer events use %d distinct intervals." % unique))

    if len(keys) >= 4:
        spread = statistics.pstdev(keys)
        if spread < 5:
            out.append(Signal("behavior", "behavior.uniform_keystrokes", 1.6,
                              "The keystroke intervals are near constant. Spread %.2f ms." % spread))

    first = beh.get("first_interaction_ms")
    if first is not None and first < 60:
        out.append(Signal("behavior", "behavior.instant_interaction", 1.4,
                          "The first interaction came %d ms after load." % first))
    return out



# ----------------------------------------------------------------- worlds

def score_worlds(session):
    """Compare the main world with the isolated world.

    Only a browser extension can make this comparison. A stealth patch that
    arrives through the automation control channel lands in the main world.
    A content script in the isolated world reads the unpatched value.
    """
    out = []
    ext = session.get("extension")
    if not ext:
        return out
    divergences = ext.get("divergences") or []
    if not divergences:
        out.append(Signal("worlds", "worlds.no_divergence", -1.2,
                          "The main world and the isolated world agree on every field."))
        return out
    for item in divergences:
        field = item.get("field", "unknown")
        strong = field == "webdriver" or field.startswith("native:")
        out.append(Signal("worlds", "worlds.divergence." + field, 3.2 if strong else 2.0,
                          "The page sees %s as %s. The browser reports %s."
                          % (field, item.get("main"), item.get("isolated"))))
    return out


# ---------------------------------------------------------------- runtime

def score_runtime(session):
    """Check the JavaScript engine for the marks that a driver leaves.

    These signals do not read what the browser claims. They read how the
    engine behaves, so a client that rewrites every property still fails
    here unless it also rebuilds the engine.
    """
    out = []
    rt = session.get("runtime")
    if not rt:
        return out

    if rt.get("cdp_runtime_enabled"):
        out.append(Signal("runtime", "runtime.cdp_attached", 2.9,
                          "Logging an Error read its stack getter. A Chrome DevTools "
                          "Protocol client is attached. An open DevTools window reads it "
                          "the same way, so record whether one was open."))

    # Chrome defines webdriver on Navigator.prototype. A stealth patch usually
    # redefines it on the navigator instance, which moves the property.
    if rt.get("webdriver_own_property"):
        out.append(Signal("runtime", "runtime.webdriver_relocated", 2.8,
                          "navigator.webdriver is an own property of the instance. Chrome "
                          "defines it on Navigator.prototype. A patch moved it."))
    elif rt.get("webdriver_on_prototype") is False:
        out.append(Signal("runtime", "runtime.webdriver_deleted", 1.8,
                          "Navigator.prototype carries no webdriver property at all. "
                          "A patch deleted it."))

    markers = rt.get("stack_markers") or []
    if markers:
        out.append(Signal("runtime", "runtime.injected_stack", 3.0,
                          "A stack trace names an injected script: %s."
                          % ", ".join(markers[:3])))

    if rt.get("prepare_stack_trace_set"):
        out.append(Signal("runtime", "runtime.prepare_stack_trace_set", 2.6,
                          "Error.prepareStackTrace is defined. Chrome leaves it undefined. "
                          "A stealth plugin sets it to scrub its own frames from traces."))

    if rt.get("tostring_chain_native") is False:
        out.append(Signal("runtime", "runtime.tostring_chain_patched", 2.6,
                          "Function.prototype.toString has itself been replaced. A stealth "
                          "patch hides other patches and forgets to hide this one."))

    # A hidden tab throttles its frame clock to nothing, so a real browser in a
    # background tab looks exactly like a window with no compositor. Read the
    # frame signals only when the page was visible while they were measured.
    frames = rt.get("frame_count")
    visible = rt.get("visibility") in (None, "visible", "unknown")
    if not visible:
        out.append(Signal("runtime", "runtime.frame_clock_not_measured", 0.0,
                          "The page was hidden during the probe. The frame clock says "
                          "nothing about this client."))
    elif frames == 0:
        out.append(Signal("runtime", "runtime.no_animation_frame", 1.7,
                          "requestAnimationFrame never fired. A window with no compositor "
                          "reports this."))
    elif frames:
        spread = rt.get("frame_stdev_ms")
        if spread is not None and spread < 0.2:
            out.append(Signal("runtime", "runtime.synthetic_frame_clock", 0.8,
                              "The frame interval never varies. Spread %.3f ms. A display "
                              "refresh jitters; a generated clock does not." % spread))
        else:
            out.append(Signal("runtime", "runtime.frame_clock_present", -0.5,
                              "The frame clock runs and jitters as a display does."))
    return out


# ------------------------------------------------------------ environment

def score_environment(session):
    """Check the capabilities that a desktop install has and a container lacks.

    A stealth patch rewrites what the browser says. It does not install a
    sound card, a camera, a voice pack, or a licensed codec.
    """
    out = []
    env = session.get("environment")
    if not env:
        return out

    family = reference.ua_family(session.get("headers", {}).get("user-agent", ""))

    devices = env.get("media_device_count")
    if devices == 0:
        out.append(Signal("environment", "environment.no_media_devices", 1.6,
                          "The browser enumerated no camera and no microphone. A desktop "
                          "install reports at least one."))
    elif devices:
        out.append(Signal("environment", "environment.media_devices_present", -0.5,
                          "The browser enumerated %d media devices." % devices))

    voices = env.get("voice_count")
    if voices == 0:
        out.append(Signal("environment", "environment.no_speech_voices", 1.3,
                          "The speech synthesizer holds no voices. A desktop install "
                          "carries the system voice pack."))
    elif voices:
        out.append(Signal("environment", "environment.speech_voices_present", -0.4,
                          "The speech synthesizer holds %d voices." % voices))

    # Chrome ships licensed H.264 and AAC. The plain Chromium build that
    # Puppeteer and Playwright download does not.
    codecs = env.get("codecs") or {}
    if codecs and not codecs.get("h264"):
        out.append(Signal("environment", "environment.no_proprietary_codecs", 2.2,
                          "The build cannot play H.264. Chrome ships the licensed codecs. "
                          "The plain Chromium build that automation downloads does not."))
    elif codecs.get("h264"):
        out.append(Signal("environment", "environment.proprietary_codecs_present", -0.6,
                          "The build plays H.264, as a released Chrome does."))

    if family == "chrome" and env.get("pdf_viewer_enabled") is False:
        out.append(Signal("environment", "environment.no_pdf_viewer", 1.2,
                          "navigator.pdfViewerEnabled is false. Desktop Chrome ships the "
                          "PDF viewer and reports true."))

    if family == "chrome" and env.get("battery_api") is False:
        out.append(Signal("environment", "environment.no_battery_api", 0.9,
                          "navigator.getBattery is absent. Desktop Chrome exposes it."))

    ice = env.get("ice_candidate_count")
    if ice == 0 and env.get("webrtc_supported"):
        out.append(Signal("environment", "environment.no_ice_candidates", 1.4,
                          "WebRTC gathering finished with no candidate. The host has no "
                          "reachable network interface."))
    elif ice:
        out.append(Signal("environment", "environment.ice_candidates_present", -0.4,
                          "WebRTC gathered %d candidates." % ice))

    quota = env.get("storage_quota")
    if quota is not None and quota == 0:
        out.append(Signal("environment", "environment.no_storage_quota", 0.7,
                          "The origin was granted no storage quota."))

    permissions = env.get("permissions") or {}
    states = set(permissions.values())
    if len(permissions) >= 3 and states == {"denied"}:
        out.append(Signal("environment", "environment.all_permissions_denied", 1.0,
                          "Every queried permission returned denied. A headless profile "
                          "answers this way."))
    return out


# ------------------------------------------------------------- consistency

def score_consistency(session):
    """Compare what each layer claims. A disagreement is the strongest evidence.

    A stealth client can pass one layer. It fails when two layers tell
    different stories about the same machine.
    """
    out = []
    headers = session.get("headers", {})
    fp = session.get("js") or {}
    tls = session.get("tls") or {}
    user_agent = headers.get("user-agent", "")
    if not user_agent:
        return out

    claimed_family = reference.ua_family(user_agent)
    claimed_platform = reference.ua_platform(user_agent)

    js_platform = (fp.get("platform") or "").lower()
    if js_platform:
        mapped = "unknown"
        if "win" in js_platform:
            mapped = "windows"
        elif "mac" in js_platform:
            mapped = "macos"
        elif "linux" in js_platform or "x11" in js_platform:
            mapped = "linux"
        elif "android" in js_platform:
            mapped = "android"
        if mapped != "unknown" and claimed_platform != "unknown" and mapped != claimed_platform:
            out.append(Signal("consistency", "consistency.platform_mismatch", 2.7,
                              "The User-Agent claims %s. navigator.platform reports %s."
                              % (claimed_platform, mapped)))

    # Chrome sends "macOS", "Windows", "Linux", "Android". Fold the case and the
    # spaces and the two names meet.
    ch_platform = (headers.get("sec-ch-ua-platform") or "").strip('"').lower().replace(" ", "")
    if ch_platform and claimed_platform != "unknown" and ch_platform != claimed_platform:
        out.append(Signal("consistency", "consistency.client_hint_mismatch", 2.2,
                          "Sec-CH-UA-Platform says %s. The User-Agent says %s."
                          % (ch_platform, claimed_platform)))

    if claimed_family == "chrome" and tls.get("grease") is False:
        out.append(Signal("consistency", "consistency.chrome_ua_without_grease", 3.0,
                          "The User-Agent claims Chrome. The TLS handshake sends no GREASE."))

    renderer = (fp.get("webgl_renderer") or "").lower()
    if renderer and claimed_platform in ("windows", "macos"):
        if any(m in renderer for m in reference.SOFTWARE_RENDERER_MARKERS):
            out.append(Signal("consistency", "consistency.desktop_without_gpu", 2.0,
                              "The client claims a desktop system but renders in software."))

    if reference.ua_is_mobile(user_agent) and fp.get("screen_width", 0) > 1200:
        out.append(Signal("consistency", "consistency.mobile_ua_desktop_screen", 2.3,
                          "The User-Agent claims a mobile device. The screen is %d pixels wide."
                          % fp.get("screen_width", 0)))

    if fp.get("max_touch_points") == 0 and reference.ua_is_mobile(user_agent):
        out.append(Signal("consistency", "consistency.mobile_without_touch", 1.9,
                          "The User-Agent claims a mobile device that reports no touch points."))

    lang_header = (headers.get("accept-language") or "").split(",")[0].strip().lower()
    js_lang = (fp.get("language") or "").lower()
    if lang_header and js_lang and lang_header.split("-")[0] != js_lang.split("-")[0]:
        out.append(Signal("consistency", "consistency.language_mismatch", 1.3,
                          "Accept-Language says %s. navigator.language says %s."
                          % (lang_header, js_lang)))
    return out


# ------------------------------------------------------------------ score

def evaluate(session, calibration=None):
    """Run every layer and return the score, the layer table, and the signals."""
    if calibration is None:
        calibration = reference.load_calibration()

    signals = []
    signals += score_network(session)
    signals += score_tls(session, calibration)
    signals += score_http(session)
    signals += score_browser(session)
    signals += score_worlds(session)
    signals += score_runtime(session)
    signals += score_environment(session)
    signals += score_behavior(session)
    signals += score_consistency(session)

    total = sum(s.weight for s in signals)
    probability = 1.0 / (1.0 + math.exp(-(total - 1.0)))
    score = int(round(99 * (1.0 - probability)))
    score = max(1, min(99, score))

    by_layer = {}
    for name in LAYERS:
        layer_signals = [s for s in signals if s.layer == name]
        by_layer[name] = {
            "weight": round(sum(s.weight for s in layer_signals), 3),
            "count": len(layer_signals),
            "ids": [s.detection_id for s in layer_signals if s.weight > 0],
        }

    positive = [s for s in signals if s.weight > 0]
    strongest = max(positive, key=lambda s: s.weight).layer if positive else None

    # The earliest layer matters more than the strongest one. A client that the
    # TLS layer catches never reaches the JavaScript layer in production.
    earliest = None
    for name in LAYERS:
        if by_layer[name]["ids"]:
            earliest = name
            break

    if score <= 10:
        verdict = "automated"
    elif score <= 30:
        verdict = "likely automated"
    elif score <= 60:
        verdict = "unclear"
    else:
        verdict = "likely human"

    return {
        "score": score,
        "verdict": verdict,
        "total_weight": round(total, 3),
        "first_catching_layer": earliest,
        "strongest_layer": strongest,
        "layers": by_layer,
        "signals": [s.as_dict() for s in signals],
    }
