"""Turn a scored run into a replay profile.

A run says what a client looked like. A profile says what to make another
client look like, so it is the same facts pointed the other way: the same
adapter strings, the same screen, the same device list, in the shape a
spoofing or launcher program takes as input.

Two rules hold throughout.

Nothing is invented where the run measured something. Every field that can
come from the record does, verbatim, even when the value looks wrong: a
profile that quietly tidies up what it saw no longer reproduces it.

Where the run measured nothing, the gap is filled with a plain platform
default and named in `gaps`. Two fields can never be measured from a browser
at all — `speech.voice_type` and `speech.trim` are settings for whatever plays
the audio, not properties of the client — so they are always defaults.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

# Device labels a machine of each kind normally reports. Used only when the
# run holds no label of its own, which is the usual case: enumerateDevices
# blanks every label until the page is granted microphone or camera access.
DEFAULT_DEVICE_LABELS = {
    "mac": {
        "audioinput": "MacBook Microphone",
        "audiooutput": "MacBook Speakers",
        "videoinput": "FaceTime HD Camera",
    },
    "windows": {
        "audioinput": "Microphone Array (Realtek(R) Audio)",
        "audiooutput": "Speakers (Realtek(R) Audio)",
        "videoinput": "Integrated Camera",
    },
    "linux": {
        "audioinput": "Built-in Audio Analog Stereo",
        "audiooutput": "Built-in Audio Analog Stereo",
        "videoinput": "Integrated Camera",
    },
    "android": {
        "audioinput": "Default",
        "audiooutput": "Default",
        "videoinput": "camera2 0, facing back",
    },
    "": {
        "audioinput": "Default Microphone",
        "audiooutput": "Default Speakers",
        "videoinput": "Default Camera",
    },
}

MEDIA_KINDS = ["audioinput", "videoinput", "audiooutput"]

# Only a program that speaks can know which voice it has. This is the value a
# reader is expected to edit, and it is listed as a gap for that reason.
DEFAULT_VOICE_TYPE = "MALE1"


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _block(value: Any) -> Dict[str, Any]:
    """Return a dict whatever arrived. Every block in a record is optional."""
    return value if isinstance(value, dict) else {}


def _slug(value: str) -> str:
    """Return a lowercase token safe to use as a group id."""
    out = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return out[:40]


def _safe_name(value: str) -> str:
    """Return a profile name safe to put in a filename or a header.

    The name reaches a Content-Disposition header and a file on disk, and it
    can come from a run label typed by whoever drove the page, so anything
    outside a conservative set is replaced rather than trusted. Case is kept:
    the name is a label a reader chose, not an identifier.
    """
    out = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return out[:60]


def _os_of(js: Dict[str, Any], headers: Dict[str, Any]) -> str:
    """Return the operating system family, from the most reliable source first.

    A current Chromium freezes its User-Agent — every Mac claims "Mac OS X
    10_15_7" — so the client hint is asked before the string it replaced.
    """
    hint = (_text(js.get("ua_platform"))
            or _text(headers.get("sec-ch-ua-platform")).strip('"'))
    families = {
        "macos": "mac", "mac os x": "mac", "windows": "windows",
        "linux": "linux", "android": "android", "ios": "ios",
        "chrome os": "chromeos", "chromium os": "chromeos",
    }
    if hint.lower() in families:
        return families[hint.lower()]

    platform = _text(js.get("platform")).lower()
    agent = (_text(js.get("user_agent")) or _text(headers.get("user-agent"))).lower()
    for source in (platform, agent):
        if not source:
            continue
        if "mac" in source and "iphone" not in source and "ipad" not in source:
            return "mac"
        if "win" in source:
            return "windows"
        if "android" in source:
            return "android"
        if "iphone" in source or "ipad" in source or "ios" in source:
            return "ios"
        if "cros" in source:
            return "chromeos"
        if "linux" in source or "x11" in source:
            return "linux"
    return ""


def _platform_version(js: Dict[str, Any], family: str) -> str:
    """Return the platform version as major.minor.patch.

    The client hint carries the real one. Falling back to the User-Agent gives
    the frozen value, which is a fair reproduction of what the client sent even
    though it is not what the machine runs.
    """
    hint = _text(js.get("ua_platform_version"))
    if hint:
        return hint

    agent = _text(js.get("user_agent"))
    patterns = [
        r"Mac OS X (\d+)[._](\d+)(?:[._](\d+))?",
        r"Windows NT (\d+)\.(\d+)",
        r"Android (\d+)(?:\.(\d+))?(?:\.(\d+))?",
        r"(?:iPhone )?OS (\d+)[._](\d+)(?:[._](\d+))?",
    ]
    for pattern in patterns:
        found = re.search(pattern, agent)
        if found:
            parts = [p or "0" for p in found.groups()]
            while len(parts) < 3:
                parts.append("0")
            return ".".join(parts[:3])
    if family == "linux":
        # Chromium reports an empty platformVersion on Linux. Not a gap.
        return ""
    return ""


def _screen(js: Dict[str, Any]) -> str:
    width, height = js.get("screen_width"), js.get("screen_height")
    if isinstance(width, (int, float)) and isinstance(height, (int, float)):
        return "%dx%d" % (int(width), int(height))
    return ""


def _language(js: Dict[str, Any], headers: Dict[str, Any]) -> str:
    language = _text(js.get("language"))
    if language:
        return language
    languages = _text(js.get("languages"))
    if languages:
        return languages.split(",")[0].strip()
    accept = _text(headers.get("accept-language"))
    if accept:
        return accept.split(",")[0].split(";")[0].strip()
    return ""


def _device_entry(kind: str, index: int, device: Dict[str, Any],
                  family: str) -> Dict[str, Any]:
    """Return one media device in the profile's shape."""
    label = _text(device.get("label")) or DEFAULT_DEVICE_LABELS.get(
        family, DEFAULT_DEVICE_LABELS[""])[kind]
    device_id = _text(device.get("deviceId")) or (
        "default" if index == 0 else "%s-%d" % (kind, index))
    entry = {
        "deviceId": device_id,
        "label": label,
        "groupId": _text(device.get("groupId")) or "grp-" + (_slug(label) or kind),
    }
    if kind == "videoinput":
        # enumerateDevices does not report a facing mode on a desktop. Read it
        # off the label when the label says, and assume the front camera when
        # it does not, because that is the one a laptop has.
        entry["facingMode"] = "environment" if "back" in label.lower() else "user"
    return entry


