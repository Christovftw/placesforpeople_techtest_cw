"""Extract data from the Ducks Unlimited ArcGIS API."""

import requests
from loguru import logger
from requests.exceptions import HTTPError, JSONDecodeError, RequestException
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from etl.exceptions import ExtractionError


def _log_retry(retry_state: RetryCallState) -> None:
    """Log a warning before each retry attempt."""
    exception = retry_state.outcome.exception()
    logger.warning(
        "Retrying _fetch_page after {} failed attempt(s): {}",
        retry_state.attempt_number,
        exception,
    )


def _should_retry(exc: Exception) -> bool:
    """Return True if the request should be retried."""
    if isinstance(exc, HTTPError):
        return exc.response.status_code >= 500
    return isinstance(exc, RequestException)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception(_should_retry),
    reraise=True,
    before_sleep=_log_retry,
)
def _fetch_page(url: str, params: dict, timeout: int) -> dict:
    """Send a single GET request to the ArcGIS API."""
    try:
        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except JSONDecodeError as exc:
        raise ExtractionError(f"Non-JSON response from API: {exc}") from exc


def fetch_page(
    url: str, states: list[str], offset: int, page_size: int, timeout: int
) -> dict:
    """Fetch one page of chapter features from the ArcGIS API."""
    state_list = ",".join(f"'{state}'" for state in states)
    params = {
        "where": f"State IN ({state_list})",
        "outFields": "ChapterID,University_Chapter,City,State",
        "outSR": "4326",
        "returnGeometry": "true",
        "f": "json",
        "resultOffset": offset,
        "resultRecordCount": page_size,
    }

    try:
        data = _fetch_page(f"{url}/query", params, timeout)
    except RequestException as exc:
        raise ExtractionError(f"Failed to fetch page at offset {offset}: {exc}") from exc

    if data.get("error"):
        raise ExtractionError(f"ArcGIS API error: {data['error']}")

    return data


def fetch_all_chapters(
    url: str, states: list[str], page_size: int, timeout: int
) -> dict:
    """Fetch all pages of chapter features and merge them into one response."""
    features = []
    offset = 0

    while True:
        page = fetch_page(url, states, offset, page_size, timeout)
        page_features = page.get("features", [])

        if not page_features:
            break

        features.extend(page_features)

        if len(page_features) < page_size:
            break

        offset += page_size

    return {"features": features}
