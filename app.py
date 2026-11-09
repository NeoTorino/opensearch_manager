from __future__ import annotations

import hmac
import json
import os
import secrets
import uuid
from datetime import datetime
from pathlib import Path
from math import ceil
from typing import Any
from urllib.parse import quote

import requests
from flask import (
    Flask, abort, flash, redirect, render_template,
    request, session, url_for
)


BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
CONFIG_FILE = INSTANCE_DIR / "config.json"
MAPPINGS_DIR = BASE_DIR / "mappings"

INSTANCE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)


DEFAULT_CONFIG = {
    "host": "192.168.2.250",
    "port": 9200,
    "username": "admin",
    "password": "",
    "ca_certs": "",
    "use_ssl": True,
    "verify_certs": True,
    "timeout": 15,
    "secret_key": secrets.token_urlsafe(48),
}


INDEXES = {
    "orgs": {
        "title": "Organisations",
        "mapping_file": "orgs_mapping.json",
        "columns": [
            "name",
            "careers_url",
            "scrape_url",
            "source",
            "active",
            "excluded",
            "created",
            "updated_at",
        ],
    },
    "jobs": {
        "title": "Jobs",
        "mapping_file": "jobs_mapping.json",
        "columns": [
            "title",
            "org_id",
            "country",
            "country_code",
            "date_posted",
            "active",
            "salary_min",
            "salary_max",
            "currency",
        ],
    },
}


# Mandatory fields for organisations.
# Names must match mappings/orgs_mapping.json exactly.
ORG_REQUIRED_FIELDS = {
    "name",
    "careers_url",
    "source",
    "active",
    "excluded",
    "created",
    "updated_at",
}


MULTI_VALUE_FIELDS = {"tags", "skills", "language"}

TEXTAREA_FIELDS = {
    "description",
    "summary",
    "address",
    "location",
    "location_2",
    "location_3",
}


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

def save_config(config: dict[str, Any]) -> None:
    INSTANCE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)

    temporary = CONFIG_FILE.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(config, indent=2),
        encoding="utf-8",
    )

    os.replace(temporary, CONFIG_FILE)

    try:
        os.chmod(CONFIG_FILE, 0o600)
        os.chmod(INSTANCE_DIR, 0o700)
    except OSError:
        # Windows does not implement POSIX file permissions.
        pass


def load_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        config = DEFAULT_CONFIG.copy()
        save_config(config)
        return config

    try:
        stored = json.loads(
            CONFIG_FILE.read_text(encoding="utf-8")
        )

        config = DEFAULT_CONFIG.copy()
        config.update(stored)

        return config

    except (OSError, json.JSONDecodeError):
        return DEFAULT_CONFIG.copy()


def load_mapping(index_name: str) -> dict[str, Any]:
    if index_name not in INDEXES:
        abort(404)

    path = MAPPINGS_DIR / INDEXES[index_name]["mapping_file"]

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data["mappings"]["properties"]

    except (OSError, json.JSONDecodeError, KeyError) as exc:
        raise RuntimeError(
            f"Could not load mapping for {index_name}: {exc}"
        ) from exc


# ---------------------------------------------------------------------
# OpenSearch HTTP communication
# ---------------------------------------------------------------------

class OpenSearchHTTPError(RuntimeError):
    """An HTTP error returned by the OpenSearch REST API."""

    def __init__(self, response: requests.Response):
        self.status_code = response.status_code
        self.detail = ""

        try:
            payload = response.json()

            error = (
                payload.get("error", payload)
                if isinstance(payload, dict)
                else payload
            )

            if isinstance(error, dict):
                self.detail = (
                    error.get("reason")
                    or json.dumps(error, ensure_ascii=False)
                )
            else:
                self.detail = str(error)

        except ValueError:
            self.detail = response.text.strip()[:500]

        if not self.detail:
            self.detail = response.reason or "Unknown OpenSearch error"

        super().__init__(
            f"HTTP {self.status_code}: {self.detail}"
        )


