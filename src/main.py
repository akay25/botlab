# Regular imports
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Local imports
from .loaders.app_lifespan import app_lifespan
from .loaders.config import config
from .loaders.logging import get_logger
from .routes import collect, exports, pages, sessions

app = FastAPI(
    title=config.APP_NAME,
    description=(
        "A bot detection harness. An automation tool drives the task page at / "
        "and the harness reports which layer identified it; a browser under "
        "test reports through the extension instead. Both are scored by the "
        "same registry across nine layers."
    ),
    debug=config.ENV != "PROD",
    lifespan=app_lifespan,
)

# Set logger
app.logger = get_logger(config.APP_NAME)  # type: ignore
app.logger.propagate = True  # type: ignore

origins = ["*"] if config.ALLOWED_HOSTS.strip() == "*" \
    else list(config.ALLOWED_HOSTS.split(","))

# The extension reports from whatever origin the page under test is on, so it
# is a genuinely cross-origin client of this API.
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


@app.exception_handler(Exception)
async def handle_generic_exceptions(request: Request, exc: Exception):
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


# Health check endpoint
@app.get("/api/health", tags=["health"])
async def health_check():
    return {"status": "ok", "tls": config.TLS_ENABLED}
