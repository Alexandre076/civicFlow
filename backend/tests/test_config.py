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
