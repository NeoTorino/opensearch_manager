"""CSRF protection, template helpers, and error pages."""

from __future__ import annotations

import hmac
import secrets

from flask import Flask, abort, render_template, request, session

from config import INDEXES
from formatting import format_date_input, format_value


def register_hooks(app: Flask) -> None:

    # -----------------------------------------------------------------
    # CSRF protection
    # -----------------------------------------------------------------

    def csrf_token() -> str:
        token = session.get("_csrf_token")

        if not token:
            token = secrets.token_urlsafe(32)
            session["_csrf_token"] = token

        return token

    @app.context_processor
    def inject_csrf_token():
        return {"csrf_token": csrf_token}

    @app.before_request
    def protect_post_requests():
        if request.method == "POST":
            expected = session.get("_csrf_token", "")
            submitted = request.form.get("csrf_token", "")

            if (
                not expected
                or not submitted
                or not hmac.compare_digest(expected, submitted)
            ):
                abort(
                    400,
                    description=(
                        "The form security token is missing or invalid. "
                        "Reload the page and try again."
                    ),
                )

    # -----------------------------------------------------------------
    # Template filters and global variables
    # -----------------------------------------------------------------

    @app.template_filter("display_value")
    def display_value(value):
        return format_value(value)

    @app.template_filter("date_input")
    def date_input(value):
        return format_date_input(value)

    @app.context_processor
    def inject_globals():
        view_args = request.view_args or {}
        active_index = view_args.get("index_name", "orgs")

        if active_index not in INDEXES:
            active_index = "orgs"

        return {
            "indexes": INDEXES,
            "active_index": active_index,
        }

    # -----------------------------------------------------------------
    # Error pages
    # -----------------------------------------------------------------

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("404.html"), 404