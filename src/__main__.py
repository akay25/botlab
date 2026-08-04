"""Start the harness.

    python -m src
    python -m src --host 0.0.0.0          # reachable from other machines

With TLS on, two listeners come up. uvicorn holds the certificate and serves on
the upstream port, bound to loopback so nothing off this machine can reach it;
the front end in src/loaders/tls_proxy.py listens on APP_HOST:APP_PORT, reads
each ClientHello as it goes past, and pipes the still encrypted stream to
uvicorn. Clients only ever talk to APP_PORT.

With TLS off, uvicorn serves plain HTTP on APP_HOST:APP_PORT and the tls layer
reports no data. Use that only to debug the page.

A flag given here beats what .env says, which is the one override `pipenv run`
does not otherwise allow: it loads .env itself and what it loads wins over the
environment, so `APP_HOST=0.0.0.0 pipenv run start` does nothing while
`pipenv run start --host 0.0.0.0` works.
"""

import argparse

import uvicorn

from .loaders.certificates import ensure_certificate
from .loaders.config import config


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src",
        description="Start the botlab harness.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Binding anything other than a loopback address publishes the "
               "harness to your network. It has no authentication, and the run "
               "log holds fingerprints and the keys that were typed. Bind a "
               "wildcard only on a network you trust.")
    parser.add_argument("--host", default=None,
                        help="Address to bind, overriding APP_HOST. Use 0.0.0.0 to "
                             "accept connections from other machines.")
    parser.add_argument("--port", type=int, default=None,
                        help="Port clients talk to, overriding APP_PORT.")
    parser.add_argument("--cert-host", action="append", default=[], metavar="NAME",
                        help="An extra name or address the certificate must cover. "
                             "Repeatable. Use this when clients reach the harness on "
                             "an address it cannot work out for itself, which happens "
                             "on a machine with more than one adapter.")
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    if arguments.host:
        config.APP_HOST = arguments.host
    if arguments.port:
        config.APP_PORT = arguments.port
    if arguments.cert_host:
        existing = [part.strip() for part in config.CERT_HOSTS.split(",") if part.strip()]
        config.CERT_HOSTS = ",".join(existing + arguments.cert_host)

    # uvicorn builds its SSL context while it loads, which happens before the
    # lifespan runs, so the certificate has to exist by now. It also has to
    # cover whatever address clients will use, which the host flag just changed.
    if config.TLS_ENABLED:
        ensure_certificate()

    scheme = "https" if config.TLS_ENABLED else "http"
    shown = "127.0.0.1" if config.binds_wildcard else config.APP_HOST
    origin = "%s://%s:%d" % (scheme, shown, config.APP_PORT)

    print("Task page:  %s/" % origin)
    print("Dashboard:  %s/dashboard" % origin)
    print("CSV export: %s/api/export.csv" % origin)
    print("API docs:   %s/docs" % origin)
    print("Point an automation tool at the task page.")
    if config.binds_wildcard:
        from .loaders.certificates import certificate_hosts
        names, addresses = certificate_hosts()
        print("")
        print("Bound to %s, so other machines on your network can reach this."
              % config.APP_HOST)
        print("Reach it from another machine at one of:")
        for name in sorted(addresses) + sorted(names):
            if name in ("127.0.0.1", "::1"):
                continue
            shown_host = "[%s]" % name if ":" in name else name
            print("    %s://%s:%d/" % (scheme, shown_host, config.APP_PORT))
        print("The certificate covers exactly those. If clients reach this machine")
        print("on an address not listed, add it with --cert-host and restart.")
        print("There is no authentication, and the run log holds fingerprints and")
        print("the keys that were typed.")
    if config.TLS_ENABLED:
        print("")
        print("uvicorn logs an internal address on port %d below. Ignore it."
              % config.upstream_port)
        print("Use port %d. That is the only port that reads the TLS handshake;"
              % config.APP_PORT)
        print("anything sent to %d is redirected there." % config.upstream_port)
    print("Stop with Ctrl+C.")

    if config.TLS_ENABLED:
        # Loopback whatever APP_HOST is: only the front end should be reachable
        # from the network, so the port that bypasses the handshake reader
        # cannot be reached from another machine at all.
        uvicorn.run(
            "src.main:app",
            host=config.upstream_host,
            port=config.upstream_port,
            ssl_certfile=config.cert_file,
            ssl_keyfile=config.key_file,
            log_level=config.LOG_LEVEL.lower(),
        )
    else:
        uvicorn.run(
            "src.main:app",
            host=config.APP_HOST,
            port=config.APP_PORT,
            log_level=config.LOG_LEVEL.lower(),
        )


if __name__ == "__main__":
    main()
