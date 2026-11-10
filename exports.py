"""CSV backup export."""

from __future__ import annotations

import csv
import io
import json
import logging
from typing import Any
from urllib.parse import quote

from config import load_mapping
from opensearch_client import opensearch_json, opensearch_request

logger = logging.getLogger(__name__)


def csv_cell(value: Any) -> Any:
    """
    Convert values into CSV-compatible representations.

    Lists and dictionaries are preserved as JSON strings.
    """

    if value is None:
        return ""

    if isinstance(value, bool):
        return "true" if value else "false"

    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)

    return value


def export_index_csv(index_name: str) -> str:
    """
    Export every document in an index using the Scroll API.

    The export includes the OpenSearch document ID and every
    field defined in the index mapping.
    """

    properties = load_mapping(index_name)
    field_names = list(properties.keys())

    output = io.StringIO(newline="")
    writer = csv.writer(output)

    # Include _id so that the original document IDs are preserved.
    writer.writerow(["_id", *field_names])

    index_path = quote(index_name, safe="")
    scroll_id = None

    try:
        response = opensearch_json(
            "POST",
            f"/{index_path}/_search",
            params={"scroll": "2m"},
            body={
                "size": 1000,
                "sort": ["_doc"],
                "query": {"match_all": {}},
            },
        )

        scroll_id = response.get("_scroll_id")
        hits = response.get("hits", {}).get("hits", [])

        while hits:

            for hit in hits:
                source = hit.get("_source", {})
                row = [hit.get("_id", "")]

                for field_name in field_names:
                    row.append(csv_cell(source.get(field_name)))

                writer.writerow(row)

            if not scroll_id:
                break

            response = opensearch_json(
                "POST",
                "/_search/scroll",
                body={"scroll": "2m", "scroll_id": scroll_id},
            )

            scroll_id = response.get("_scroll_id", scroll_id)
            hits = response.get("hits", {}).get("hits", [])

    finally:

        # Release the OpenSearch scroll context.

        if scroll_id:
            try:
                opensearch_request(
                    "DELETE",
                    "/_search/scroll",
                    body={"scroll_id": [scroll_id]},
                )
            except Exception:
                logger.warning(
                    "Could not clear the CSV export scroll context."
                )

    return output.getvalue()