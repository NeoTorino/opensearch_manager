"""Value formatting helpers for display and form inputs."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any


def format_value(value: Any) -> str:

    if value is None:
        return ""

    if isinstance(value, bool):
        return "Yes" if value else "No"

    if isinstance(value, list):
        return ", ".join(str(item) for item in value)

    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)

    return str(value)


def format_date_input(value: Any) -> str:
    """
    Convert existing OpenSearch date values into YYYY-MM-DD.

    This also handles documents that previously contained
    full ISO-8601 timestamps or epoch milliseconds.
    """

    if value is None or value == "":
        return ""

    if isinstance(value, datetime):
        return value.date().isoformat()

    if isinstance(value, date):
        return value.isoformat()

    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(
                value / 1000,
                tz=timezone.utc,
            ).date().isoformat()
        except (ValueError, OSError, OverflowError):
            return str(value)

    raw = str(value).strip()

    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.date().isoformat()

    except ValueError:
        try:
            return date.fromisoformat(raw).isoformat()
        except ValueError:
            return raw


def format_field_value(
    field_name: str,
    value: Any,
    properties: dict[str, Any],
) -> str:

    field_type = properties.get(field_name, {}).get("type")

    if field_type == "date":
        return format_date_input(value)

    return format_value(value)