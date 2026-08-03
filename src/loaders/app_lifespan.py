from contextlib import asynccontextmanager

from fastapi import FastAPI

from .certificates import ensure_certificate
from .config import config
from .logging import get_logger
from . import tls_proxy

logger = get_logger("app_lifespan")


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    logger.info("Starting the %s harness in %s", config.APP_NAME, config.ENV)

    front_end = None
    if config.TLS_ENABLED:
        # The entry point generates the certificate before uvicorn loads it.
        # Call again in case the app was started some other way.
        ensure_certificate()
        # uvicorn holds the certificate and terminates TLS on the upstream
        # port. The front end sits on the public port and reads the handshake
        # on its way past.
        front_end = await tls_proxy.start(
            config.APP_HOST, config.APP_PORT,
            config.APP_HOST, config.upstream_port)
    else:
        logger.warning("TLS is off. The tls layer will report no data.")

    try:
        yield
    finally:
        if front_end is not None:
            front_end.close()
            await front_end.wait_closed()
            logger.info("TLS front end stopped")
        logger.info("Harness stopped")
