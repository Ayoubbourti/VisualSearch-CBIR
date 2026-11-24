"""
Briques de sécurité de l'application web.

  * protection CSRF (jeton de session comparé en temps constant) ;
  * en-têtes HTTP de durcissement (CSP stricte, anti-clickjacking, nosniff, HSTS en production) ;
  * limiteur de tentatives de connexion (fenêtre glissante, par couple IP + identifiant) ;
  * validation des redirections (empêche les « open redirects »).
"""
from __future__ import annotations

import secrets
import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlparse

from flask import abort, request, session

# Politique de contenu : tout est servi par l'application elle-même (Chart.js et polices sont
# embarqués dans static/). Les attributs style="" servent aux pastilles de couleur -> 'unsafe-inline'
# est limité aux styles ; AUCUN script inline n'est autorisé.
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
       "script-src 'self'; font-src 'self'; connect-src 'self'; object-src 'none'; "
       "base-uri 'self'; form-action 'self'; frame-ancestors 'none'")


# --------------------------------------------------------------------------- #
# CSRF
# --------------------------------------------------------------------------- #
def csrf_token() -> str:
    """Jeton CSRF de la session courante (créé à la demande)."""
    return session.setdefault("csrf", secrets.token_hex(16))


def check_csrf() -> None:
    """À appeler avant chaque requête modifiante : 400 si le jeton est absent ou faux."""
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
        if not secrets.compare_digest(sent, csrf_token()):
            abort(400, "Jeton CSRF invalide : rechargez la page.")


# --------------------------------------------------------------------------- #
# En-têtes
# --------------------------------------------------------------------------- #
def add_security_headers(response, hsts: bool = False):
    response.headers.setdefault("Content-Security-Policy", CSP)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if hsts:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    # Les pages authentifiées ne doivent pas rester en cache partagé ; les images (ETag) sont gérées à part.
    if response.mimetype == "text/html":
        response.headers.setdefault("Cache-Control", "no-store")
    return response


# --------------------------------------------------------------------------- #
# Limiteur de connexions
# --------------------------------------------------------------------------- #
class LoginRateLimiter:
    """Compte les échecs dans une fenêtre glissante. Stockage en mémoire du processus :
    suffisant pour une instance unique ; avec plusieurs workers, utiliser Redis (voir README)."""

    def __init__(self, max_failures: int = 5, window: int = 300):
        self.max_failures, self.window = max_failures, window
        self._failures: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def _purge(self, key: str, now: float) -> deque:
        q = self._failures[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def blocked(self, key: str) -> int:
        """0 si la connexion est autorisée, sinon le nombre de secondes d'attente restantes."""
        now = time.monotonic()
        with self._lock:
            q = self._purge(key, now)
            if len(q) >= self.max_failures:
                return max(1, int(self.window - (now - q[0])))
            return 0

    def register_failure(self, key: str) -> None:
        with self._lock:
            self._purge(key, time.monotonic()).append(time.monotonic())

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


# --------------------------------------------------------------------------- #
# Redirections
# --------------------------------------------------------------------------- #
def is_safe_redirect(target: str | None) -> bool:
    """Accepte uniquement un chemin local (« /galerie?x=1 »), jamais une URL absolue ou « //hôte »."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return False
    parsed = urlparse(target)
    return not parsed.scheme and not parsed.netloc