def _media_devices(environment: Dict[str, Any],
                   family: str) -> Tuple[Dict[str, List[Dict[str, Any]]], List[str]]:
    """Return the device list, and what had to be filled in to build it.

    The per-device list is preferred; a run recorded before it existed carries
    only the counts, and a device list is then rebuilt from them.
    """
    gaps: List[str] = []
    devices: Dict[str, List[Dict[str, Any]]] = {}

    stored = environment.get("media_device_list")
    if isinstance(stored, list):
        for device in stored:
            if not isinstance(device, dict):
                continue
            kind = _text(device.get("kind"))
            if kind not in MEDIA_KINDS:
                continue
            devices.setdefault(kind, [])
            devices[kind].append(
                _device_entry(kind, len(devices[kind]), device, family))
        if not environment.get("media_devices_labelled"):
            gaps.append("browser.media_devices[].label: the page was never granted "
                        "microphone or camera access, so every label came back "
                        "blank; platform defaults used")
        return devices, gaps

    counts = environment.get("media_devices")
    if isinstance(counts, dict) and counts:
        for kind in MEDIA_KINDS:
            total = counts.get(kind)
            if not isinstance(total, int) or total <= 0:
                continue
            devices[kind] = [_device_entry(kind, i, {}, family)
                             for i in range(total)]
        gaps.append("browser.media_devices[]: the run stored device counts only, "
                    "so ids and labels are platform defaults")
    elif environment:
        gaps.append("browser.media_devices: the run enumerated no devices")
    return devices, gaps


def build(record: Dict[str, Any], name: Optional[str] = None,
          voice_type: str = DEFAULT_VOICE_TYPE) -> Dict[str, Any]:
    """Return the replay profile for one stored run.

    `record` is a session as `/api/sessions/{id}` returns it, which is also
    exactly what the report page's Download JSON button writes to disk.
    """
    return describe(record, name=name, voice_type=voice_type)[0]


