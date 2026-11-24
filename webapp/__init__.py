"""
Application web « VisualSearch » (Flask) — fabrique d'application.

    from webapp import create_app
    app = create_app()                 # profil choisi par APP_ENV (développement par défaut)

Organisation du paquet :
    config.py        profils de configuration (dev / prod / test)
    db.py            schéma SQLite, migrations, requêtes sur la hiérarchie de catégories
    security.py      CSRF, en-têtes HTTP, limiteur de connexions, redirections sûres
    core.py          utilitaires partagés (accès base, login_required, propriété des images)
    blueprints/      routes : auth, gallery (catégories), images (fichiers, transformations), search (CBIR)
    services/        logique métier : api_client, imagestore, transforms, retrieval (moteur Type-1)
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from flask import Flask, g, jsonify, render_template, request, session

from webapp import db as dbl
from webapp import security
from webapp.config import get_config
from webapp.services import transforms


def create_app(profile: str | None = None, **overrides) -> Flask:
    """Construit l'application.

    profile   : « development » | « production » | « testing » (défaut : variable APP_ENV) ;
    overrides : valeurs de configuration forcées (utilisé par les tests : DATABASE=..., STORAGE_DIR=...).
    """
    app = Flask(__name__)
    app.config.from_object(get_config(profile))
    app.config.update(overrides)

    logging.basicConfig(level=app.config.get("LOG_LEVEL", "INFO"), stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    Path(app.config["STORAGE_DIR"]).mkdir(parents=True, exist_ok=True)
    dbl.init_db(app.config["DATABASE"])

    from PIL import Image
    Image.MAX_IMAGE_PIXELS = app.config["MAX_IMAGE_PIXELS"] * 2   # Pillow refuse > 2× cette valeur

    app.extensions["login_limiter"] = security.LoginRateLimiter(
        app.config["LOGIN_MAX_FAILURES"], app.config["LOGIN_WINDOW_SECONDS"])

    _register_request_hooks(app)
    _register_error_handlers(app)

    from webapp.blueprints import auth, gallery, images, search
    for module in (auth, gallery, images, search):
        app.register_blueprint(module.bp)

    @app.get("/healthz")
    def healthz():
        """Sonde de santé (Docker / supervision) : vérifie l'accès à la base."""
        from webapp.core import get_db
        get_db().execute("SELECT 1")
        return jsonify(status="ok")

    return app


def _register_request_hooks(app: Flask) -> None:
    from webapp.core import get_db

    @app.teardown_appcontext
    def close_db(_exc):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    @app.before_request
    def load_user_and_check_csrf():
        g.user = None
        if request.endpoint in {"static", "healthz"}:
            return
        if session.get("user_id"):
            g.user = get_db().execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
            if g.user is None:                         # compte supprimé : on invalide la session
                session.clear()
        security.check_csrf()

    @app.after_request
    def harden(response):
        return security.add_security_headers(response, hsts=app.config["HSTS"])

    @app.context_processor
    def inject_globals():
        return {"csrf_token": security.csrf_token(), "operations": transforms.OPERATIONS}


def _register_error_handlers(app: Flask) -> None:
    def respond(code: int, title: str, message: str):
        if request.path.startswith("/api/"):
            return jsonify(error=message), code
        return render_template("error.html", code=code, title=title, message=message), code

    @app.errorhandler(400)
    def bad_request(e):
        return respond(400, "Requête invalide", getattr(e, "description", "Requête invalide."))

    @app.errorhandler(404)
    def not_found(_e):
        return respond(404, "Page introuvable", "Cette page ou cette image n'existe pas.")

    @app.errorhandler(413)
    def too_large(_e):
        return respond(413, "Envoi trop volumineux", "Les fichiers dépassent la taille maximale autorisée.")

    @app.errorhandler(500)
    def server_error(e):
        app.logger.exception("Erreur interne", exc_info=e)
        return respond(500, "Erreur interne", "Une erreur inattendue s'est produite.")
