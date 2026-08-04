"""Reference data for the detector.

Two kinds of data live here.

Structural facts are stable across browser releases. An example is the
GREASE extension that Chromium sends and most HTTP libraries do not.

Calibrated data changes with every browser release. The known-client table
starts almost empty on purpose. Run `python3 calibrate.py` with a real
browser to fill it. Do not cite a table you did not measure.
"""

import json
import os

from src.loaders.config import config

# Header order that each browser family sends on a top-level HTTP/1.1 request.
# The order is a strong signal. An HTTP library rarely reproduces it.
CANONICAL_HEADER_ORDER = {
    "chrome": [
        "host", "connection", "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform",
        "upgrade-insecure-requests", "user-agent", "accept", "sec-fetch-site",
        "sec-fetch-mode", "sec-fetch-user", "sec-fetch-dest", "accept-encoding",
        "accept-language",
    ],
    "firefox": [
        "host", "user-agent", "accept", "accept-language", "accept-encoding",
        "connection", "upgrade-insecure-requests", "sec-fetch-dest",
        "sec-fetch-mode", "sec-fetch-site", "sec-fetch-user",
    ],
    "safari": [
        "host", "accept", "connection", "accept-encoding", "user-agent",
        "accept-language",
    ],
}

# A Chromium browser sends every one of these on a top-level navigation.
CHROMIUM_REQUIRED_HEADERS = [
    "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform",
    "sec-fetch-site", "sec-fetch-mode", "sec-fetch-dest", "accept-language",
]

# Software renderers. A headless browser with no GPU reports one of these, and
# the machine is then drawing on the CPU rather than on a graphics card.
SOFTWARE_RENDERER_MARKERS = [
    "swiftshader", "llvmpipe", "software rasterizer", "mesa offscreen",
    "google inc. (google)", "virgl", "microsoft basic render",
    "lavapipe", "softpipe", "swrast", "d3d11 warp", "apple software renderer",
]

# Strings that name real silicon. A machine drawing on a GPU reports one of
# these in the vendor or the renderer, and no software rasterizer does.
HARDWARE_GPU_MARKERS = [
    "nvidia", "geforce", "quadro", "rtx ", "gtx ",
    "radeon", "amd ", "firepro",
    "intel", "iris", "hd graphics", "uhd graphics", "arc ",
    "apple m1", "apple m2", "apple m3", "apple m4", "apple gpu", "apple a",
    "adreno", "mali", "powervr", "videocore",
]


def gpu_class(vendor, renderer):
    """Return whether WebGL is drawing on a GPU, on the CPU, or unknown.

    Read both strings. Chrome reports the adapter through ANGLE, so the vendor
    carries "Google Inc. (NVIDIA)" while the renderer carries the board name,
    and a software build names SwiftShader in one or the other.

    Software is checked first. A rasterizer string never names a real card, but
    the machine it runs on may put its own name nearby, so testing hardware
    first would read a CPU renderer as a GPU.
    """
    text = ("%s %s" % (vendor or "", renderer or "")).lower()
    if not text.strip():
        return "unknown"
    if any(marker in text for marker in SOFTWARE_RENDERER_MARKERS):
        return "software"
    if any(marker in text for marker in HARDWARE_GPU_MARKERS):
        return "hardware"
    return "unknown"


# Fonts that ship with one desktop platform and not the others. The collector
# probes for these by name, so a resolved font is evidence about the machine
# rather than about what the User-Agent claims. Keep every name here inside
# FONT_PROBES in the collector, or it can never be resolved.
PLATFORM_FONTS = {
    "windows": ["segoe ui", "calibri", "cambria", "candara",
                "franklin gothic medium", "palatino linotype"],
    "macos": ["menlo", "optima", "helvetica neue"],
}

# Substrings that appear in the User-Agent of an unmodified automation client.
DECLARED_AUTOMATION_MARKERS = [
    "headlesschrome", "phantomjs", "python-requests", "curl/", "wget/",
    "go-http-client", "okhttp", "java/", "node-fetch", "axios/", "scrapy",
    "libwww-perl", "httpclient", "aiohttp", "postmanruntime",
]

# Properties that only an automation control channel adds to the page.
# Each entry is read by the collector script in the browser.
AUTOMATION_WINDOW_KEYS = [
    "cdc_adoQpoasnfa76pfcZLmcfl_Array",
    "cdc_adoQpoasnfa76pfcZLmcfl_Promise",
    "cdc_adoQpoasnfa76pfcZLmcfl_Symbol",
    "$cdc_asdjflasutopfhvcZLmcfl_",
    "__webdriver_evaluate",
    "__selenium_evaluate",
    "__driver_evaluate",
    "__webdriver_script_function",
    "__fxdriver_evaluate",
    "__driver_unwrapped",
    "_phantom",
    "callPhantom",
    "domAutomation",
    "domAutomationController",
    "__nightmare",
    "_Selenium_IDE_Recorder",
    "__playwright__binding__",
    "__pw_manual",
    "__puppeteer_evaluation_script__",
]


def load_calibration():
    """Return the calibrated fingerprint table. Return empty sets if none exists."""
    default = {"human_ja4": {}, "automation_ja4": {}, "human_ja3": {}, "automation_ja3": {}}
    if not os.path.exists(config.calibration_file):
        return default
    with open(config.calibration_file) as handle:
        stored = json.load(handle)
    default.update(stored)
    return default


def save_calibration(table):
    """Write the calibrated fingerprint table to disk."""
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(config.calibration_file, "w") as handle:
        json.dump(table, handle, indent=2, sort_keys=True)


def ua_family(user_agent):
    """Return the browser family that the User-Agent claims."""
    ua = (user_agent or "").lower()
    if "edg/" in ua or "edge" in ua:
        return "chrome"
    if "chrome/" in ua or "chromium" in ua:
        return "chrome"
    if "firefox/" in ua:
        return "firefox"
    if "safari/" in ua and "chrome" not in ua:
        return "safari"
    return "unknown"


def ua_platform(user_agent):
    """Return the operating system that the User-Agent claims."""
    ua = (user_agent or "").lower()
    if "windows" in ua:
        return "windows"
    if "android" in ua:
        return "android"
    if "iphone" in ua or "ipad" in ua:
        return "ios"
    if "mac os x" in ua:
        return "macos"
    if "linux" in ua:
        return "linux"
    return "unknown"


def ua_is_mobile(user_agent):
    """Return True if the User-Agent claims a mobile device."""
    ua = (user_agent or "").lower()
    return "mobile" in ua or "android" in ua or "iphone" in ua