def describe(record: Dict[str, Any], name: Optional[str] = None,
             voice_type: str = DEFAULT_VOICE_TYPE
             ) -> Tuple[Dict[str, Any], List[str]]:
    """Return the profile and the list of fields no measurement backed.

    The gap list is the honest part. A profile prints as a complete document
    whether or not the run behind it held the values, and a reader who cannot
    see which fields were guessed will trust a guess.
    """
    record = _block(record)
    js = _block(record.get("js"))
    environment = _block(record.get("environment"))
    headers = _block(record.get("headers"))

    gaps: List[str] = []
    if not js:
        gaps.append("the run carries no browser fingerprint at all: it came from "
                    "a client that ran no JavaScript, so almost nothing below is "
                    "measured")

    family = _os_of(js, headers)
    if not family:
        gaps.append("os: neither the client hint nor the User-Agent named a platform")

    screen = _screen(js)
    if not screen:
        gaps.append("screen_resolution: the run recorded no screen size")

    timezone = _text(js.get("timezone"))
    if not timezone:
        gaps.append("timezone: the run recorded none; UTC assumed")
        timezone = "UTC"

    language = _language(js, headers)
    if not language:
        gaps.append("lang: the run recorded no language; en-US assumed")
        language = "en-US"

    agent = _text(js.get("user_agent")) or _text(headers.get("user-agent"))
    if not agent:
        gaps.append("browser.ua: the run recorded no User-Agent")

    platform_version = _platform_version(js, family)
    if not platform_version and family not in ("linux", ""):
        gaps.append("browser.ua_platform_version: no client hint was available "
                    "and the User-Agent named no version")

    concurrency = js.get("hardware_concurrency")
    if not isinstance(concurrency, int) or concurrency <= 0:
        gaps.append("browser.hardware_concurrency: the run recorded none")
        concurrency = 0

    webgl = {
        "vendor": _text(js.get("webgl_vendor")),
        "renderer": _text(js.get("webgl_renderer")),
        "version": _text(js.get("webgl_version")),
        "glsl_version": _text(js.get("webgl_glsl_version")),
    }
    if js.get("webgl_unmasked") is False and js.get("webgl_supported"):
        gaps.append("browser.webgl.vendor/renderer: the adapter names were masked, "
                    "so these are the generic strings the client reported rather "
                    "than the hardware behind them")
    if not webgl["version"]:
        gaps.append("browser.webgl.version/glsl_version: the run predates these "
                    "being collected, or WebGL was unavailable")

    gpu = _block(environment.get("webgpu"))
    webgpu = {
        "vendor": _text(gpu.get("vendor")),
        "architecture": _text(gpu.get("architecture")),
    }
    if not webgpu["vendor"]:
        # An adapter with no vendor is normal: Chromium reports empty strings
        # unless the origin is granted the WebGPU adapter-info permission.
        gaps.append("browser.webgpu: no adapter information was readable")

    devices, device_gaps = _media_devices(environment, family)
    gaps += device_gaps

    def first_label(kind: str) -> str:
        entries = devices.get(kind) or []
        return entries[0]["label"] if entries else ""

    run_id = _text(record.get("id"))
    chosen = (_safe_name(_text(name)) or _safe_name(_text(record.get("label")))
              or ("run-" + _safe_name(run_id)[:8] if run_id else "run"))

    profile: Dict[str, Any] = {
        "name": chosen,
        "os": family,
        "screen_resolution": screen,
        "timezone": timezone,
        "lang": language,
        "browser": {
            "ua": agent,
            "platform": _text(js.get("platform")),
            "ua_platform_version": platform_version,
            "hardware_concurrency": concurrency,
            "webgl": webgl,
            "webgpu": webgpu,
            "media_devices": devices,
        },
        "audio": {
            "sink_desc": first_label("audiooutput"),
            "mic_desc": first_label("audioinput"),
        },
        "speech": {
            "lang": language,
            "voice_type": _safe_name(_text(voice_type)) or DEFAULT_VOICE_TYPE,
            "trim": True,
        },
    }
    gaps.append("speech.voice_type and speech.trim: settings for whatever plays "
                "the audio, not facts about the client; no run can measure them")
    return profile, gaps