def opensearch_request(
    method: str,
    path: str,
    config: dict[str, Any] | None = None,
    *,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> requests.Response:

    """Send an authenticated HTTP request to OpenSearch."""

    cfg = config or load_config()

    host = str(cfg.get("host", "")).strip().rstrip("/")

    if not host:
        raise ValueError(
            "OpenSearch host/IP has not been configured."
        )

    # Accept an accidentally pasted URL scheme, but use the
    # HTTPS checkbox as the authority.
    host = host.removeprefix("https://").removeprefix("http://")

    if not host or "/" in host:
        raise ValueError(
            "Enter only an OpenSearch hostname or IP address, without a path."
        )

    try:
        port = int(cfg.get("port", 9200))
        timeout = int(cfg.get("timeout", 15))

    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Port and timeout must be numbers."
        ) from exc

    if not 1 <= port <= 65535:
        raise ValueError(
            "Port must be between 1 and 65535."
        )

    if timeout < 1:
        raise ValueError(
            "Timeout must be at least 1 second."
        )

    use_ssl = bool(cfg.get("use_ssl", True))

    verify_certs = (
        bool(cfg.get("verify_certs", True))
        if use_ssl
        else False
    )

    verify: bool | str = False

    if verify_certs:
        ca_certs = str(cfg.get("ca_certs", "")).strip()

        if ca_certs:
            cert_path = Path(ca_certs).expanduser()

            if not cert_path.is_absolute():
                cert_path = BASE_DIR / cert_path

            if not cert_path.exists():
                raise ValueError(
                    f"CA certificate path does not exist: {cert_path}"
                )

            verify = str(cert_path)

        else:
            verify = True

    username = str(cfg.get("username", "")).strip()
    password = str(cfg.get("password", ""))

    auth = (username, password) if username else None

    scheme = "https" if use_ssl else "http"

    url = f"{scheme}://{host}:{port}{path}"

    response = requests.request(
        method=method.upper(),
        url=url,
        auth=auth,
        verify=verify,
        timeout=timeout,
        headers={"Accept": "application/json"},
        params=params,
        json=body,
    )

    if response.status_code >= 400:
        raise OpenSearchHTTPError(response)

    return response


def opensearch_json(
    method: str,
    path: str,
    config: dict[str, Any] | None = None,
    *,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:

    response = opensearch_request(
        method,
        path,
        config,
        params=params,
        body=body,
    )

    try:
        return response.json()

    except ValueError as exc:
        raise ValueError(
            "OpenSearch returned a response that was not valid JSON."
        ) from exc


# ---------------------------------------------------------------------
# Document processing
# ---------------------------------------------------------------------

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


def parse_field_value(
    field_name: str,
    field_mapping: dict[str, Any],
    raw: str,
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

    if field_type == "boolean":
        lowered = raw.lower()

        if lowered == "true":
            return True

        if lowered == "false":
            return False

        raise ValueError(
            f"{field_name}: choose Yes or No."
        )

    if field_type == "integer":
        try:
            return int(raw)

        except ValueError as exc:
            raise ValueError(
                f"{field_name}: enter a whole number."
            ) from exc

    if field_type in {
        "float", "double", "long", "short", "byte"
    }:
        try:
            if field_type in {"float", "double"}:
                return float(raw)

            return int(raw)

        except ValueError as exc:
            raise ValueError(
                f"{field_name}: enter a valid number."
            ) from exc

    if field_type == "date":
        try:
            datetime.fromisoformat(
                raw.replace("Z", "+00:00")
            )

        except ValueError as exc:
            raise ValueError(
                f"{field_name}: use YYYY-MM-DD or an ISO-8601 date/time."
            ) from exc

        return raw

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

        value = parse_field_value(
            field_name,
            field_mapping,
            raw,
        )

        if is_new and (
            raw == ""
            or (
                field_name in MULTI_VALUE_FIELDS
                and value is None
            )
        ):
            continue

        # When editing, blank fields are stored as null,
        # clearing their previous values.
        if value is not None or not is_new:
            document[field_name] = value

    return document


def validate_required_fields(
    index_name: str,
    document: dict[str, Any],
) -> None:

    """Enforce mandatory fields before sending data to OpenSearch."""

    if index_name != "orgs":
        return

    missing = []

    for field_name in sorted(ORG_REQUIRED_FIELDS):

        value = document.get(field_name)

        # False is a valid boolean value.
        # Only None or blank strings count as missing.
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

        searchable_fields = [
            name
            for name, spec in properties.items()
            if spec.get("type") in {"text", "keyword"}
            or "fields" in spec
        ]

        search_query = {
            "simple_query_string": {
                "query": query.strip(),
                "fields": searchable_fields,
                "default_operator": "and",
            }
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
                format_value(source.get(col))
                for col in INDEXES[index_name]["columns"]
            ],
        })

    return records, total, pages


