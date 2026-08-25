"""Single entry point for the ETL pipeline."""

from datetime import datetime, timezone

from loguru import logger
from typing import Any

from sqlalchemy.orm import Session

from etl.config import Settings
from etl.exceptions import ETLError
from etl.extract import fetch_all_chapters
from etl.load import build_engine, ensure_table, load_chapters
from etl.transform import normalise_features


def lambda_handler(event: dict, context: Any) -> dict:
    """Run the full ETL pipeline and return a status summary."""
    settings = Settings()
    batch_timestamp = datetime.now(timezone.utc)
    request_id = getattr(context, "aws_request_id", None)
    log = logger.bind(request_id=request_id)
    log.info("Starting ETL run")

    try:
        engine = build_engine(settings)
        ensure_table(engine)

        raw = fetch_all_chapters(
            settings.source_url,
            settings.target_states,
            settings.arcgis_page_size,
            settings.request_timeout,
        )
        log.debug('University chapters collected')
        rows = normalise_features(raw, settings.target_states)
        log.debug('University chapters normalised')

        with Session(engine) as session:
            load_chapters(session, rows, batch_timestamp)
        log.debug('University chapters loaded to postgres')
    except ETLError:
        log.exception("ETL run failed")
        raise

    log.info("ETL run complete")
    return {"statusCode": 200, "records_processed": len(rows)}
