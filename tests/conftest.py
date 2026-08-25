"""Shared pytest fixtures for the ETL test suite."""

from io import StringIO

from datetime import datetime, timezone

import pytest
from loguru import logger
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from etl.config import Settings
from etl.load import build_database_url, build_engine, ensure_table


# tests use a local postgres database for parity against the desired deployment state
TEST_DB_SETTINGS = {
    "postgres_host": "localhost",
    "postgres_port": 5432,
    "postgres_user": "etl",
    "postgres_password": "etl",
}
TEST_DB_NAME = "du_chapters_test"


def _make_settings(db_name: str) -> Settings:
    """Return Settings pointing at the supplied database name."""
    return Settings(
        **TEST_DB_SETTINGS,
        postgres_db=db_name,
        source_url=(
            "https://example.com/chapters"
        ),
        target_states=["CA"],
        arcgis_page_size=1000,
        request_timeout=30,
        log_level="INFO",
    )


@pytest.fixture
def settings() -> Settings:
    """Return settings configured for the test database."""
    return _make_settings(TEST_DB_NAME)


@pytest.fixture(scope="session", autouse=True)
def engine():
    """Create the test database, build tables, and tear down after the session."""
    # connect to the existing database, then switch to postgres
    # so we can run admin commands to create the new test database
    base_settings = _make_settings("du_chapters")
    admin_url = build_database_url(base_settings).replace("/du_chapters", "/postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")

    # create a test specific database
    with admin_engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME}"))
        conn.execute(text(f"CREATE DATABASE {TEST_DB_NAME}"))

    test_settings = _make_settings(TEST_DB_NAME)
    eng = build_engine(test_settings)
    ensure_table(eng)
    yield eng
    eng.dispose()

    # drop the database after the tests have run
    with admin_engine.connect() as conn:
        conn.execute(
            text(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = :db_name
                """
            ),
            {"db_name": TEST_DB_NAME},
        )
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME}"))

    admin_engine.dispose()


@pytest.fixture
def session(engine):
    """Yield a fresh SQLAlchemy session with a clean university_chapters table."""
    with Session(engine) as sess:
        # truncate before we yield the session
        sess.execute(text("TRUNCATE TABLE university_chapters CASCADE"))
        sess.commit()
        yield sess
        # TRUNCATE after the test runs, while the session is still open
        sess.rollback()
        sess.execute(text("TRUNCATE TABLE university_chapters CASCADE"))
        sess.commit()


@pytest.fixture
def batch_timestamp() -> datetime:
    """Return a fixed UTC timestamp for SCD2 batch tests."""
    return datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def loguru_capture():
    """Capture loguru output at WARNING level and above for a single test."""
    stream = StringIO()
    handler_id = logger.add(stream, level="WARNING")
    try:
        yield stream
    finally:
        logger.remove(handler_id)


@pytest.fixture
def sample_feature():
    """Return a single valid ArcGIS feature for California."""
    return {
        "attributes": {
            "ChapterID": "CA-001",
            "University_Chapter": "Duck State University",
            "City": "Sacramento",
            "State": "CA",
        },
        "geometry": {"x": -121.4944, "y": 38.5816},
    }


@pytest.fixture
def sample_features():
    """Return features spanning multiple states."""
    return {
        "features": [
            {
                "attributes": {
                    "ChapterID": "CA-001",
                    "University_Chapter": "Duck State University",
                    "City": "Sacramento",
                    "State": "CA",
                },
                "geometry": {"x": -121.4944, "y": 38.5816},
            },
            {
                "attributes": {
                    "ChapterID": "NY-001",
                    "University_Chapter": "New York Duck College",
                    "City": "Albany",
                    "State": "NY",
                },
                "geometry": {"x": -73.7562, "y": 42.6526},
            },
        ]
    }
