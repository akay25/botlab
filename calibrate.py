"""File a measured fingerprint into the calibration table.

Calibrate before you report any result. The table starts empty because a
JA4 hash changes with every browser release. A table you copied from a blog
post is not evidence.

Procedure:
  1. Start the server.
  2. Open the test page in the client you want to record.
  3. Run this script with the class and the label for that client.

Example:
  python3 calibrate.py --class human --label "chrome-141-macos"
  python3 calibrate.py --class automation --label "playwright-chromium-1.49"
"""

import argparse
import json
import os

import reference
import server


def latest_session(label_filter=""):
    """Return the newest logged session that carried a TLS fingerprint."""
    if not os.path.exists(server.LOG_FILE):
        return None
    newest = None
    with open(server.LOG_FILE) as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not record.get("tls"):
                continue
            if label_filter and record.get("label") != label_filter:
                continue
            newest = record
    return newest


def main():
    parser = argparse.ArgumentParser(description="Record a fingerprint in the calibration table.")
    parser.add_argument("--class", dest="klass", required=True,
                        choices=["human", "automation"],
                        help="Record the client as a real browser or as an automation client.")
    parser.add_argument("--label", required=True, help="A name for the client and its version.")
    parser.add_argument("--match-label", default="",
                        help="Only read a session that already carries this run label.")
    parser.add_argument("--list", action="store_true", help="Print the table and exit.")
    args = parser.parse_args()

    table = reference.load_calibration()
    if args.list:
        print(json.dumps(table, indent=2, sort_keys=True))
        return

    record = latest_session(args.match_label)
    if record is None:
        print("No logged session carries a TLS fingerprint. Start the server and load the page.")
        return

    tls = record["tls"]
    table.setdefault(args.klass + "_ja4", {})[tls["ja4"]] = args.label
    table.setdefault(args.klass + "_ja3", {})[tls["ja3"]] = args.label
    reference.save_calibration(table)

    print("Recorded %s as %s." % (args.label, args.klass))
    print("  JA4   %s" % tls["ja4"])
    print("  JA4_r %s" % tls["ja4_r"])
    print("  JA3   %s" % tls["ja3"])
    print("  UA    %s" % record.get("headers", {}).get("user-agent", ""))


if __name__ == "__main__":
    main()
