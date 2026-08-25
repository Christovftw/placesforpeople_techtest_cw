"""Tests for etl/models.py."""

import pytest
from pydantic import ValidationError

from etl.models import ChapterRow


class TestChapterRow:
    """Tests for the ChapterRow Pydantic model."""

    def test_chapter_row_accepts_valid_data(self):
        row = ChapterRow(
            chapter_id="CA-001",
            chapter_name="Duck State University",
            city="Sacramento",
            state="CA",
            coordinates="POINT(-121.4944 38.5816)",
        )
        assert row.chapter_id == "CA-001"
        assert row.chapter_name == "Duck State University"
        assert row.city == "Sacramento"
        assert row.state == "CA"
        assert row.coordinates == "POINT(-121.4944 38.5816)"

    def test_chapter_row_rejects_missing_field(self):
        with pytest.raises(ValidationError):
            ChapterRow(
                chapter_id="CA-001",
                chapter_name="Duck State University",
                city="Sacramento",
                state="CA",
                # missing coordinates
            )

    def test_chapter_row_rejects_wrong_type(self):
        with pytest.raises(ValidationError):
            ChapterRow(
                chapter_id="CA-001",
                chapter_name="Duck State University",
                city="Sacramento",
                state="CA",
                coordinates=12345,  # should be str
            )
