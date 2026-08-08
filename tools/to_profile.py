"""Turn a downloaded run into a replay profile.

The report page's Download JSON button writes the whole record: what the
client reported, what the harness measured, and the score. This reads one of
those files and writes the profile — the same facts pointed the other way,
naming what another client would have to report to look like this one.

  python3 to_profile.py ~/Downloads/botlab-<label>.json
  python3 to_profile.py run.json --name mac-m4 -o profile.json

The fields no measurement backed are listed on stderr, so a redirect gets the
profile alone and the terminal still says which values were filled in. Pass
--quiet to drop them.

A whole log converts in one go. Point it at data/sessions.jsonl with -o set to
a directory and every run in the file becomes its own profile.

The running harness serves the same document, if it is easier to reach:
  curl -k https://127.0.0.1:8443/api/export/profile/<id>.json
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.profile import DEFAULT_VOICE_TYPE, describe      # noqa: E402


def read_records(path):
    """Return every session record in one file.

    Three shapes arrive here: a single downloaded record, a JSON array of
    them, and the harness's own sessions.jsonl, which is one record per line.
    """
    text = sys.stdin.read() if path == "-" else open(path).read()
    stripped = text.strip()
    if not stripped:
        return []
    if stripped[0] == "[":
        loaded = json.loads(stripped)
        return [r for r in loaded if isinstance(r, dict)]
    try:
        loaded = json.loads(stripped)
    except json.JSONDecodeError:
        records = []
        for number, line in enumerate(stripped.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                raise SystemExit("%s line %d is not JSON." % (path, number))
        return [r for r in records if isinstance(r, dict)]
    if not isinstance(loaded, dict):
        raise SystemExit("%s does not hold a session record." % path)
    # The API wraps a record in {success, message, data}. Unwrap it, so a file
    # saved straight from curl works as well as one saved from the report page.
    if "js" not in loaded and isinstance(loaded.get("data"), dict):
        loaded = loaded["data"]
    return [loaded]


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="+",
                        help="downloaded run files, sessions.jsonl, or - for stdin")
    parser.add_argument("--name", default="",
                        help="profile name; the run label is used when this is unset")
    parser.add_argument("--voice-type", default=DEFAULT_VOICE_TYPE,
                        help="speech.voice_type, which no run can measure "
                             "(default: %(default)s)")
    parser.add_argument("-o", "--out", default="",
                        help="write here instead of stdout; must be a directory "
                             "when more than one run is converted")
    parser.add_argument("--quiet", action="store_true",
                        help="do not list the fields no measurement backed")
    args = parser.parse_args()

    records = []
    for path in args.paths:
        try:
            records += read_records(path)
        except OSError as error:
            raise SystemExit("Could not read %s: %s" % (path, error))
    if not records:
        raise SystemExit("Those files hold no session records.")

    if args.name and len(records) > 1:
        raise SystemExit("--name names one profile, but %d runs were read."
                         % len(records))
    directory = len(records) > 1 or (args.out and os.path.isdir(args.out))
    if directory:
        if not args.out:
            raise SystemExit("Converting %d runs at once needs -o pointing at a "
                             "directory." % len(records))
        if not os.path.isdir(args.out):
            raise SystemExit("%s is not a directory. Converting %d runs writes one "
                             "file per run, so -o has to name one that exists."
                             % (args.out, len(records)))

    written = set()
    for record in records:
        built, gaps = describe(record, name=args.name or None,
                               voice_type=args.voice_type)
        text = json.dumps(built, indent=2) + "\n"
        if directory:
            # Runs share a label freely — a comparison matrix is built by
            # running the same client twice — so the run id separates two
            # profiles that would otherwise write to the same file.
            stem = built["name"]
            if stem in written:
                stem = "%s-%s" % (stem, str(record.get("id") or "")[:8])
            written.add(stem)
            target = os.path.join(args.out, "botlab-profile-%s.json" % stem)
            with open(target, "w") as handle:
                handle.write(text)
            print(target, file=sys.stderr)
        elif args.out:
            with open(args.out, "w") as handle:
                handle.write(text)
        else:
            sys.stdout.write(text)

        if not args.quiet and gaps:
            print("\n%s: fields no measurement backed" % built["name"], file=sys.stderr)
            for gap in gaps:
                print("  - " + gap, file=sys.stderr)


if __name__ == "__main__":
    main()
