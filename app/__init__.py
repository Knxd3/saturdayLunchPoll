"""
Flask app setup
"""

import os
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

def create_app():
    app = Flask(__name__)
    # Secret key for session/signing if needed
    app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")
    # Respect proxy headers on Fly/io or other platforms
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_host=1)

    # Ensure DB tables exist
    try:
        from .db import init_db
        init_db()
    except Exception:
        # Fail open; routes can still run and surface errors
        pass

    from .poll import poll_bp
    app.register_blueprint(poll_bp)

    @app.route("/health")
    def health():
        return {"status": "ok"}
    
    return app
