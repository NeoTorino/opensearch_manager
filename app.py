
from __future__ import annotations

import csv
import hmac
import io
import json
import os
import secrets
import uuid

from datetime import date, datetime, timezone
from math import ceil
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from flask import (
    Flask,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)


# ---------------------------------------------------------------------
# Paths and configuration
# ---------------------------------------------------------------------

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


# ---------------------------------------------------------------------
# Index definitions
# ---------------------------------------------------------------------

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


ORG_REQUIRED_FIELDS = {
    "name",
    "careers_url",
    "source",
    "active",
    "excluded",
    "created",
    "updated_at",
}


MULTI_VALUE_FIELDS = {
    "tags",
    "skills",
    "language",
}


TEXTAREA_FIELDS = {
    "description",
    "summary",
    "address",
    "location",
    "location_2",
    "location_3",
}


# ---------------------------------------------------------------------
# Configuration management
# ---------------------------------------------------------------------

def save_config(config: dict[str, Any]) -> None:

    INSTANCE_DIR.mkdir(
        mode=0o700,
        parents=True,
        exist_ok=True,
    )

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


# ---------------------------------------------------------------------
# Mapping management
# ---------------------------------------------------------------------

def load_mapping(index_name: str) -> dict[str, Any]:

    if index_name not in INDEXES:
        abort(404)

    path = (
        MAPPINGS_DIR
        / INDEXES[index_name]["mapping_file"]
    )

    try:

        data = json.loads(
            path.read_text(encoding="utf-8")
        )

        return data["mappings"]["properties"]

    except (OSError, json.JSONDecodeError, KeyError) as exc:

        raise RuntimeError(
            f"Could not load mapping for {index_name}: {exc}"
        ) from exc


# ---------------------------------------------------------------------
# OpenSearch HTTP communication
# ---------------------------------------------------------------------

