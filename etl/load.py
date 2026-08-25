"""Load transformed rows into Postgres using an SCD2 pattern."""

import json
from datetime import datetime

import boto3
from botocore.exceptions import ClientError
from loguru import logger
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from etl.config import Settings
from etl.exceptions import LoadError
from etl.models import ChapterRow, UniversityChapter
from etl.transform import hash_row


def get_secret_value(secret_arn: str) -> dict:
    """Fetch and parse a JSON secret from AWS Secrets Manager."""
    try:
        client = boto3.client("secretsmanager")
        response = client.get_secret_value(SecretId=secret_arn)
        return json.loads(response["SecretString"])
    except ClientError as exc:
        raise LoadError(f"Failed to retrieve secret {secret_arn}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise LoadError(f"Secret {secret_arn} is not valid JSON: {exc}") from exc


def resolve_db_settings(settings: Settings) -> dict:
    """Return database connection settings from Secrets Manager or env vars.

    Secrets Manager values take precedence over environment variables.
    Supported secret keys: username, password, host, port, dbname.
    """
    defaults = {
        "username": settings.postgres_user,
        "password": settings.postgres_password,
        "host": settings.postgres_host,
        "port": settings.postgres_port,
        "dbname": settings.postgres_db,
    }
    if settings.db_secret_arn:
        secret = get_secret_value(settings.db_secret_arn)
        for key in defaults:
            if key in secret:
                defaults[key] = secret[key]
    return defaults


def build_database_url(settings: Settings) -> str:
    """Build the Postgres connection URL from settings."""
    params = resolve_db_settings(settings)
    return (
        f"postgresql+psycopg2://{params['username']}:{params['password']}"
        f"@{params['host']}:{params['port']}/{params['dbname']}"
    )


def build_engine(settings: Settings) -> Engine:
    """Create and return a SQLAlchemy engine."""
    return create_engine(build_database_url(settings))


def ensure_table(engine: Engine) -> None:
    """Create the target table if it does not already exist."""
    UniversityChapter.metadata.create_all(engine)
    logger.debug('University Chapter table created or already exists')


def load_chapters(
    session: Session, rows: list[ChapterRow], batch_timestamp: datetime
) -> None:
    """Apply SCD2 upserts for the supplied rows."""
    now = batch_timestamp
    chapter_ids = [row.chapter_id for row in rows]

    current_rows = {
        row.chapter_id: row
        for row in session.scalars(
            select(UniversityChapter)
            .where(UniversityChapter.chapter_id.in_(chapter_ids))
            .where(UniversityChapter.is_current.is_(True))
        )
    }

    for row in rows:
        existing = current_rows.get(row.chapter_id)
        new_hash = hash_row(row)

        if existing is None:
            logger.debug('new row')
            new_row = UniversityChapter(
                chapter_id=row.chapter_id,
                chapter_name=row.chapter_name,
                city=row.city,
                state=row.state,
                coordinates=row.coordinates,
                row_hash=new_hash,
                valid_from=now,
                valid_to=None,
                is_current=True,
            )
            session.add(new_row)
            current_rows[row.chapter_id] = new_row
        elif existing.row_hash != new_hash:
            logger.debug('existing row needs updating')
            existing.valid_to = now
            existing.is_current = False
            new_row = UniversityChapter(
                chapter_id=row.chapter_id,
                chapter_name=row.chapter_name,
                city=row.city,
                state=row.state,
                coordinates=row.coordinates,
                row_hash=new_hash,
                valid_from=now,
                valid_to=None,
                is_current=True,
            )
            session.add(new_row)
            current_rows[row.chapter_id] = new_row

    try:
        session.commit()
    except Exception as exc:
        session.rollback()
        raise LoadError(f"Failed to load chapters: {exc}") from exc
