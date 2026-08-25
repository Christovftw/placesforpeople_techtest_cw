"""Tests for etl/transform.py."""

import pytest

from etl.exceptions import TransformationError
from etl.models import ChapterRow
from etl.transform import hash_row, normalise_features


class TestNormaliseFeatures:
    """Tests for normalise_features."""

    def test_normalise_features_returns_filtered_rows(self, sample_features):
        rows = normalise_features(sample_features, ["CA"])
        assert len(rows) == 1
        assert rows[0].chapter_id == "CA-001"
        assert rows[0].chapter_name == "Duck State University"
        assert rows[0].city == "Sacramento"
        assert rows[0].state == "CA"
        assert rows[0].coordinates == "POINT(-121.4944 38.5816)"

    def test_normalise_features_lowercases_state(self):
        raw = {
            "features": [
                {
                    "attributes": {
                        "ChapterID": "CA-001",
                        "University_Chapter": "Duck State",
                        "City": "Sacramento",
                        "State": "ca",
                    },
                    "geometry": {"x": 1.0, "y": 2.0},
                }
            ]
        }
        rows = normalise_features(raw, ["CA"])
        assert rows[0].state == "CA"

    def test_normalise_features_raises_on_missing_field(self):
        raw = {
            "features": [
                {
                    "attributes": {
                        "University_Chapter": "Duck State",
                        "City": "Sacramento",
                        "State": "CA",
                    },
                    "geometry": {"x": 1.0, "y": 2.0},
                }
            ]
        }
        with pytest.raises(TransformationError, match="Missing expected field"):
            normalise_features(raw, ["CA"])

    def test_normalise_features_raises_on_missing_geometry(self):
        raw = {
            "features": [
                {
                    "attributes": {
                        "ChapterID": "CA-001",
                        "University_Chapter": "Duck State",
                        "City": "Sacramento",
                        "State": "CA",
                    }
                }
            ]
        }
        with pytest.raises(TransformationError, match="Missing expected field"):
            normalise_features(raw, ["CA"])

    @pytest.mark.parametrize("geometry", [{"x": 1.0}, {"y": 2.0}])
    def test_normalise_features_raises_on_missing_coordinate(self, geometry):
        raw = {
            "features": [
                {
                    "attributes": {
                        "ChapterID": "CA-001",
                        "University_Chapter": "Duck State",
                        "City": "Sacramento",
                        "State": "CA",
                    },
                    "geometry": geometry,
                }
            ]
        }
        with pytest.raises(TransformationError, match="Missing expected field"):
            normalise_features(raw, ["CA"])

    def test_normalise_features_returns_empty_list_for_empty_input(self):
        raw = {"features": []}
        rows = normalise_features(raw, ["CA"])
        assert rows == []

    def test_normalise_features_strips_whitespace(self):
        raw = {
            "features": [
                {
                    "attributes": {
                        "ChapterID": " CA-001 ",
                        "University_Chapter": " Duck State ",
                        "City": " Sacramento ",
                        "State": " CA ",
                    },
                    "geometry": {"x": 1.0, "y": 2.0},
                }
            ]
        }
        rows = normalise_features(raw, ["CA"])
        assert rows[0].chapter_id == "CA-001"
        assert rows[0].chapter_name == "Duck State"
        assert rows[0].city == "Sacramento"
        assert rows[0].state == "CA"

    def test_normalise_features_filters_non_target_states(self):
        raw = {
            "features": [
                {
                    "attributes": {
                        "ChapterID": "CA-001",
                        "University_Chapter": "Duck State",
                        "City": "Sacramento",
                        "State": "CA",
                    },
                    "geometry": {"x": 1.0, "y": 2.0},
                },
                {
                    "attributes": {
                        "ChapterID": "NY-001",
                        "University_Chapter": "New York Duck",
                        "City": "Albany",
                        "State": "NY",
                    },
                    "geometry": {"x": 3.0, "y": 4.0},
                },
            ]
        }
        rows = normalise_features(raw, ["CA"])
        assert len(rows) == 1
        assert rows[0].chapter_id == "CA-001"


class TestHashRow:
    """Tests for hash_row."""

    def test_hash_row_returns_same_hash_for_identical_rows(self):
        row = ChapterRow(
            chapter_id="CA-001",
            chapter_name="Duck State",
            city="Sacramento",
            state="CA",
            coordinates="POINT(-121.4944 38.5816)",
        )
        assert hash_row(row) == hash_row(row)

    def test_hash_row_returns_different_hash_for_different_rows(self):
        row1 = ChapterRow(
            chapter_id="CA-001",
            chapter_name="Duck State",
            city="Sacramento",
            state="CA",
            coordinates="POINT(-121.4944 38.5816)",
        )
        row2 = ChapterRow(
            chapter_id="CA-001",
            chapter_name="Duck State Updated",
            city="Sacramento",
            state="CA",
            coordinates="POINT(-121.4944 38.5816)",
        )
        assert hash_row(row1) != hash_row(row2)

    def test_hash_row_is_case_insensitive(self):
        row1 = ChapterRow(
            chapter_id="CA-001",
            chapter_name="Duck State",
            city="Sacramento",
            state="CA",
            coordinates="POINT(-121.4944 38.5816)",
        )
        row2 = ChapterRow(
            chapter_id="CA-001",
            chapter_name="duck state",
            city="sacramento",
            state="ca",
            coordinates="point(-121.4944 38.5816)",
        )
        assert hash_row(row1) == hash_row(row2)

    def test_hash_row_handles_unicode(self):
        row = ChapterRow(
            chapter_id="CA-001",
            chapter_name="Université des Canards",
            city="Sacramento",
            state="CA",
            coordinates="POINT(-121.4944 38.5816)",
        )
        result = hash_row(row)
        assert isinstance(result, str)
        assert len(result) == 32
