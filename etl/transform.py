"""Transform raw ArcGIS features into validated rows and hashes."""

import hashlib
import json

from etl.exceptions import TransformationError
from etl.models import ChapterRow


def normalise_features(raw: dict, target_states: list[str]) -> list[ChapterRow]:
    """Convert raw ArcGIS features into validated ChapterRow objects."""
    rows = []

    for feature in raw.get("features", []):
        attributes = feature.get("attributes", {})
        geometry = feature.get("geometry", {})

        try:
            chapter_id = str(attributes["ChapterID"]).strip()
            chapter_name = str(attributes["University_Chapter"]).strip()
            city = str(attributes["City"]).strip()
            state = str(attributes["State"]).strip().upper()
            longitude = geometry["x"]
            latitude = geometry["y"]
        except KeyError as exc:
            raise TransformationError(f"Missing expected field or geometry: {exc}") from exc

        if state not in target_states:
            continue

        rows.append(
            ChapterRow(
                chapter_id=chapter_id,
                chapter_name=chapter_name,
                city=city,
                state=state,
                coordinates=f"POINT({longitude} {latitude})",
            )
        )

    return rows


def hash_row(row: ChapterRow) -> str:
    """Return a lower-cased MD5 hash of the business attributes."""
    payload = {
        "chapter_id": row.chapter_id.lower(),
        "chapter_name": row.chapter_name.lower(),
        "city": row.city.lower(),
        "state": row.state.lower(),
        "coordinates": row.coordinates.lower(),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.md5(canonical.encode("utf-8")).hexdigest()
