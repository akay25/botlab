"""Send a set of non-browser clients to the backend and print the result table.

The matrix shows the central finding. A client can spoof the User-Agent and
still fail at the TLS layer, because the handshake happens before any header
arrives.

These clients run no JavaScript and load no extension, so they are scored on
the network, TLS, HTTP and consistency layers alone. Add the browser rows by
loading the extension in each browser with its own run label.

Start the backend first. Then run:
  python3 client_matrix.py --url https://127.0.0.1:8443
"""

import argparse
import json
import os
import shutil
import ssl
import subprocess
import sys
import urllib.request

import scoring

CHROME_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")

# Headers that a Chromium browser sends, in the order that it sends them.
CHROME_HEADERS = [
    ("sec-ch-ua", '"Chromium";v="141", "Not(A:Brand";v="24"'),
    ("sec-ch-ua-mobile", "?0"),
    ("sec-ch-ua-platform", '"Windows"'),
    ("upgrade-insecure-requests", "1"),
    ("user-agent", CHROME_UA),
    ("accept", "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
               "image/webp,image/apng,*/*;q=0.8"),
    ("sec-fetch-site", "none"),
    ("sec-fetch-mode", "navigate"),
    ("sec-fetch-user", "?1"),
    ("sec-fetch-dest", "document"),
    ("accept-encoding", "gzip, deflate, br"),
    ("accept-language", "en-US,en;q=0.9"),
]


def probe_urllib(url, label, headers=None):
    """Send one request with the Python standard library client."""
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    request = urllib.request.Request(url + "/api/probe?label=" + label)
    if headers:
        for name, value in headers:
            request.add_header(name, value)
    with urllib.request.urlopen(request, context=context, timeout=10) as response:
        return json.loads(response.read().decode())


def probe_curl(url, label, extra=None):
    """Send one request with the curl binary, if the system has it."""
    if not shutil.which("curl"):
        return None
    command = ["curl", "-sk", url + "/api/probe?label=" + label]
    for item in extra or []:
        command += ["-H", item]
    output = subprocess.run(command, capture_output=True, timeout=20)
    if output.returncode != 0:
        return None
    try:
        return json.loads(output.stdout.decode())
    except ValueError:
        return None


def row(record):
    """Return one printable row from a probe response."""
    if record is None:
        return None
    result = record.get("result", {})
    tls = record.get("tls") or {}
    layers = result.get("layers", {})
    hot = [name for name in scoring.LAYERS
           if layers.get(name, {}).get("weight", 0) > 0]
    return {
        "label": record.get("label", ""),
        "score": result.get("score", 0),
        "verdict": result.get("verdict", ""),
        "earliest": result.get("first_catching_layer") or "-",
        "strongest": result.get("strongest_layer") or "-",
        "flagging_layers": ",".join(hot) or "-",
        "ja4": tls.get("ja4", "-"),
        "grease": "yes" if tls.get("grease") else "no",
    }


def print_table(rows):
    """Print the matrix as a fixed-width table."""
    columns = ["label", "score", "verdict", "earliest", "strongest", "grease", "ja4"]
    widths = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in columns}
    line = "  ".join(c.upper().ljust(widths[c]) for c in columns)
    print(line)
    print("-" * len(line))
    for r in rows:
        print("  ".join(str(r[c]).ljust(widths[c]) for c in columns))


def main():
    parser = argparse.ArgumentParser(description="Run the client matrix against the harness.")
    parser.add_argument("--url", default="https://127.0.0.1:8443")
    parser.add_argument("--csv", default="", help="Also write the table to this CSV path.")
    args = parser.parse_args()
    url = args.url.rstrip("/")

    probes = [
        ("py-urllib-default", lambda: probe_urllib(url, "py-urllib-default")),
        ("py-urllib-chrome-ua", lambda: probe_urllib(url, "py-urllib-chrome-ua",
                                                    [("user-agent", CHROME_UA)])),
        ("py-urllib-full-spoof", lambda: probe_urllib(url, "py-urllib-full-spoof",
                                                     CHROME_HEADERS)),
        ("curl-default", lambda: probe_curl(url, "curl-default")),
        ("curl-chrome-ua", lambda: probe_curl(url, "curl-chrome-ua",
                                              ["User-Agent: " + CHROME_UA])),
    ]

    rows = []
    for name, run in probes:
        try:
            record = run()
        except Exception as error:              # the client failed to connect
            print("%s did not complete: %s" % (name, error), file=sys.stderr)
            continue
        built = row(record)
        if built:
            rows.append(built)

    if not rows:
        print("No client reached the harness. Check that the server is running.")
        return

    print_table(rows)
    print("\nEvery client above spoofs headers only. The TLS layer sees the real client.")
    print("Add the browser rows by loading the extension in a real browser and in a stealth")
    print("browser, with one run label per client, and sending each report to this backend.")

    if args.csv:
        import csv
        with open(args.csv, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print("Wrote %s." % os.path.abspath(args.csv))


if __name__ == "__main__":
    main()
