"""Form layout: field order, grouping, labels and column widths."""

from __future__ import annotations

from typing import Any

from config import SINGLE_LINE_FIELDS, TEXTAREA_FIELDS


# Order: mandatory fields first (name, URLs, source, active/excluded,
# dates), optional details last, description at the very end.
# "status" attaches a read-only HTTP status box to a URL field.

ORG_FORM_SECTIONS = [
    {
        "title": "Organisation",
        "fields": [
            {"name": "name", "label": "Name",
             "cols": "col-12 col-md-8 col-lg-6"},
        ],
    },
    {
        "title": "Web addresses",
        "hint": (
            "The HTTP status boxes are filled in by the URL checker "
            "and are read-only."
        ),
        "fields": [
            {"name": "url", "label": "Website URL", "cols": "col-12",
             "status": "status_code_url"},
            {"name": "careers_url", "label": "Careers URL", "cols": "col-12",
             "status": "status_code_careers_url"},
            {"name": "scrape_url", "label": "Scrape URL", "cols": "col-12",
             "status": "status_code_scrape_url"},
            {"name": "source", "label": "Source",
             "cols": "col-12 col-md-6"},
        ],
    },
    {
        "title": "Status",
        "fields": [
            {"name": "active", "label": "Active",
             "cols": "col-12 col-sm-6 col-md-3"},
            {"name": "excluded", "label": "Excluded",
             "cols": "col-12 col-sm-6 col-md-3"},
        ],
    },
    {
        "title": "Dates",
        "fields": [
            {"name": "created", "label": "Created",
             "cols": "col-12 col-md-4"},
            {"name": "updated_at", "label": "Updated",
             "cols": "col-12 col-md-4"},
            {"name": "last_scraped_at", "label": "Last scraped",
             "cols": "col-12 col-md-4"},
        ],
    },
    {
        "title": "Details",
        "fields": [
            {"name": "country", "label": "Country",
             "cols": "col-12 col-md-4"},
            {"name": "country_code", "label": "Country code",
             "cols": "col-12 col-md-4"},
            {"name": "jobs_posted", "label": "Jobs posted",
             "cols": "col-12 col-md-4"},
            {"name": "comments", "label": "Comments", "cols": "col-12"},
            {"name": "description", "label": "Description",
             "cols": "col-12"},
        ],
    },
]


FORM_LAYOUTS = {
    "orgs": ORG_FORM_SECTIONS,
}


def default_cols(field_name: str, spec: dict[str, Any]) -> str:
    wide = (
        field_name in TEXTAREA_FIELDS
        or (
            spec.get("type") == "text"
            and field_name not in SINGLE_LINE_FIELDS
        )
    )

    return "col-12" if wide else "col-12 col-md-6"


def build_form_sections(
    index_name: str,
    properties: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Return the form sections for an index.

    Indexes without a layout get one untitled section in mapping order.
    Mapped fields missing from a layout are appended under "Other".
    """

    layout = FORM_LAYOUTS.get(index_name)

    if not layout:
        return [{
            "title": None,
            "hint": None,
            "fields": [
                {
                    "name": name,
                    "label": None,
                    "cols": default_cols(name, spec),
                    "status": None,
                }
                for name, spec in properties.items()
            ],
        }]

    placed: set[str] = set()
    sections = []

    for section in layout:
        fields = []

        for entry in section["fields"]:
            name = entry["name"]

            if name not in properties:
                continue

            status = entry.get("status")

            # Degrade gracefully if the mapping has not been updated yet.
            if status not in properties:
                status = None

            fields.append({
                "name": name,
                "label": entry.get("label"),
                "cols": entry.get("cols") or default_cols(name, properties[name]),
                "status": status,
            })

            placed.add(name)

            if status:
                placed.add(status)

        if fields:
            sections.append({
                "title": section.get("title"),
                "hint": section.get("hint"),
                "fields": fields,
            })

    leftovers = [name for name in properties if name not in placed]

    if leftovers:
        sections.append({
            "title": "Other",
            "hint": None,
            "fields": [
                {
                    "name": name,
                    "label": None,
                    "cols": default_cols(name, properties[name]),
                    "status": None,
                }
                for name in leftovers
            ],
        })

    return sections