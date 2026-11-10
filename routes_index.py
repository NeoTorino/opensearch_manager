"""Home, index listing, and CSV backup routes."""

from __future__ import annotations

from datetime import date

from flask import (
    Flask,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from config import INDEXES
from documents import search_documents
from exports import export_index_csv
from opensearch_client import friendly_opensearch_error


def register(app: Flask) -> None:

    @app.route("/")
    def home():
        return redirect(url_for("index_view", index_name="orgs"))

    @app.route("/index/<index_name>")
    def index_view(index_name: str):

        if index_name not in INDEXES:
            abort(404)

        query = request.args.get("q", "").strip()

        try:
            page = max(1, int(request.args.get("page", "1")))
        except ValueError:
            page = 1

        try:
            records, total, pages = search_documents(
                index_name,
                query,
                page,
            )

        except Exception as exc:
            app.logger.exception(
                "Failed to retrieve index %s",
                index_name,
            )

            flash(
                f"Could not load {index_name}: "
                f"{friendly_opensearch_error(exc)}",
                "danger",
            )

            return render_template(
                "index.html",
                index_name=index_name,
                index_info=INDEXES[index_name],
                columns=INDEXES[index_name]["columns"],
                records=[],
                total=0,
                page=1,
                pages=1,
                query=query,
                connection_error=True,
            )

        if page > pages:
            return redirect(
                url_for(
                    "index_view",
                    index_name=index_name,
                    q=query,
                    page=pages,
                )
            )

        return render_template(
            "index.html",
            index_name=index_name,
            index_info=INDEXES[index_name],
            columns=INDEXES[index_name]["columns"],
            records=records,
            total=total,
            page=page,
            pages=pages,
            query=query,
            connection_error=False,
        )

    @app.route("/index/<index_name>/backup.csv")
    def backup_index(index_name: str):

        if index_name not in INDEXES:
            abort(404)

        try:
            csv_content = export_index_csv(index_name)

            filename = (
                f"{index_name}-backup-{date.today().isoformat()}.csv"
            )

            response = Response(csv_content, mimetype="text/csv")
            response.headers["Content-Disposition"] = (
                f'attachment; filename="{filename}"'
            )
            response.headers["Cache-Control"] = "no-store"

            return response

        except Exception as exc:
            app.logger.exception(
                "CSV backup failed for %s",
                index_name,
            )

            flash(
                "Could not create CSV backup: "
                f"{friendly_opensearch_error(exc)}",
                "danger",
            )

            return redirect(url_for("index_view", index_name=index_name))