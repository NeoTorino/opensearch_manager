"""Paths, defaults, index definitions, and config/mapping loading."""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any

from flask import abort


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
            "status_code_scrape_url",
            "source",
            "active",
            "excluded",
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
    "comments",
    "summary",
    "address",
    "location",
    "location_2",
    "location_3",
}

# Text-mapped fields that should be a compact one-line input.
SINGLE_LINE_FIELDS = {
    "name",
}

# Visible rows for textareas (default is 4).
FIELD_ROWS = {
    "description": 3,
    "comments": 2,
}


# ---------------------------------------------------------------------
# Configuration management
# ---------------------------------------------------------------------

def save_config(config: dict[str, Any]) -> None:
    INSTANCE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)

    temporary = CONFIG_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(config, indent=2), encoding="utf-8")
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
        stored = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
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

    path = MAPPINGS_DIR / INDEXES[index_name]["mapping_file"]

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data["mappings"]["properties"]

    except (OSError, json.JSONDecodeError, KeyError) as exc:
        raise RuntimeError(
            f"Could not load mapping for {index_name}: {exc}"
        ) from exc