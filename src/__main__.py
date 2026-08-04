"""Start the harness.

    python -m src

With TLS on, two listeners come up. uvicorn holds the certificate and serves
on the upstream port; the front end in src/loaders/tls_proxy.py listens on
APP_PORT, reads each ClientHello as it goes past, and pipes the still
encrypted stream to uvicorn. Clients only ever talk to APP_PORT.

With TLS off, uvicorn serves plain HTTP on APP_PORT and the tls layer reports
no data. Use that only to debug the page.
"""

import uvicorn

from .loaders.certificates import ensure_certificate
from .loaders.config import config


def main() -> None:
    # uvicorn builds its SSL context while it loads, which happens before the
    # lifespan runs, so the certificate has to exist by now.
    if config.TLS_ENABLED:
        ensure_certificate()

    scheme = "https" if config.TLS_ENABLED else "http"
    origin = "%s://%s:%d" % (scheme, config.APP_HOST, config.APP_PORT)

    print("Task page:  %s/" % origin)
    print("Dashboard:  %s/dashboard" % origin)
    print("CSV export: %s/api/export.csv" % origin)
    print("API docs:   %s/docs" % origin)
    print("Point an automation tool at the task page.")
    if config.TLS_ENABLED:
        print("")
        print("uvicorn logs an internal address on port %d below. Ignore it."
              % config.upstream_port)
        print("Use port %d. That is the only port that reads the TLS handshake;"
              % config.APP_PORT)
        print("anything sent to %d is redirected there." % config.upstream_port)
    print("Stop with Ctrl+C.")

    if config.TLS_ENABLED:
        uvicorn.run(
            "src.main:app",
            host=config.APP_HOST,
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
