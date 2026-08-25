"""Pydantic and SQLAlchemy models for the pipeline."""

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import Boolean, DateTime, Index, Integer, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""


class ChapterRow(BaseModel):
    """Validated business row extracted from the source API."""

    chapter_id: str
    chapter_name: str
    city: str
    state: str
    coordinates: str


class UniversityChapter(Base):
    """Postgres table storing university chapters with SCD2 history."""

    __tablename__ = "university_chapters"
    __table_args__ = (Index("ix_chapter_current", "chapter_id", "is_current"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chapter_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    chapter_name: Mapped[str] = mapped_column(Text, nullable=False)
    city: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    coordinates: Mapped[str] = mapped_column(Text, nullable=False)
    row_hash: Mapped[str] = mapped_column(Text, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    valid_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
