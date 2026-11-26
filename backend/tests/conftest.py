"""Regression database selection. PostgreSQL requires a new dedicated test database."""
import os
from pathlib import Path
import re
import secrets
from tempfile import TemporaryDirectory

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url


def pytest_configure(config):
    address = os.environ.get('ASISTIX_TEST_DATABASE_URL')
    if address:
        url = make_url(address)
        if ((url.drivername, url.host, url.port, url.username) !=
                ('postgresql+psycopg', '127.0.0.1', 5433, 'asistix_lab')
                or not re.fullmatch(r'asistix_test_12_8_5_[a-f0-9]{8}', url.database or '')
                or url.query):
            raise pytest.UsageError('PostgreSQL tests require a separate ASISTIX laboratory test database.')
    else:
        temp = TemporaryDirectory(prefix='asistix-test-')
        config.add_cleanup(temp.cleanup)
        address = 'sqlite:///' + (Path(temp.name) / 'test.db').as_posix()
    os.environ.update(DATABASE_URL=address, JWT_SECRET=secrets.token_urlsafe(48), DEMO_MODE='true')


def pytest_sessionstart(session):
    from app.db import engine

    if engine.dialect.name == 'postgresql':
        with engine.connect() as conn:
            if (conn.scalar(text('SELECT current_database()')) != engine.url.database
                    or conn.scalar(text('SELECT current_user')) != 'asistix_lab'
                    or inspect(conn).get_table_names()):
                raise pytest.UsageError('The PostgreSQL test database must be empty and owned by the test role.')


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.db import Base, engine
    from app.main import app, attempts
    from app.seed import seed

    attempts.clear()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        with TestClient(app) as test_client:
            seed()
            yield test_client
    finally:
        engine.dispose()
