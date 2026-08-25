"""Tests for etl/main.py."""

from unittest.mock import MagicMock, patch

import pytest

from etl.exceptions import ExtractionError
from etl.main import lambda_handler


@patch("etl.main.load_chapters")
@patch("etl.main.Session")
@patch("etl.main.normalise_features")
@patch("etl.main.fetch_all_chapters")
@patch("etl.main.ensure_table")
@patch("etl.main.build_engine")
@patch("etl.main.Settings")
def test_lambda_handler_runs_full_pipeline(
    mock_settings_class,
    mock_build_engine,
    mock_ensure_table,
    mock_fetch_all_chapters,
    mock_normalise_features,
    mock_session_class,
    mock_load_chapters,
):
    """Happy-path test that the pipeline calls each stage in order."""
    mock_settings = MagicMock()
    mock_settings.source_url = "http://example.com/arcgis"
    mock_settings.target_states = ["CA"]
    mock_settings.arcgis_page_size = 1000
    mock_settings.request_timeout = 30
    mock_settings_class.return_value = mock_settings

    mock_engine = MagicMock()
    mock_build_engine.return_value = mock_engine

    mock_fetch_all_chapters.return_value = {"features": [{"id": 1}]}
    mock_normalise_features.return_value = []

    result = lambda_handler({}, None)

    assert result == {"statusCode": 200, "records_processed": 0}
    mock_build_engine.assert_called_once_with(mock_settings)
    mock_ensure_table.assert_called_once_with(mock_engine)
    mock_fetch_all_chapters.assert_called_once_with(
        "http://example.com/arcgis", ["CA"], 1000, 30
    )
    mock_normalise_features.assert_called_once_with(
        {"features": [{"id": 1}]}, ["CA"]
    )
    mock_session_class.assert_called_once_with(mock_engine)
    mock_load_chapters.assert_called_once()


@patch("etl.main.logger")
@patch("etl.main.load_chapters")
@patch("etl.main.Session")
@patch("etl.main.normalise_features")
@patch("etl.main.fetch_all_chapters")
@patch("etl.main.ensure_table")
@patch("etl.main.build_engine")
@patch("etl.main.Settings")
def test_lambda_handler_logs_and_raises_on_etl_error(
    mock_settings_class,
    mock_build_engine,
    mock_ensure_table,
    mock_fetch_all_chapters,
    mock_normalise_features,
    mock_session_class,
    mock_load_chapters,
    mock_logger,
):
    """Exception test: ETLError is logged and re-raised via bound logger."""
    mock_settings = MagicMock()
    mock_settings_class.return_value = mock_settings
    mock_fetch_all_chapters.side_effect = ExtractionError("API down")

    with pytest.raises(ExtractionError, match="API down"):
        lambda_handler({}, None)

    mock_logger.bind.assert_called_once_with(request_id=None)
    mock_logger.bind.return_value.exception.assert_called_once_with("ETL run failed")


@patch("etl.main.logger")
@patch("etl.main.load_chapters")
@patch("etl.main.Session")
@patch("etl.main.normalise_features")
@patch("etl.main.fetch_all_chapters")
@patch("etl.main.ensure_table")
@patch("etl.main.build_engine")
@patch("etl.main.Settings")
def test_lambda_handler_binds_aws_request_id(
    mock_settings_class,
    mock_build_engine,
    mock_ensure_table,
    mock_fetch_all_chapters,
    mock_normalise_features,
    mock_session_class,
    mock_load_chapters,
    mock_logger,
):
    """Happy-path test: request ID from Lambda context is bound to logs."""
    mock_settings = MagicMock()
    mock_settings.source_url = "http://example.com/arcgis"
    mock_settings.target_states = ["CA"]
    mock_settings.arcgis_page_size = 1000
    mock_settings.request_timeout = 30
    mock_settings_class.return_value = mock_settings

    mock_context = MagicMock()
    mock_context.aws_request_id = "abc-123"

    mock_fetch_all_chapters.return_value = {"features": []}
    mock_normalise_features.return_value = []

    lambda_handler({}, mock_context)

    mock_logger.bind.assert_called_once_with(request_id="abc-123")
