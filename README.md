# OpenSearch Manager

A small local Flask + Bootstrap CRUD interface for the `orgs` and `jobs` OpenSearch indexes.

## Features

- Browse both indexes in a table.
- Search and paginate through documents.
- Create, edit and delete documents.
- Generate document forms from the supplied OpenSearch mapping JSON files.
- Validate basic field types before sending data to OpenSearch.
- Configure host/IP, port, username, password, HTTPS, CA certificate path and timeout in the Settings page.
- Test the connection and check whether both indexes exist.

## Requirements

- Python 3.10 or newer.
- Network access from the computer running Flask to your OpenSearch node.
- An OpenSearch account with read/write/delete permissions on `orgs` and `jobs`.
- Your OpenSearch CA certificate, if the cluster uses a private/self-signed CA.

## Install and run

From the `opensearch_manager` directory:

### Linux / FreeBSD

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

Open:

```text
http://127.0.0.1:8080
```

The application binds to `127.0.0.1` only.

## First-time configuration

Open **Settings** and configure:

- IP address / hostname: your OpenSearch server (the current default is `192.168.2.250`).
- Port: `9200` by default.
- Username: `admin` by default.
- Password: your OpenSearch password.
- CA certificate: the full path to your CA PEM file on the computer running this Flask application.
- Keep **Use HTTPS** and **Verify TLS certificate** enabled for a normal secured OpenSearch endpoint.

For example, if you place your certificate in the application folder under `certs/`, the path can be:

```text
certs/opensearch-root-ca.pem
```

Relative certificate paths are resolved from the application directory. The certificate itself is not included in this project.

Click **Test connection** to check the credentials and connection. This does not save the settings. Click **Save settings** to persist them.

## Mapping files

The supplied mappings are in:

```text
mappings/orgs_mapping.json
mappings/jobs_mapping.json
```

The application reads these files at runtime. If you change an index mapping, update the corresponding JSON file too.

The current mappings use `dynamic: strict`; the application only presents fields declared in those mapping files.

The `tags`, `skills` and `language` fields in `jobs` are treated as multi-value keyword fields and are entered one value per line. If your data model uses a different convention, adjust `MULTI_VALUE_FIELDS` near the top of `app.py`.

## Document IDs

OpenSearch document `_id` values are managed separately from fields in `_source`. New documents receive a generated UUID as `_id`. For jobs, the mapped `reference` field remains an ordinary document field; it is not automatically used as `_id`.

## Clearing fields

When editing an existing document, leaving a field blank clears its value by writing `null`. When creating a document, blank fields are omitted.

## Security notes

- The OpenSearch password is saved locally in `instance/config.json`. It is not encrypted; on POSIX systems the application sets the file permissions to `0600` and the `instance` directory to `0700`. Protect the computer and its backups accordingly.
- Do not commit `instance/config.json` to source control.
- The Flask app binds to `127.0.0.1`, not `0.0.0.0`. Do not expose this management interface to your LAN or the internet without adding application authentication, HTTPS and appropriate access controls.
- Certificate verification should remain enabled. Disabling it is not recommended.
- Debug mode is disabled.

## Troubleshooting

- **Connection refused / timeout:** check the host, port, firewall and that OpenSearch is listening on the configured interface.
- **Authentication failed:** verify the username/password and that the account is enabled.
- **Certificate verify failed:** provide the correct CA PEM path. If the certificate does not contain the IP address in its Subject Alternative Name, connect using a hostname that matches the certificate.
- **Index not found:** create the `orgs` and `jobs` indexes before using the interface. This application does not create or alter indexes automatically.
- **Permission denied:** grant the OpenSearch user the required index permissions for search, index/update and delete operations.

## Index operations

The application does not modify mappings or index settings. It only performs document-level operations against the two existing indexes.
