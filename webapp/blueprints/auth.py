"""Authentification : inscription, connexion (avec limitation anti brute-force), déconnexion."""
from flask import (Blueprint, current_app, flash, redirect, render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from webapp.core import get_db
from webapp.security import is_safe_redirect

bp = Blueprint("auth", __name__)

# Hash factice : on le vérifie même si l'identifiant n'existe pas, pour que le temps de réponse
# ne révèle pas quels identifiants sont valides (attaque par énumération temporelle).
_DUMMY_HASH = generate_password_hash("not-a-real-password")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        pwd = request.form.get("password", "")
        min_len = current_app.config["PASSWORD_MIN_LENGTH"]
        if not (3 <= len(username) <= 40) or not username.replace("_", "").replace("-", "").replace(".", "").isalnum():
            flash("Identifiant : 3 à 40 caractères (lettres, chiffres, « . », « - », « _»).", "error")
        elif len(pwd) < min_len:
            flash(f"Mot de passe : {min_len} caractères minimum.", "error")
        elif get_db().execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            flash("Cet identifiant existe déjà.", "error")
        else:
            get_db().execute("INSERT INTO users(username, password_hash) VALUES (?,?)",
                             (username, generate_password_hash(pwd)))
            get_db().commit()
            current_app.logger.info("Nouveau compte : %s", username)
            flash("Compte créé, vous pouvez vous connecter.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth.html", mode="register")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        limiter = current_app.extensions["login_limiter"]
        key = f"{request.remote_addr}|{username.lower()}"
        wait = limiter.blocked(key)
        if wait:
            flash(f"Trop de tentatives échouées. Réessayez dans {wait} s.", "error")
            return render_template("auth.html", mode="login"), 429
        user = get_db().execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        ok = check_password_hash(user["password_hash"] if user else _DUMMY_HASH, request.form.get("password", ""))
        if user and ok:
            limiter.reset(key)
            session.clear()                                   # évite la fixation de session
            session.permanent = True
            session["user_id"] = user["id"]
            nxt = request.args.get("next", "")
            return redirect(nxt if is_safe_redirect(nxt) else url_for("gallery.index"))
        limiter.register_failure(key)
        current_app.logger.warning("Échec de connexion pour %r depuis %s", username, request.remote_addr)
        flash("Identifiants incorrects.", "error")
    return render_template("auth.html", mode="login")


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
