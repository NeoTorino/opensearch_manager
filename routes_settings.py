"""Settings route."""

from __future__ import annotations

from urllib.parse import quote

from flask import Flask, flash, render_template, request

from config import INDEXES, load_config, save_config
from opensearch_client import (
    OpenSearchHTTPError,
    friendly_opensearch_error,
    opensearch_json,
    opensearch_request,
)


def register(app: Flask) -> None:

    @app.route("/settings", methods=["GET", "POST"])
    def settings():

        current = load_config()

        if request.method == "POST":

            candidate = current.copy()

            candidate["host"] = request.form.get("host", "").strip()
            candidate["username"] = request.form.get("username", "").strip()
            candidate["ca_certs"] = request.form.get("ca_certs", "").strip()
            candidate["use_ssl"] = request.form.get("use_ssl") == "on"
            candidate["verify_certs"] = (
                request.form.get("verify_certs") == "on"
            )

            try:
                candidate["port"] = int(request.form.get("port", "9200"))
                candidate["timeout"] = int(request.form.get("timeout", "15"))

                if not candidate["host"]:
                    raise ValueError(
                        "Enter an OpenSearch IP address or hostname."
                    )

                if not 1 <= candidate["port"] <= 65535:
                    raise ValueError("Port must be between 1 and 65535.")

                if not 1 <= candidate["timeout"] <= 300:
                    raise ValueError(
                        "Timeout must be between 1 and 300 seconds."
                    )

                if request.form.get("clear_password") == "on":
                    candidate["password"] = ""

                elif request.form.get("password", ""):
                    candidate["password"] = request.form["password"]

                action = request.form.get("action", "save")

                if action == "test":

                    info = opensearch_json("GET", "/", config=candidate)

                    cluster = info.get("cluster_name", "OpenSearch")
                    version = info.get("version", {}).get(
                        "number",
                        "unknown",
                    )

                    missing = []

                    for name in INDEXES:
                        try:
                            opensearch_request(
                                "HEAD",
                                f"/{quote(name, safe='')}",
                                config=candidate,
                            )

                        except OpenSearchHTTPError as exc:
                            if exc.status_code == 404:
                                missing.append(name)
                            else:
                                raise

                    message = (
                        f"Connected to {cluster} (version {version})."
                    )

                    if missing:
                        message += (
                            " Missing indexes: " + ", ".join(missing) + "."
                        )

                    flash(
                        message,
                        "success" if not missing else "warning",
                    )

                else:
                    save_config(candidate)
                    flash("Settings saved.", "success")
                    current = candidate

            except Exception as exc:
                flash(
                    "Settings error: "
                    f"{friendly_opensearch_error(exc)}",
                    "danger",
                )

            if request.form.get("action") == "test":
                current = candidate

        return render_template(
            "settings.html",
            config=current,
            password_is_set=bool(current.get("password")),
        )