"""Fonctions partagées par les blueprints : accès base, authentification, propriété des images."""
from __future__ import annotations

from functools import wraps
from pathlib import Path

from flask import abort, current_app, g, jsonify, redirect, request, url_for

from webapp import db as dbl
from webapp.security import is_safe_redirect
from webapp.services import imagestore


def get_db():
    """Connexion SQLite de la requête courante (une par requête, fermée au teardown)."""
    if "db" not in g:
        g.db = dbl.connect(current_app.config["DATABASE"])
    return g.db


def login_required(view):
    """Redirige vers /login (ou répond 401 JSON pour les routes /api/)."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if g.user is None:
            if request.path.startswith("/api/"):
                return jsonify(error="Authentification requise."), 401
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)
    return wrapper


def own_image(image_id):
    """Image de l'utilisateur courant, sinon 404 (on ne révèle pas l'existence des images d'autrui)."""
    row = get_db().execute("SELECT * FROM images WHERE id=? AND user_id=?", (image_id, g.user["id"])).fetchone()
    if row is None:
        abort(404)
    return row


def image_path(row) -> Path:
    return imagestore.user_dir(current_app.config["STORAGE_DIR"], row["user_id"]) / row["stored_name"]


def parse_category(value):
    """'' -> None (aucune catégorie) ; sinon id vérifié comme appartenant à l'utilisateur (400 sinon)."""
    if not value:
        return None
    if not str(value).isdigit() or not get_db().execute(
            "SELECT 1 FROM categories WHERE id=? AND user_id=?", (value, g.user["id"])).fetchone():
        abort(400, "Catégorie invalide.")
    return int(value)


def back(default_endpoint: str = "gallery.index", **values):
    """Redirection vers la page précédente, uniquement si elle appartient à ce site."""
    ref = request.referrer or ""
    if ref.startswith(request.host_url):
        local = "/" + ref[len(request.host_url):]
        if is_safe_redirect(local):
            return redirect(local)
    return redirect(url_for(default_endpoint, **values))
