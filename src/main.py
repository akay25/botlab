# Regular imports
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

# Local imports
from .loaders.app_lifespan import app_lifespan
from .loaders.config import config
from .loaders.logging import get_logger
from .routes import collect, exports, pages, sessions

app = FastAPI(
    title=config.APP_NAME,
    description=(
        "A bot detection harness. An automation tool drives the task page at / "
        "and the harness reports which layer identified it. A non-browser "
        "client reaches /api/probe instead and is scored on the layers that "
        "need no JavaScript. Both go through the same registry of eight layers."
    ),
    debug=config.ENV != "PROD",
    lifespan=app_lifespan,
)

# Set logger
app.logger = get_logger(config.APP_NAME)  # type: ignore
app.logger.propagate = True  # type: ignore

origins = ["*"] if config.ALLOWED_HOSTS.strip() == "*" \
    else list(config.ALLOWED_HOSTS.split(","))


# Defined before the CORS middleware is added, so CORS ends up outermost and
# wraps the redirect below. A cross-origin client must see the redirect as a
# valid CORS response before it will follow it.
@app.middleware("http")
async def redirect_upstream_traffic(request: Request, call_next):
    """Send anything that reached uvicorn directly back to the public port.

    With TLS on, uvicorn listens on the upstream port and the ClientHello
    front end listens on the public one. uvicorn logs its own banner naming
    the upstream port, which reads like an invitation, and a client that
    accepts it bypasses the front end: the request still succeeds, but no
    handshake is ever read and the run silently loses its tls layer.

    The Host header says which port the client aimed at, so the mistake is
    visible and worth correcting rather than merely reporting. 307 keeps the
    method and the body, so a report posted to the wrong port still lands.
    """
    if not config.TLS_ENABLED:
        return await call_next(request)

    host = request.headers.get("host", "")
    if not host.endswith(":%d" % config.upstream_port):
        return await call_next(request)

    # Redirect to the hostname the client actually used, not to APP_HOST.
    # localhost and 127.0.0.1 are different origins, so sending a client that
    # asked for one to the other turns a same-origin page into a cross-origin
    # one, and the report it posts afterwards fails as a CORS error.
    hostname = request.url.hostname or config.APP_HOST
    if ":" in hostname:                        # an IPv6 literal needs its brackets back
        hostname = "[%s]" % hostname
    target = "https://%s:%d%s" % (hostname, config.APP_PORT, request.url.path)
    if request.url.query:
        target = "%s?%s" % (target, request.url.query)
    app.logger.warning(  # type: ignore
        "Redirecting %s %s from the upstream port to %s",
        request.method, request.url.path, target)
    return RedirectResponse(target, status_code=307)


# Defined after the redirect and before the CORS middleware, so it ends up
# inside the CORS layer. Starlette's ServerErrorMiddleware is the outermost
# layer of all, so an unhandled exception is returned from outside CORS with no
# Access-Control-Allow-Origin on it. A browser then reports the symptom as a
# CORS failure and hides the server error underneath, which is the single most
# misleading thing this app can do to someone debugging it. Catching here keeps
# the real status and the real message visible to a cross-origin caller.
@app.middleware("http")
async def report_errors_inside_cors(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception:
        app.logger.exception("Unhandled exception on %s", request.url.path)  # type: ignore
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "Internal server error",
                "status_code": 500,
                "data": {},
            },
        )


# The task page is served by this app and reports to its own origin, so it
# needs none of this. CORS stays because a client on another origin may post a
# report or read the API, and because the redirect above has to be a valid CORS
# response before a cross-origin client will follow it. ALLOWED_HOSTS narrows it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load routes
app.include_router(collect.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
app.include_router(sessions.probe_router, prefix="/api")
app.include_router(exports.router, prefix="/api")

# The browser-facing pages sit outside /api.
app.include_router(pages.router)


@app.exception_handler(HTTPException)
async def handle_http_exceptions(request: Request, exc: HTTPException):
    exception_data = {}
    if hasattr(exc, "data"):
        exception_data = exc.data  # type: ignore

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "message": exc.detail,
            "status_code": exc.status_code,
            "data": exception_data,
        },
    )


# An @app.exception_handler(Exception) would run in ServerErrorMiddleware,
# outside CORS. report_errors_inside_cors above does the same job where the
# CORS layer can still reach the response.


# Health check endpoint
@app.get("/api/health", tags=["health"])
async def health_check():
    return {"status": "ok", "tls": config.TLS_ENABLED}
