import os
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ENV config
    ENV: str = Field(default="dev")

    # App config
    APP_NAME: str = Field(default="botlab")
    APP_HOST: str = Field(default="127.0.0.1")
    APP_PORT: int = Field(default=8443)
    ALLOWED_HOSTS: str = Field(default="*")

    # Log config
    LOG_LEVEL: str = Field(default="INFO")

    # TLS config. The harness serves a certificate it signs itself, because it
    # is a local test origin. Turning TLS off leaves the tls layer unmeasured.
    TLS_ENABLED: bool = Field(default=True)
    # uvicorn listens here and the peeking front end listens on APP_PORT. See
    # src/loaders/tls_proxy.py for why the two are separate.
    TLS_UPSTREAM_PORT: int = Field(default=0)
    # Extra names or addresses the certificate must cover, comma separated.
    # Needed when clients reach the harness by a name this machine cannot
    # resolve for itself, such as a DNS alias or a tunnel.
    CERT_HOSTS: str = Field(default="")

    # Storage config
    DATA_DIR: str = Field(default=os.path.join(BASE_DIR, "data"))

    # How many scored sessions to keep in memory for the dashboard.
    SESSION_CACHE_SIZE: int = Field(default=500)

    @property
    def upstream_port(self) -> int:
        return self.TLS_UPSTREAM_PORT or (self.APP_PORT + 1)

    @property
    def upstream_host(self) -> str:
        """Where uvicorn binds when the ClientHello front end is in play.

        Always loopback, whatever APP_HOST is. Only the front end should be
        reachable from the network: binding uvicorn to 0.0.0.0 as well would
        publish the one port that bypasses the handshake reader, and a client
        that found it would be scored with its tls layer silently missing.
        """
        return "127.0.0.1"

    @property
    def binds_wildcard(self) -> bool:
        """Whether APP_HOST means "every address on this machine"."""
        return self.APP_HOST in ("0.0.0.0", "::", "")

    @property
    def cert_file(self) -> str:
        return os.path.join(self.DATA_DIR, "harness-cert.pem")

    @property
    def key_file(self) -> str:
        return os.path.join(self.DATA_DIR, "harness-key.pem")

    @property
    def log_file(self) -> str:
        return os.path.join(self.DATA_DIR, "sessions.jsonl")

    @property
    def calibration_file(self) -> str:
        return os.path.join(self.DATA_DIR, "calibration.json")

    @property
    def static_dir(self) -> str:
        return os.path.join(BASE_DIR, "src", "static")


config = Settings()
