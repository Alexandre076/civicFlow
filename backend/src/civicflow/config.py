"""Environment-driven application configuration."""

from urllib.parse import urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CIVICFLOW_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "CivicFlow API"

    database_url: str = (
        "postgresql+psycopg://civicflow:civicflow@localhost:5432/civicflow"
    )
    google_client_id: str = ""
    google_client_secret: str = ""
    public_origin: str = "http://localhost:5173"
    callback_url: str = "http://localhost:5173/api/v1/auth/google/callback"
    allowed_return_paths: list[str] = ["/"]
    trusted_proxy_origin: str | None = None
    secure_cookies: bool = True
    login_ttl: int = 600
    session_idle_ttl: int = 86400
    session_absolute_ttl: int = 604800
    clock_skew: int = 60

    @property
    def session_cookie(self) -> str:
        return (
            "__Host-civicflow_session"
            if self.secure_cookies
            else "civicflow_session_dev"
        )

    @property
    def transaction_cookie(self) -> str:
        return (
            "__Host-civicflow_login" if self.secure_cookies else "civicflow_login_dev"
        )

    @model_validator(mode="after")
    def validate_auth(self):
        origin = urlsplit(self.public_origin)
        callback = urlsplit(self.callback_url)
        if origin.scheme not in {"http", "https"} or not origin.hostname:
            raise ValueError("Invalid public origin")
        if origin.path or origin.query or origin.fragment or origin.username:
            raise ValueError("Public origin must contain only scheme and authority")
        if callback.scheme != origin.scheme or callback.netloc != origin.netloc:
            raise ValueError("Callback must use the configured public origin")
        if callback.query or callback.fragment or callback.username:
            raise ValueError("Invalid callback URL")
        if not self.secure_cookies:
            if origin.scheme != "http" or origin.hostname not in {
                "localhost",
                "127.0.0.1",
                "::1",
            }:
                raise ValueError("Insecure cookies require explicit loopback HTTP")
        elif origin.scheme != "https" and origin.hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise ValueError("Public deployments require HTTPS")
        if self.trusted_proxy_origin is not None:
            proxy = urlsplit(self.trusted_proxy_origin)
            if (
                origin.scheme != "https"
                or proxy.scheme not in {"http", "https"}
                or proxy.hostname not in {"localhost", "127.0.0.1", "::1"}
                or proxy.port is None
                or proxy.path
                or proxy.query
                or proxy.fragment
                or proxy.username is not None
            ):
                raise ValueError(
                    "Proxy origin requires explicit loopback port and public HTTPS"
                )
        for path in self.allowed_return_paths:
            if (
                not path.startswith("/")
                or path.startswith("//")
                or any(c in path for c in "%\\?#")
                or any(ord(c) < 33 for c in path)
            ):
                raise ValueError("Return paths must be literal relative UI paths")
        if not all(
            1 <= value <= 31536000
            for value in (
                self.login_ttl,
                self.session_idle_ttl,
                self.session_absolute_ttl,
            )
        ):
            raise ValueError("Expiry durations must be finite positive seconds")
        if not 0 <= self.clock_skew <= 120:
            raise ValueError("Clock skew must be between zero and 120 seconds")
        return self
