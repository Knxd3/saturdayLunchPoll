"""
Flask app setup
"""

from flask import Flask

def create_app():
    app = Flask(__name__)

    from .poll import poll_bp
    app.register_blueprint(poll_bp)

    @app.route("/health")
    def health():
        return {"status": "ok"}
    
    return app