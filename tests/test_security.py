"""Sécurité : CSRF, en-têtes, XSS, limiteur, validations de configuration."""
import time

import pytest

from tests.conftest import Session, make_image_bytes, register_and_login
from webapp import create_app
from webapp.security import LoginRateLimiter, is_safe_redirect


def test_post_without_csrf_token_is_rejected(client):
    r = client.post("/register", data={"username": "mallory", "password": "longenough1"})
    assert r.status_code == 400


def test_post_with_wrong_csrf_token_is_rejected(client):
    Session(client).token()
    assert client.post("/login", data={"username": "x", "password": "y", "csrf_token": "forged"}).status_code == 400


def test_json_endpoint_requires_csrf_header(gallery):
    assert gallery.c.post("/api/search", json={"query_id": 1}).status_code == 400


def test_security_headers_present(client):
    h = client.get("/login").headers
    assert "script-src 'self'" in h["Content-Security-Policy"] and "'unsafe-inline'" not in \
        h["Content-Security-Policy"].split("script-src")[1].split(";")[0]
    assert h["X-Frame-Options"] == "DENY" and h["X-Content-Type-Options"] == "nosniff"
    assert h["Cache-Control"] == "no-store"


def test_session_cookie_flags(client):
    cookie = client.get("/login").headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie


def test_hsts_only_in_production(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    import importlib, webapp.config as cfg
    importlib.reload(cfg)
    prod = create_app("production", DATABASE=tmp_path / "p.db", STORAGE_DIR=tmp_path / "s", SECRET_KEY="y" * 40)
    assert "Strict-Transport-Security" in prod.test_client().get("/login").headers
    importlib.reload(cfg)


def test_production_refuses_default_secret(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    import importlib, webapp.config as cfg
    importlib.reload(cfg)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        cfg.get_config("production")
    importlib.reload(cfg)


def test_unknown_profile_is_rejected():
    from webapp.config import get_config
    with pytest.raises(ValueError):
        get_config("staging")


def test_filename_with_html_is_escaped_everywhere(user, app):
    evil = "<img src=x onerror=alert(1)>'.png"
    user.upload([(evil, make_image_bytes())])
    from webapp import db as dbl
    conn = dbl.connect(app.config["DATABASE"])
    iid = conn.execute("SELECT id FROM images").fetchone()[0]       # l'import a bien eu lieu
    conn.close()
    for url in ("/", "/dashboard", f"/image/{iid}", f"/search?query_id={iid}"):
        html = user.get(url).data.decode()
        assert "<img src=x" not in html, url                          # échappé par Jinja2 (&lt;img…)
    assert "&lt;img src=x" in user.get("/").data.decode()


def test_path_traversal_in_filename_is_neutralised(user, app, tmp_path):
    user.upload([("../../evil.png", make_image_bytes())])
    assert not (tmp_path / "evil.png").exists() and not (tmp_path.parent / "evil.png").exists()
    from webapp import db as dbl
    conn = dbl.connect(app.config["DATABASE"])
    name, stored = conn.execute("SELECT filename, stored_name FROM images").fetchone()
    conn.close()
    assert name == "evil.png" and "/" not in stored and ".." not in stored


def test_passwords_are_hashed(client, app):
    register_and_login(client, "frank", "plain-text-pass")
    from webapp import db as dbl
    conn = dbl.connect(app.config["DATABASE"])
    h = conn.execute("SELECT password_hash FROM users").fetchone()[0]
    conn.close()
    assert "plain-text-pass" not in h and h.split(":")[0] in {"scrypt", "pbkdf2"}


def test_sql_injection_in_search_filter_is_harmless(gallery):
    r = gallery.get("/?q=' OR 1=1 --")
    assert r.status_code == 200 and b"red_0.png" not in r.data


def test_oversized_upload_is_413(user, app):
    app.config["MAX_CONTENT_LENGTH"] = 1000
    r = user.upload([("a.png", make_image_bytes(size=(200, 200), noise=100))])
    assert r.status_code == 413


def test_healthz_is_public(client):
    assert client.get("/healthz").json == {"status": "ok"}


def test_error_pages_do_not_leak_details(client):
    r = client.get("/nope")
    assert r.status_code == 404 and b"Traceback" not in r.data


class TestLoginRateLimiter:
    def test_blocks_after_max_failures_then_resets(self):
        rl = LoginRateLimiter(max_failures=2, window=60)
        assert rl.blocked("k") == 0
        rl.register_failure("k"); rl.register_failure("k")
        assert rl.blocked("k") > 0 and rl.blocked("other") == 0
        rl.reset("k")
        assert rl.blocked("k") == 0

    def test_failures_expire(self):
        rl = LoginRateLimiter(max_failures=1, window=0.05)
        rl.register_failure("k")
        assert rl.blocked("k") > 0
        time.sleep(0.08)
        assert rl.blocked("k") == 0


@pytest.mark.parametrize("target,ok", [("/gallery", True), ("/?a=1", True), ("//evil.com", False),
                                       ("https://evil.com", False), ("javascript:alert(1)", False),
                                       ("/\\evil.com", False), ("", False), (None, False)])
def test_is_safe_redirect(target, ok):
    assert is_safe_redirect(target) is ok
