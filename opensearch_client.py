"""OpenSearch HTTP communication and error formatting."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests

from config import BASE_DIR, load_config


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
            self.detail = response.reason or "Unknown OpenSearch error"

        super().__init__(f"HTTP {self.status_code}: {self.detail}")


def opensearch_request(
    method: str,
    path: str,
    config: dict[str, Any] | None = None,
    *,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> requests.Response:

    cfg = config or load_config()

    host = str(cfg.get("host", "")).strip().rstrip("/")

    if not host:
        raise ValueError("OpenSearch host/IP has not been configured.")

    host = host.removeprefix("https://").removeprefix("http://")

    if not host or "/" in host:
        raise ValueError(
            "Enter only an OpenSearch hostname or IP address, without a path."
        )

    try:
        port = int(cfg.get("port", 9200))
        timeout = int(cfg.get("timeout", 15))
    except (TypeError, ValueError) as exc:
        raise ValueError("Port and timeout must be numbers.") from exc

    if not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535.")

    if timeout < 1:
        raise ValueError("Timeout must be at least 1 second.")

    use_ssl = bool(cfg.get("use_ssl", True))
    verify_certs = bool(cfg.get("verify_certs", True)) if use_ssl else False

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
            f"OpenSearch returned HTTP {exc.status_code}: {exc.detail}"
        )

    if isinstance(exc, requests.exceptions.SSLError):
        return (
            "TLS certificate verification failed. "
            f"Check the CA certificate and hostname: {exc}"
        )

    if isinstance(exc, requests.exceptions.Timeout):
        return f"The connection to OpenSearch timed out: {exc}"

    if isinstance(exc, requests.exceptions.ConnectionError):
        return (
            "Could not connect to OpenSearch. "
            f"Check the host, port and network: {exc}"
        )

    if isinstance(exc, requests.exceptions.RequestException):
        return f"HTTP request failed: {exc}"

    return str(exc)