# ---------------------------------------------------------------------
# Flask application
# ---------------------------------------------------------------------

app = Flask(__name__)

app.config["SECRET_KEY"] = load_config()["secret_key"]
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


# ---------------------------------------------------------------------
# CSRF protection
# ---------------------------------------------------------------------

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


@app.template_filter("display_value")
def display_value(value):
    return format_value(value)


@app.context_processor
def inject_globals():
    return {"indexes": INDEXES}


# ---------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------

def friendly_opensearch_error(exc: Exception) -> str:

    if isinstance(exc, OpenSearchHTTPError):

        if exc.status_code == 401:
            return (
                "Authentication failed. "
                "Check your OpenSearch username and password in Settings."
            )

        if exc.status_code == 403:
            return (
                "OpenSearch rejected this operation. "
                "Check the user's index permissions."
            )

        if exc.status_code == 404:
            return "The requested document or index was not found."

        return (
            f"OpenSearch returned HTTP {exc.status_code}: "
            f"{exc.detail}"
        )

    if isinstance(exc, requests.exceptions.SSLError):
        return (
            "TLS certificate verification failed. "
            f"Check the CA certificate and hostname: {exc}"
        )

    if isinstance(exc, requests.exceptions.Timeout):
        return (
            f"The connection to OpenSearch timed out: {exc}"
        )

    if isinstance(exc, requests.exceptions.ConnectionError):
        return (
            "Could not connect to OpenSearch. "
            f"Check the host, port and network: {exc}"
        )

    if isinstance(exc, requests.exceptions.RequestException):
        return f"HTTP request failed: {exc}"

    return str(exc)


# ---------------------------------------------------------------------
# Main routes
# ---------------------------------------------------------------------

@app.route("/")
def home():
    return redirect(
        url_for("index_view", index_name="orgs")
    )


@app.route("/index/<index_name>")
def index_view(index_name: str):

    if index_name not in INDEXES:
        abort(404)

    query = request.args.get("q", "").strip()

    try:
        page = max(
            1,
            int(request.args.get("page", "1")),
        )

    except ValueError:
        page = 1

    # Only the OpenSearch request is inside this try block.
    # Template errors should not be reported as connection problems.
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


# ---------------------------------------------------------------------
# Create document
# ---------------------------------------------------------------------

@app.route(
    "/index/<index_name>/new",
    methods=["GET", "POST"],
)
def create_document(index_name: str):

    if index_name not in INDEXES:
        abort(404)

    properties = load_mapping(index_name)
    values = {}

    if request.method == "POST":

        try:
            document = build_document(
                index_name,
                request.form,
                is_new=True,
            )

            # Validate mandatory organisation fields.
            validate_required_fields(
                index_name,
                document,
            )

            if not document:
                raise ValueError(
                    "Enter at least one field before creating the document."
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
                f"Could not create document: "
                f"{friendly_opensearch_error(exc)}",
                "danger",
            )

            values = request.form.to_dict()

    return render_template(
        "document_form.html",
        index_name=index_name,
        index_info=INDEXES[index_name],
        properties=properties,
        values=values,
        mode="new",
        doc_id=None,
        multi_value_fields=MULTI_VALUE_FIELDS,
        textarea_fields=TEXTAREA_FIELDS,
        required_fields=(
            ORG_REQUIRED_FIELDS
            if index_name == "orgs"
            else set()
        ),
    )


# ---------------------------------------------------------------------
# Edit document
# ---------------------------------------------------------------------

