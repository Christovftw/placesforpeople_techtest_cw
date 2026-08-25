"""Tests for etl/extract.py."""

import pytest
import responses
from requests.exceptions import ConnectionError, HTTPError

from etl.exceptions import ExtractionError
from etl.extract import _fetch_page, fetch_all_chapters, fetch_page

BASE_URL = "https://example.com/chapters"
QUERY_URL = f"{BASE_URL}/query"


class TestFetchPagePrivate:
    """Tests for the low-level _fetch_page helper."""

    @responses.activate
    def test_fetch_page_returns_json(self):
        responses.get(QUERY_URL, json={"features": []}, status=200)
        data = _fetch_page(QUERY_URL, {}, 30)
        assert data == {"features": []}

    @responses.activate
    def test_fetch_page_retries_then_succeeds(self):
        responses.get(QUERY_URL, body=ConnectionError("network down"))
        responses.get(QUERY_URL, json={"features": []}, status=200)
        data = _fetch_page(QUERY_URL, {}, 30)
        assert data == {"features": []}
        assert len(responses.calls) == 2

    @responses.activate
    def test_fetch_page_raises_after_exhausted_retries(self):
        for _ in range(3):
            responses.get(QUERY_URL, body=ConnectionError("network down"))
        with pytest.raises(ConnectionError):
            _fetch_page(QUERY_URL, {}, 30)
        assert len(responses.calls) == 3

    @responses.activate
    def test_fetch_page_raises_extraction_error_on_non_json_response(self):
        responses.get(QUERY_URL, body="not json", status=200)
        with pytest.raises(ExtractionError, match="Non-JSON response"):
            _fetch_page(QUERY_URL, {}, 30)

    @responses.activate
    def test_fetch_page_does_not_retry_4xx(self):
        responses.get(QUERY_URL, json={"error": "not found"}, status=404)
        with pytest.raises(HTTPError):
            _fetch_page(QUERY_URL, {}, 30)
        assert len(responses.calls) == 1

    @responses.activate
    def test_fetch_page_retries_5xx_then_fails(self):
        for _ in range(3):
            responses.get(QUERY_URL, status=500)
        with pytest.raises(HTTPError):
            _fetch_page(QUERY_URL, {}, 30)
        assert len(responses.calls) == 3

    @responses.activate
    def test_retry_logs_warning(self, loguru_capture):
        responses.get(QUERY_URL, body=ConnectionError("network down"))
        responses.get(QUERY_URL, json={"features": []}, status=200)
        _fetch_page(QUERY_URL, {}, 30)
        log_output = loguru_capture.getvalue()
        assert "Retrying _fetch_page" in log_output
        assert "network down" in log_output


class TestFetchPage:
    """Tests for the public fetch_page function."""

    @responses.activate
    def test_fetch_page_returns_features(self):
        responses.get(
            QUERY_URL,
            json={
                "features": [
                    {
                        "attributes": {
                            "ChapterID": "CA-001",
                            "University_Chapter": "Duck State",
                            "City": "Sacramento",
                            "State": "CA",
                        },
                        "geometry": {"x": 1.0, "y": 2.0},
                    }
                ]
            },
            status=200,
        )
        data = fetch_page(BASE_URL, ["CA"], 0, 1000, 30)
        assert len(data["features"]) == 1
        assert data["features"][0]["attributes"]["ChapterID"] == "CA-001"

    @responses.activate
    def test_fetch_page_raises_on_arcgis_error(self):
        responses.get(QUERY_URL, json={"error": {"code": 400, "message": "bad"}}, status=200)
        with pytest.raises(ExtractionError, match="ArcGIS API error"):
            fetch_page(BASE_URL, ["CA"], 0, 1000, 30)

    @responses.activate
    def test_fetch_page_raises_after_retries_exhausted(self):
        for _ in range(3):
            responses.get(QUERY_URL, body=ConnectionError("network down"))
        with pytest.raises(ExtractionError, match="Failed to fetch page"):
            fetch_page(BASE_URL, ["CA"], 0, 1000, 30)

    @responses.activate
    def test_fetch_page_builds_multiple_states_where_clause(self):
        responses.get(QUERY_URL, json={"features": []}, status=200)
        fetch_page(BASE_URL, ["CA", "OR"], 0, 1000, 30)
        request = responses.calls[0].request
        assert "State+IN+%28%27CA%27%2C%27OR%27%29" in request.url

    @responses.activate
    def test_fetch_page_with_empty_states(self):
        responses.get(QUERY_URL, json={"features": []}, status=200)
        data = fetch_page(BASE_URL, [], 0, 1000, 30)
        request = responses.calls[0].request
        assert "State+IN+%28%29" in request.url
        assert data == {"features": []}


class TestFetchAllChapters:
    """Tests for fetch_all_chapters pagination."""

    @responses.activate
    def test_fetch_all_chapters_merges_pages(self):
        responses.get(
            QUERY_URL,
            json={
                "features": [
                    {
                        "attributes": {
                            "ChapterID": "CA-001",
                            "University_Chapter": "A",
                            "City": "B",
                            "State": "CA",
                        },
                        "geometry": {"x": 1.0, "y": 2.0},
                    }
                ]
            },
            status=200,
        )
        responses.get(
            QUERY_URL,
            json={
                "features": [
                    {
                        "attributes": {
                            "ChapterID": "CA-002",
                            "University_Chapter": "C",
                            "City": "D",
                            "State": "CA",
                        },
                        "geometry": {"x": 3.0, "y": 4.0},
                    }
                ]
            },
            status=200,
        )
        responses.get(QUERY_URL, json={"features": []}, status=200)

        data = fetch_all_chapters(BASE_URL, ["CA"], 1, 30)
        assert len(data["features"]) == 2
        assert data["features"][0]["attributes"]["ChapterID"] == "CA-001"
        assert data["features"][1]["attributes"]["ChapterID"] == "CA-002"
        assert len(responses.calls) == 3

    @responses.activate
    def test_fetch_all_chapters_returns_empty_when_first_page_empty(self):
        responses.get(QUERY_URL, json={"features": []}, status=200)
        data = fetch_all_chapters(BASE_URL, ["CA"], 1000, 30)
        assert data == {"features": []}
        assert len(responses.calls) == 1

    @responses.activate
    def test_fetch_all_chapters_propagates_error(self):
        for _ in range(3):
            responses.get(QUERY_URL, body=ConnectionError("network down"))
        with pytest.raises(ExtractionError):
            fetch_all_chapters(BASE_URL, ["CA"], 1000, 30)
