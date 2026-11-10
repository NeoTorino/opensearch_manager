from __future__ import annotations

from flask import Flask

import routes_documents
import routes_index
import routes_settings
from config import load_config
from hooks import register_hooks


def create_app() -> Flask:
    app = Flask(__name__)

    app.config["SECRET_KEY"] = load_config()["secret_key"]
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    register_hooks(app)
    routes_index.register(app)
    routes_documents.register(app)
    routes_settings.register(app)

    return app


app = create_app()


if __name__ == "__main__":
    # Keep this bound to loopback.
    # Do not expose the management interface directly to your LAN.
    app.run(host="127.0.0.1", port=8080, debug=False)