@app.route(
    "/index/<index_name>/<doc_id>/edit",
    methods=["GET", "POST"],
)
def edit_document(index_name: str, doc_id: str):

    if index_name not in INDEXES:
        abort(404)

    properties = load_mapping(index_name)

    try:
        index_path = quote(index_name, safe="")
        document_path = quote(doc_id, safe="")

        response = opensearch_json(
            "GET",
            f"/{index_path}/_doc/{document_path}",
        )

        current_source = response.get("_source", {})

    except Exception as exc:

        flash(
            f"Could not retrieve document: "
            f"{friendly_opensearch_error(exc)}",
            "danger",
        )

        return redirect(
            url_for(
                "index_view",
                index_name=index_name,
            )
        )

    values = current_source.copy()

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
            document = build_document(
                index_name,
                request.form,
                is_new=False,
            )

            # Validate mandatory organisation fields.
            validate_required_fields(
                index_name,
                document,
            )

            opensearch_request(
                "PUT",
                f"/{index_path}/_doc/{document_path}",
                params={"refresh": "wait_for"},
                body=document,
            )

            flash(
                "Document updated successfully.",
                "success",
            )

            return redirect(
                url_for(
                    "edit_document",
                    index_name=index_name,
                    doc_id=doc_id,
                )
            )

        except Exception as exc:

            flash(
                f"Could not update document: "
                f"{friendly_opensearch_error(exc)}",
                "danger",
            )

            values = request.form.to_dict()

    return render_template(
        "document_form.html",
        index_name=index_name,
        index_info=INDEXES[index_name],
        properties=properties,
        values=values,
        mode="edit",
        doc_id=doc_id,
        multi_value_fields=MULTI_VALUE_FIELDS,
        textarea_fields=TEXTAREA_FIELDS,
        required_fields=(
            ORG_REQUIRED_FIELDS
            if index_name == "orgs"
            else set()
        ),
    )


# ---------------------------------------------------------------------
# Delete document
# ---------------------------------------------------------------------

@app.route(
    "/index/<index_name>/<doc_id>/delete",
    methods=["POST", "GET"],
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

        flash(
            f"Document {doc_id} deleted.",
            "success",
        )

    except Exception as exc:

        flash(
            f"Could not delete document: "
            f"{friendly_opensearch_error(exc)}",
            "danger",
        )

    return redirect(
        url_for(
            "index_view",
            index_name=index_name,
        )
    )


# ---------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------

@app.route("/settings", methods=["GET", "POST"])
def settings():

    current = load_config()

    if request.method == "POST":

        candidate = current.copy()

        candidate["host"] = request.form.get(
            "host", ""
        ).strip()

        candidate["username"] = request.form.get(
            "username", ""
        ).strip()

        candidate["ca_certs"] = request.form.get(
            "ca_certs", ""
        ).strip()

        candidate["use_ssl"] = (
            request.form.get("use_ssl") == "on"
        )

        candidate["verify_certs"] = (
            request.form.get("verify_certs") == "on"
        )

        try:
            candidate["port"] = int(
                request.form.get("port", "9200")
            )

            candidate["timeout"] = int(
                request.form.get("timeout", "15")
            )

            if not candidate["host"]:
                raise ValueError(
                    "Enter an OpenSearch IP address or hostname."
                )

            if not 1 <= candidate["port"] <= 65535:
                raise ValueError(
                    "Port must be between 1 and 65535."
                )

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

                info = opensearch_json(
                    "GET",
                    "/",
                    config=candidate,
                )

                cluster = info.get(
                    "cluster_name",
                    "OpenSearch",
                )

                version = info.get(
                    "version", {}
                ).get(
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
                    f"Connected to {cluster} "
                    f"(version {version})."
                )

                if missing:
                    message += (
                        " Missing indexes: "
                        + ", ".join(missing)
                        + "."
                    )

                flash(
                    message,
                    "success" if not missing else "warning",
                )

            else:
                save_config(candidate)

                flash(
                    "Settings saved.",
                    "success",
                )

                current = candidate

        except Exception as exc:

            flash(
                f"Settings error: "
                f"{friendly_opensearch_error(exc)}",
                "danger",
            )

        if request.form.get("action") == "test":
            current = candidate

    return render_template(
        "settings.html",
        config=current,
        password_is_set=bool(
            current.get("password")
        ),
    )


# ---------------------------------------------------------------------
# Error pages
# ---------------------------------------------------------------------

@app.errorhandler(404)
def not_found(_error):
    return render_template("404.html"), 404


# ---------------------------------------------------------------------
# Application entry point
# ---------------------------------------------------------------------

if __name__ == "__main__":

    # Keep this bound to loopback.
    # Do not change to 0.0.0.0 unless you deliberately intend
    # to expose the management UI to your network.
    app.run(
        host="127.0.0.1",
        port=8080,
        debug=False,
    )