class OpenSearchHTTPError(RuntimeError):

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

            self.detail = (
                response.reason
                or "Unknown OpenSearch error"
            )

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

    cfg = config or load_config()

    host = str(
        cfg.get("host", "")
    ).strip().rstrip("/")

    if not host:

        raise ValueError(
            "OpenSearch host/IP has not been configured."
        )

    host = (
        host.removeprefix("https://")
        .removeprefix("http://")
    )

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

        ca_certs = str(
            cfg.get("ca_certs", "")
        ).strip()

        if ca_certs:

            cert_path = Path(
                ca_certs
            ).expanduser()

            if not cert_path.is_absolute():

                cert_path = BASE_DIR / cert_path

            if not cert_path.exists():

                raise ValueError(
                    f"CA certificate path does not exist: {cert_path}"
                )

            verify = str(cert_path)

        else:

            verify = True

    username = str(
        cfg.get("username", "")
    ).strip()

    password = str(
        cfg.get("password", "")
    )

    auth = (
        (username, password)
        if username
        else None
    )

    scheme = (
        "https"
        if use_ssl
        else "http"
    )

    url = f"{scheme}://{host}:{port}{path}"

    response = requests.request(
        method=method.upper(),
        url=url,
        auth=auth,
        verify=verify,
        timeout=timeout,
        headers={
            "Accept": "application/json",
        },
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
# Value formatting
# ---------------------------------------------------------------------

def format_value(value: Any) -> str:

    if value is None:
        return ""

    if isinstance(value, bool):
        return "Yes" if value else "No"

    if isinstance(value, list):

        return ", ".join(
            str(item)
            for item in value
        )

    if isinstance(value, dict):

        return json.dumps(
            value,
            ensure_ascii=False,
        )

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

        parsed = datetime.fromisoformat(
            raw.replace("Z", "+00:00")
        )

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

    field_type = properties.get(
        field_name, {}
    ).get("type")

    if field_type == "date":

        return format_date_input(value)

    return format_value(value)


# ---------------------------------------------------------------------
# Document processing
# ---------------------------------------------------------------------

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

    if field_name == "source":
        if raw == "__new_source__":
            raw = request.form.get("source_new", "")
        return raw.strip()

    if field_type == "boolean":

        lowered = raw.lower()

        if lowered == "true":
            return True

        if lowered == "false":
            return False

        raise ValueError(
            f"{field_name}: choose Yes or No."
        )

    if field_type in {
        "integer",
        "long",
        "short",
        "byte",
    }:

        try:

            return int(raw)

        except ValueError as exc:

            raise ValueError(
                f"{field_name}: enter a whole number."
            ) from exc

    if field_type in {
        "float",
        "double",
    }:

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
            isinstance(value, str)
            and not value.strip()
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
    """
    Retrieve distinct source values from the Organisations index.

    The source field is a keyword field in orgs_mapping.json.
    """

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
                        "order": {
                            "_key": "asc",
                        },
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

    return sorted(
        sources,
        key=str.casefold,
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

        # Search across all mapped fields, not just the
        # columns currently visible in the table.
        #
        # Include sub-fields such as name.keyword where present.
        # Lenient mode allows different field types to be searched
        # without failing on incompatible query terms.

        searchable_fields = []

        for field_name, spec in properties.items():

            searchable_fields.append(field_name)

            for subfield in spec.get("fields", {}):

                searchable_fields.append(
                    f"{field_name}.{subfield}"
                )

        search_query = {
            "simple_query_string": {
                "query": query.strip(),
                "fields": searchable_fields,
                "default_operator": "and",
                "lenient": True,
            },
        }

    else:

        search_query = {
            "match_all": {},
        }

    index_path = quote(
        index_name,
        safe="",
    )

    response = opensearch_json(
        "POST",
        f"/{index_path}/_search",
        body={
            "from": (page - 1) * page_size,
            "size": page_size,
            "track_total_hits": True,
            "query": search_query,
            "sort": [
                {
                    "_doc": "asc",
                },
            ],
        },
    )

    total_info = response["hits"]["total"]

    total = (
        total_info["value"]
        if isinstance(total_info, dict)
        else total_info
    )

    pages = max(
        1,
        ceil(total / page_size),
    )

    records = []

    for hit in response["hits"]["hits"]:

        source = hit.get("_source", {})

        records.append({
            "id": hit["_id"],

            "source": source,

            "values": [
                format_field_value(
                    col,
                    source.get(col),
                    properties,
                )
                for col in INDEXES[index_name]["columns"]
            ],
        })

    return records, total, pages


# ---------------------------------------------------------------------
# CSV backup
# ---------------------------------------------------------------------

def csv_cell(value: Any) -> Any:
    """
    Convert values into CSV-compatible representations.

    Lists and dictionaries are preserved as JSON strings.
    """

    if value is None:
        return ""

    if isinstance(value, bool):

        return (
            "true"
            if value
            else "false"
        )

    if isinstance(value, (list, dict)):

        return json.dumps(
            value,
            ensure_ascii=False,
        )

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

    writer.writerow([
        "_id",
        *field_names,
    ])

    index_path = quote(
        index_name,
        safe="",
    )

    scroll_id = None

    try:

        response = opensearch_json(
            "POST",
            f"/{index_path}/_search",
            params={
                "scroll": "2m",
            },
            body={
                "size": 1000,
                "sort": [
                    "_doc",
                ],
                "query": {
                    "match_all": {},
                },
            },
        )

        scroll_id = response.get("_scroll_id")

        hits = response.get(
            "hits", {}
        ).get(
            "hits", []
        )

        while hits:

            for hit in hits:

                source = hit.get("_source", {})

                row = [
                    hit.get("_id", ""),
                ]

                for field_name in field_names:

                    row.append(
                        csv_cell(
                            source.get(field_name)
                        )
                    )

                writer.writerow(row)

            if not scroll_id:
                break

            response = opensearch_json(
                "POST",
                "/_search/scroll",
                body={
                    "scroll": "2m",
                    "scroll_id": scroll_id,
                },
            )

            scroll_id = response.get(
                "_scroll_id",
                scroll_id,
            )

            hits = response.get(
                "hits", {}
            ).get(
                "hits", []
            )

    finally:

        # Release the OpenSearch scroll context.

        if scroll_id:

            try:

                opensearch_request(
                    "DELETE",
                    "/_search/scroll",
                    body={
                        "scroll_id": [
                            scroll_id,
                        ],
                    },
                )

            except Exception:

                app.logger.warning(
                    "Could not clear the CSV export scroll context."
                )

    return output.getvalue()


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

    return {
        "csrf_token": csrf_token,
    }


@app.before_request
def protect_post_requests():

    if request.method == "POST":

        expected = session.get(
            "_csrf_token",
            "",
        )

        submitted = request.form.get(
            "csrf_token",
            "",
        )

        if (
            not expected
            or not submitted
            or not hmac.compare_digest(
                expected,
                submitted,
            )
        ):

            abort(
                400,
                description=(
                    "The form security token is missing or invalid. "
                    "Reload the page and try again."
                ),
            )


# ---------------------------------------------------------------------
# Template filters and global variables
# ---------------------------------------------------------------------

@app.template_filter("display_value")
def display_value(value):

    return format_value(value)


@app.template_filter("date_input")
def date_input(value):

    return format_date_input(value)


@app.context_processor
def inject_globals():

    view_args = request.view_args or {}

    active_index = view_args.get(
        "index_name",
        "orgs",
    )

    if active_index not in INDEXES:
        active_index = "orgs"

    return {
        "indexes": INDEXES,
        "active_index": active_index,
    }


# ---------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------

def friendly_opensearch_error(
    exc: Exception,
) -> str:

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

            return (
                "The requested document or index was not found."
            )

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
# Home
# ---------------------------------------------------------------------

@app.route("/")
def home():

    return redirect(
        url_for(
            "index_view",
            index_name="orgs",
        )
    )


# ---------------------------------------------------------------------
# Index view
# ---------------------------------------------------------------------

@app.route("/index/<index_name>")
def index_view(index_name: str):

    if index_name not in INDEXES:
        abort(404)

    query = request.args.get(
        "q",
        "",
    ).strip()

    try:

        page = max(
            1,
            int(request.args.get("page", "1")),
        )

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


# ---------------------------------------------------------------------
# CSV backup route
# ---------------------------------------------------------------------

@app.route("/index/<index_name>/backup.csv")
def backup_index(index_name: str):

    if index_name not in INDEXES:
        abort(404)

    try:

        csv_content = export_index_csv(index_name)

        filename = (
            f"{index_name}-backup-"
            f"{date.today().isoformat()}.csv"
        )

        response = Response(
            csv_content,
            mimetype="text/csv",
        )

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

        return redirect(
            url_for(
                "index_view",
                index_name=index_name,
            )
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

    source_options = []

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

    values = {}

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

            validate_required_fields(
                index_name,
                document,
            )

            if not document:

                raise ValueError(
                    "Enter at least one field before creating the document."
                )

            document_id = uuid.uuid4().hex

            index_path = quote(
                index_name,
                safe="",
            )

            document_path = quote(
                document_id,
                safe="",
            )

            opensearch_request(
                "PUT",
                f"/{index_path}/_doc/{document_path}",
                params={
                    "refresh": "wait_for",
                },
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
        source_options=source_options,
    )


# ---------------------------------------------------------------------
# Edit document
# ---------------------------------------------------------------------

@app.route(
    "/index/<index_name>/<doc_id>/edit",
    methods=["GET", "POST"],
)
def edit_document(
    index_name: str,
    doc_id: str,
):

    if index_name not in INDEXES:
        abort(404)

    properties = load_mapping(index_name)

    index_path = quote(
        index_name,
        safe="",
    )

    document_path = quote(
        doc_id,
        safe="",
    )

    try:

        response = opensearch_json(
            "GET",
            f"/{index_path}/_doc/{document_path}",
        )

        current_source = response.get(
            "_source",
            {},
        )

    except Exception as exc:

        flash(
            "Could not retrieve document: "
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

    source_options = []

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

            source_options.append(
                current_source_value
            )

        source_options.sort(
            key=str.casefold
        )

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

            validate_required_fields(
                index_name,
                document,
            )

            opensearch_request(
                "PUT",
                f"/{index_path}/_doc/{document_path}",
                params={
                    "refresh": "wait_for",
                },
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
                "Could not update document: "
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
        source_options=source_options,
    )


# ---------------------------------------------------------------------
# Delete document
# ---------------------------------------------------------------------

@app.route(
    "/index/<index_name>/<doc_id>/delete",
    methods=["GET", "POST"],
)
def delete_document(
    index_name: str,
    doc_id: str,
):

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

        index_path = quote(
            index_name,
            safe="",
        )

        document_path = quote(
            doc_id,
            safe="",
        )

        opensearch_request(
            "DELETE",
            f"/{index_path}/_doc/{document_path}",
            params={
                "refresh": "wait_for",
            },
        )

        flash(
            f"Document {doc_id} deleted.",
            "success",
        )

    except Exception as exc:

        flash(
            "Could not delete document: "
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

@app.route(
    "/settings",
    methods=["GET", "POST"],
)
def settings():

    current = load_config()

    if request.method == "POST":

        candidate = current.copy()

        candidate["host"] = request.form.get(
            "host",
            "",
        ).strip()

        candidate["username"] = request.form.get(
            "username",
            "",
        ).strip()

        candidate["ca_certs"] = request.form.get(
            "ca_certs",
            "",
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

            action = request.form.get(
                "action",
                "save",
            )

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
                    "version",
                    {},
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
                "Settings error: "
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
    # Do not expose the management interface directly to your LAN.

    app.run(
        host="127.0.0.1",
        port=8080,
        debug=False,
    )
