"""Create, edit, and delete document routes."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any
from urllib.parse import quote

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from config import (
    FIELD_ROWS,
    INDEXES,
    MULTI_VALUE_FIELDS,
    ORG_REQUIRED_FIELDS,
    SINGLE_LINE_FIELDS,
    TEXTAREA_FIELDS,
    load_mapping,
)
from documents import (
    build_document,
    get_org_sources,
    validate_required_fields,
)
from form_layout import build_form_sections
from opensearch_client import (
    friendly_opensearch_error,
    opensearch_json,
    opensearch_request,
)


def _form_context(
    index_name: str,
    properties: dict[str, Any],
    values: dict[str, Any],
    *,
    mode: str,
    doc_id: str | None,
    source_options: list[str],
) -> dict[str, Any]:

    return {
        "index_name": index_name,
        "index_info": INDEXES[index_name],
        "properties": properties,
        "sections": build_form_sections(index_name, properties),
        "values": values,
        "mode": mode,
        "doc_id": doc_id,
        "multi_value_fields": MULTI_VALUE_FIELDS,
        "textarea_fields": TEXTAREA_FIELDS,
        "single_line_fields": SINGLE_LINE_FIELDS,
        "field_rows": FIELD_ROWS,
        "required_fields": (
            ORG_REQUIRED_FIELDS if index_name == "orgs" else set()
        ),
        "source_options": source_options,
    }


def register(app: Flask) -> None:

    # -----------------------------------------------------------------
    # Create document
    # -----------------------------------------------------------------

    @app.route("/index/<index_name>/new", methods=["GET", "POST"])
    def create_document(index_name: str):

        if index_name not in INDEXES:
            abort(404)

        properties = load_mapping(index_name)

        source_options: list[str] = []

        if index_name == "orgs":
            try:
                source_options = get_org_sources()

            except Exception as exc:
                app.logger.exception(
                    "Could not retrieve organisation sources."
                )

                flash(
                    "Could not load source options: "
                    f"{friendly_opensearch_error(exc)}",
                    "warning",
                )

        today = date.today().isoformat()
        values: dict[str, Any] = {}

        if index_name == "orgs":
            values = {
                "created": today,
                "updated_at": today,
            }

        if request.method == "POST":
            try:
                document = build_document(
                    index_name,
                    request.form,
                    is_new=True,
                )

                validate_required_fields(index_name, document)

                # updated_at is always stamped automatically, so it
                # does not count as user input.
                if not any(key != "updated_at" for key in document):
                    raise ValueError(
                        "Enter at least one field before creating "
                        "the document."
                    )

                document_id = uuid.uuid4().hex
                index_path = quote(index_name, safe="")
                document_path = quote(document_id, safe="")

                opensearch_request(
                    "PUT",
                    f"/{index_path}/_doc/{document_path}",
                    params={"refresh": "wait_for"},
                    body=document,
                )

                flash(
                    f"Document created successfully (ID: {document_id}).",
                    "success",
                )

                return redirect(
                    url_for(
                        "edit_document",
                        index_name=index_name,
                        doc_id=document_id,
                    )
                )

            except Exception as exc:
                flash(
                    "Could not create document: "
                    f"{friendly_opensearch_error(exc)}",
                    "danger",
                )

                values = request.form.to_dict()

        return render_template(
            "document_form.html",
            **_form_context(
                index_name,
                properties,
                values,
                mode="new",
                doc_id=None,
                source_options=source_options,
            ),
        )

    # -----------------------------------------------------------------
    # Edit document
    # -----------------------------------------------------------------

    @app.route(
        "/index/<index_name>/<doc_id>/edit",
        methods=["GET", "POST"],
    )
    def edit_document(index_name: str, doc_id: str):

        if index_name not in INDEXES:
            abort(404)

        properties = load_mapping(index_name)

        index_path = quote(index_name, safe="")
        document_path = quote(doc_id, safe="")

        try:
            response = opensearch_json(
                "GET",
                f"/{index_path}/_doc/{document_path}",
            )
            current_source = response.get("_source", {})

        except Exception as exc:
            flash(
                "Could not retrieve document: "
                f"{friendly_opensearch_error(exc)}",
                "danger",
            )

            return redirect(url_for("index_view", index_name=index_name))

        values = current_source.copy()
        source_options: list[str] = []

        if index_name == "orgs":
            try:
                source_options = get_org_sources()

            except Exception as exc:
                app.logger.exception(
                    "Could not retrieve organisation sources."
                )

                flash(
                    "Could not refresh source options: "
                    f"{friendly_opensearch_error(exc)}",
                    "warning",
                )

            # Keep the existing value available even if it is no
            # longer returned by the aggregation.

            current_source_value = current_source.get("source")

            if (
                current_source_value
                and current_source_value not in source_options
            ):
                source_options.append(current_source_value)

            source_options.sort(key=str.casefold)

        if request.method == "POST":

            if request.form.get("action") == "delete":
                return redirect(
                    url_for(
                        "delete_document",
                        index_name=index_name,
                        doc_id=doc_id,
                    )
                )

            try:
                # current_source lets build_document detect changed
                # URLs (to reset their status codes) and stamps
                # updated_at.
                document = build_document(
                    index_name,
                    request.form,
                    is_new=False,
                    current=current_source,
                )

                validate_required_fields(index_name, document)

                opensearch_request(
                    "PUT",
                    f"/{index_path}/_doc/{document_path}",
                    params={"refresh": "wait_for"},
                    body=document,
                )

                flash("Document updated successfully.", "success")

                return redirect(
                    url_for(
                        "edit_document",
                        index_name=index_name,
                        doc_id=doc_id,
                    )
                )

            except Exception as exc:
                flash(
                    "Could not update document: "
                    f"{friendly_opensearch_error(exc)}",
                    "danger",
                )

                values = request.form.to_dict()

        return render_template(
            "document_form.html",
            **_form_context(
                index_name,
                properties,
                values,
                mode="edit",
                doc_id=doc_id,
                source_options=source_options,
            ),
        )

    # -----------------------------------------------------------------
    # Delete document
    # -----------------------------------------------------------------

    @app.route(
        "/index/<index_name>/<doc_id>/delete",
        methods=["GET", "POST"],
    )
    def delete_document(index_name: str, doc_id: str):

        if index_name not in INDEXES:
            abort(404)

        if request.method == "GET":
            return render_template(
                "confirm_delete.html",
                index_name=index_name,
                index_info=INDEXES[index_name],
                doc_id=doc_id,
            )

        try:
            index_path = quote(index_name, safe="")
            document_path = quote(doc_id, safe="")

            opensearch_request(
                "DELETE",
                f"/{index_path}/_doc/{document_path}",
                params={"refresh": "wait_for"},
            )

            flash(f"Document {doc_id} deleted.", "success")

        except Exception as exc:
            flash(
                "Could not delete document: "
                f"{friendly_opensearch_error(exc)}",
                "danger",
            )

        return redirect(url_for("index_view", index_name=index_name))