"""Document building, validation, organisation sources, and search."""

from __future__ import annotations

from datetime import date
from math import ceil
from typing import Any
from urllib.parse import quote

from config import (
    INDEXES,
    MULTI_VALUE_FIELDS,
    ORG_REQUIRED_FIELDS,
    load_mapping,
)
from formatting import format_field_value
from opensearch_client import opensearch_json


# ---------------------------------------------------------------------
# Document processing
# ---------------------------------------------------------------------

def parse_field_value(
    field_name: str,
    field_mapping: dict[str, Any],
    raw: str,
    form=None,
) -> Any:

    field_type = field_mapping.get("type")

    if field_name in MULTI_VALUE_FIELDS:
        values = [
            item.strip()
            for item in raw.splitlines()
            if item.strip()
        ]
        return values if values else None

    if raw == "":
        return None

    if field_name == "source":
        if raw == "__new_source__":
            raw = form.get("source_new", "") if form is not None else ""
        return raw.strip()

    if field_type == "boolean":
        lowered = raw.lower()

        if lowered == "true":
            return True

        if lowered == "false":
            return False

        raise ValueError(f"{field_name}: choose Yes or No.")

    if field_type in {"integer", "long", "short", "byte"}:
        try:
            return int(raw)
        except ValueError as exc:
            raise ValueError(
                f"{field_name}: enter a whole number."
            ) from exc

    if field_type in {"float", "double"}:
        try:
            return float(raw)
        except ValueError as exc:
            raise ValueError(
                f"{field_name}: enter a valid number."
            ) from exc

    if field_type == "date":
        raw = raw.strip()

        try:
            parsed = date.fromisoformat(raw)
        except ValueError as exc:
            raise ValueError(
                f"{field_name}: enter a date in YYYY-MM-DD format."
            ) from exc

        if parsed.isoformat() != raw:
            raise ValueError(
                f"{field_name}: use YYYY-MM-DD (for example, 2026-11-09)."
            )

        return parsed.isoformat()

    return raw


def build_document(
    index_name: str,
    form,
    is_new: bool,
) -> dict[str, Any]:

    properties = load_mapping(index_name)
    document: dict[str, Any] = {}

    for field_name, field_mapping in properties.items():

        raw = form.get(field_name, "")

        value = parse_field_value(field_name, field_mapping, raw, form)

        if is_new and (
            raw == ""
            or (field_name in MULTI_VALUE_FIELDS and value is None)
        ):
            continue

        # When editing, blank fields are stored as null.
        # This clears their previous values.

        if value is not None or not is_new:
            document[field_name] = value

    return document


def validate_required_fields(
    index_name: str,
    document: dict[str, Any],
) -> None:

    if index_name != "orgs":
        return

    missing = []

    for field_name in sorted(ORG_REQUIRED_FIELDS):
        value = document.get(field_name)

        # False is a valid boolean value.

        if value is None or (
            isinstance(value, str) and not value.strip()
        ):
            missing.append(field_name)

    if missing:
        raise ValueError(
            "The following organisation fields are mandatory: "
            + ", ".join(missing)
        )


# ---------------------------------------------------------------------
# Organisation source options
# ---------------------------------------------------------------------

def get_org_sources() -> list[str]:
    """Retrieve distinct source values from the Organisations index."""

    response = opensearch_json(
        "POST",
        "/orgs/_search",
        body={
            "size": 0,
            "aggs": {
                "source_values": {
                    "terms": {
                        "field": "source",
                        "size": 1000,
                        "order": {"_key": "asc"},
                    },
                },
            },
        },
    )

    buckets = (
        response
        .get("aggregations", {})
        .get("source_values", {})
        .get("buckets", [])
    )

    sources = {
        str(bucket["key"]).strip()
        for bucket in buckets
        if bucket.get("key") is not None
        and str(bucket["key"]).strip()
    }

    return sorted(sources, key=str.casefold)


# ---------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------

def search_documents(
    index_name: str,
    query: str,
    page: int,
    page_size: int = 1000,
):

    properties = load_mapping(index_name)

    if query.strip():

        # Search across all mapped fields, not just the visible columns,
        # including sub-fields such as name.keyword. Lenient mode allows
        # different field types to be searched without failing.

        searchable_fields = []

        for field_name, spec in properties.items():
            searchable_fields.append(field_name)

            for subfield in spec.get("fields", {}):
                searchable_fields.append(f"{field_name}.{subfield}")

        search_query = {
            "simple_query_string": {
                "query": query.strip(),
                "fields": searchable_fields,
                "default_operator": "and",
                "lenient": True,
            },
        }

    else:
        search_query = {"match_all": {}}

    index_path = quote(index_name, safe="")

    response = opensearch_json(
        "POST",
        f"/{index_path}/_search",
        body={
            "from": (page - 1) * page_size,
            "size": page_size,
            "track_total_hits": True,
            "query": search_query,
            "sort": [{"_doc": "asc"}],
        },
    )

    total_info = response["hits"]["total"]

    total = (
        total_info["value"]
        if isinstance(total_info, dict)
        else total_info
    )

    pages = max(1, ceil(total / page_size))

    records = []

    for hit in response["hits"]["hits"]:
        source = hit.get("_source", {})

        records.append({
            "id": hit["_id"],
            "source": source,
            "values": [
                format_field_value(col, source.get(col), properties)
                for col in INDEXES[index_name]["columns"]
            ],
        })

    return records, total, pages