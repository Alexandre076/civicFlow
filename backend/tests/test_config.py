from civicflow.config import Settings
from civicflow.main import create_app


def test_default_app_name(monkeypatch):
    monkeypatch.delenv("CIVICFLOW_APP_NAME", raising=False)

    assert Settings(_env_file=None).app_name == "CivicFlow API"


def test_environment_overrides_dotenv(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("CIVICFLOW_APP_NAME=Local API\n", encoding="utf-8")
    monkeypatch.delenv("CIVICFLOW_APP_NAME", raising=False)
    assert Settings(_env_file=env_file).app_name == "Local API"

    monkeypatch.setenv("CIVICFLOW_APP_NAME", "Environment API")
    settings = Settings(_env_file=env_file)

    assert create_app(settings).title == "Environment API"


def test_insecure_cookie_configuration():
    import pytest
    from pydantic import ValidationError

    local = Settings(_env_file=None, secure_cookies=False)
    assert local.session_cookie == "civicflow_session_dev"
    assert local.transaction_cookie == "civicflow_login_dev"
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            secure_cookies=False,
            public_origin="http://public.example",
            callback_url="http://public.example/api/v1/auth/google/callback",
        )
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            public_origin="https://safe.example",
            callback_url="https://evil.example/callback",
        )


def test_finite_session_configuration():
    import pytest
    from pydantic import ValidationError

    settings = Settings(_env_file=None)
    assert (
        settings.login_ttl,
        settings.session_idle_ttl,
        settings.session_absolute_ttl,
        settings.clock_skew,
    ) == (600, 86400, 604800, 60)
    for overrides in (
        {"login_ttl": 0},
        {"session_idle_ttl": -1},
        {"clock_skew": 121},
        {"allowed_return_paths": ["//evil.example"]},
        {"allowed_return_paths": ["/%2fevil"]},
    ):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **overrides)


def test_trusted_proxy_requires_loopback_and_public_https():
    import pytest
    from pydantic import ValidationError

    public = {
        "public_origin": "https://civicflow.test",
        "callback_url": "https://civicflow.test/api/v1/auth/google/callback",
    }
    settings = Settings(
        _env_file=None, trusted_proxy_origin="http://localhost:5173", **public
    )
    assert settings.trusted_proxy_origin == "http://localhost:5173"
    for proxy in (
        "https://evil.test:5173",
        "http://localhost",
        "http://localhost:5173/",
        "http://localhost:5173?query=1",
        "http://user@localhost:5173",
        "null",
    ):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, trusted_proxy_origin=proxy, **public)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, trusted_proxy_origin="http://localhost:5173")
