import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


@pytest.fixture
def auth_database(monkeypatch):
    url = os.environ.get("CIVICFLOW_TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "Set CIVICFLOW_TEST_DATABASE_URL to an isolated PostgreSQL database"
        )
    monkeypatch.setenv("CIVICFLOW_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE oidc_transactions, sessions, external_identities, users CASCADE"
            )
        )
    yield url
    engine.dispose()
