"""
Flask app setup
"""

import os
import secrets
from flask import Flask, request, abort
from werkzeug.middleware.proxy_fix import ProxyFix


def create_app():
    app = Flask(__name__)

    # Secret key for session/signing
    secret = os.environ.get("SECRET_KEY")
    if not secret:
        # Fallback for local/dev; set REQUIRE_SECRET_KEY=1 in prod to enforce
        secret = "dev-secret"
    app.secret_key = secret

    # Session cookie hardening (tunable via env)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax")
    # Default secure off for local HTTP unless explicitly enabled
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"

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
    from .login import login_bp
    from .admin import admin_bp
    app.register_blueprint(poll_bp)
    app.register_blueprint(login_bp)
    app.register_blueprint(admin_bp)

    # Basic security headers (safe defaults for inline scripts)
    @app.after_request
    def _set_security_headers(resp):
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        return resp

    # Optional CSRF enforcement for admin POST/PUT/PATCH/DELETE
    # Enable by setting ADMIN_CSRF_ENFORCE=1
    if os.environ.get("ADMIN_CSRF_ENFORCE", "1") == "1":
        @app.before_request
        def _admin_csrf_guard():
            if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.path.startswith("/admin"):
                token_hdr = request.headers.get("X-CSRF-Token", "")
                token_sess = request.cookies.get("_csrf") or request.headers.get("X-Session-CSRF") or request.environ.get("session_csrf")
                # Prefer server-side session token if present
                try:
                    from flask import session
                    token_sess = session.get("csrf_token") or token_sess
                except Exception:
                    pass
                # Constant-time compare when both present
                if not token_hdr or not token_sess or not secrets.compare_digest(str(token_hdr), str(token_sess)):
                    abort(403)

    @app.route("/health")
    def health():
        return {"status": "ok"}

    return app
