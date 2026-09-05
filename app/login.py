"""
Google OAuth login blueprint
"""
import os
from flask import Blueprint, redirect, url_for, session, request
from google_auth_oauthlib.flow import Flow
import google.auth.transport.requests

# Determine environment
IS_PROD = os.environ.get("FLY_APP_NAME") is not None  # Fly.io sets this automatically

if IS_PROD:
    app_name = os.environ["FLY_APP_NAME"]
    REDIRECT_URI = f"https://{app_name}.fly.dev/login/callback"
else:
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"  # only for local dev
    REDIRECT_URI = "http://127.0.0.1:5000/login/callback"

login_bp = Blueprint("login", __name__)


CLIENT_SECRETS_FILE = "client_secret_satlunchpoll.json"
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]


def _client_config_from_env():
    """Build OAuth client config from env if available (Fly secrets)."""
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if client_id and client_secret:
        return {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }
    return None


def build_flow(redirect_uri, state=None):
    """Create an OAuth Flow using env config in prod or local JSON in dev."""
    cfg = _client_config_from_env()
    if cfg is not None:
        return Flow.from_client_config(cfg, scopes=SCOPES, redirect_uri=redirect_uri, state=state)
    secrets_path = os.path.join(os.path.dirname(__file__), CLIENT_SECRETS_FILE)
    return Flow.from_client_secrets_file(secrets_path, scopes=SCOPES, redirect_uri=redirect_uri, state=state)


@login_bp.route("/login")
def login():
    # Optionally remember where to go after login
    nxt = request.args.get("next")
    if nxt:
        session["post_login_redirect"] = nxt
    flow = build_flow(REDIRECT_URI)
    authorization_url, state = flow.authorization_url(
        include_granted_scopes="true" #, prompt="consent" - not necessary every time
    )
    session["state"] = state
    # Persist PKCE verifier for callback/token exchange
    session["code_verifier"] = flow.code_verifier
    return redirect(authorization_url)


@login_bp.route("/login/callback")
def callback():
    # Handle user cancel or errors gracefully
    if request.args.get("error"):
        # Clear any pending vote intent
        session.pop("pending_option_ids", None)
        session.pop("post_login_redirect", None)
        return redirect(url_for("poll.show_poll"))

    flow = build_flow(REDIRECT_URI, state=session.get("state"))
    code_verifier = session.pop("code_verifier", None)
    flow.fetch_token(authorization_response=request.url, code_verifier=code_verifier)
    credentials = flow.credentials

    from googleapiclient.discovery import build

    oauth2 = build("oauth2", "v2", credentials=credentials)
    user_info = oauth2.userinfo().get().execute()

    session.permanent = True
    session["user"] = user_info
    print(user_info)
    # If a post-login redirect was set, honor it
    post_nxt = session.pop("post_login_redirect", None)
    if post_nxt:
        try:
            return redirect(url_for(post_nxt))
        except Exception:
            # If not a named endpoint, treat as absolute/relative path
            return redirect(post_nxt)
    return redirect(url_for("poll.show_poll"))


@login_bp.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("poll.show_poll"))
