"""
Configuration de l'application web.

Trois profils (sélection via la variable d'environnement ``APP_ENV``) :
  * ``development`` (défaut) : confort de développement, clé de session de secours ;
  * ``production``           : ``SECRET_KEY`` OBLIGATOIRE, cookies ``Secure``, HSTS ;
  * ``testing``              : utilisé par la suite pytest (CSRF actif, rate-limit désactivé).

Un fichier ``.env`` placé à la racine du projet est chargé automatiquement s'il existe
(python-dotenv) ; les variables déjà présentes dans l'environnement restent prioritaires.
"""
from __future__ import annotations

import os
from pathlib import Path

try:                                    # python-dotenv est optionnel : le projet marche sans
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
except ImportError:                     # pragma: no cover
    pass

BASE_DIR = Path(__file__).resolve().parent
_DEV_SECRET = "dev-only-change-this-secret-before-deployment"  # noqa: S105 (refusé en production)


def _env_bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


class Config:
    """Paramètres communs à tous les profils."""
    ENV = "development"
    SECRET_KEY = os.environ.get("SECRET_KEY", _DEV_SECRET)
    DATABASE = Path(os.environ.get("GALLERY_DB", BASE_DIR / "instance" / "gallery.db"))
    STORAGE_DIR = Path(os.environ.get("GALLERY_STORAGE", BASE_DIR / "instance" / "storage"))

    # --- API de descripteurs -------------------------------------------------
    API_URL = os.environ.get("DESCRIPTOR_API_URL", "http://127.0.0.1:5001")
    API_KEY = os.environ.get("DESCRIPTOR_API_KEY", "")           # vide = API ouverte (dev local)
    API_TIMEOUT = int(os.environ.get("API_TIMEOUT", "300"))      # secondes (gros lots d'images)
    API_BATCH_SIZE = 16                                          # images par requête HTTP

    # --- Fichiers ------------------------------------------------------------
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", str(512 * 1024 * 1024)))
    ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
    MAX_IMAGE_PIXELS = 50_000_000       # refuse les « bombes de décompression » (≈ 7000×7000 px)
    PAGE_SIZE = 48                      # images par page dans la galerie
    THUMB_SIZE = (256, 256)

    # --- Recherche -----------------------------------------------------------
    SEARCH_DEFAULT_K = 24               # nombre d'images retournées (= « scope »)
    SEARCH_MAX_K = 200
    MAX_WEIGHT_RATIO = 20.0             # garde-fou sur les poids Type-1 (voir retrieval.py)

    # --- Sécurité ------------------------------------------------------------
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False
    PERMANENT_SESSION_LIFETIME = 8 * 3600
    LOGIN_MAX_FAILURES = 5              # tentatives échouées tolérées…
    LOGIN_WINDOW_SECONDS = 300          # …dans cette fenêtre, avant blocage temporaire
    PASSWORD_MIN_LENGTH = 8
    HSTS = False
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")


class DevelopmentConfig(Config):
    ENV = "development"


class ProductionConfig(Config):
    ENV = "production"
    SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", True)
    HSTS = _env_bool("ENABLE_HSTS", True)

    @classmethod
    def validate(cls) -> None:
        if cls.SECRET_KEY == _DEV_SECRET or len(cls.SECRET_KEY) < 32:
            raise RuntimeError("SECRET_KEY doit être défini (≥ 32 caractères) en production. "
                               "Générer : python -c \"import secrets; print(secrets.token_hex(32))\"")


class TestingConfig(Config):
    ENV = "testing"
    TESTING = True
    SECRET_KEY = "test-secret-key-not-for-production-use-0123456789"  # noqa: S105
    LOGIN_MAX_FAILURES = 3


CONFIGS = {"development": DevelopmentConfig, "production": ProductionConfig, "testing": TestingConfig}


def get_config(name: str | None = None):
    """Retourne la classe de configuration du profil demandé (défaut : variable APP_ENV)."""
    name = (name or os.environ.get("APP_ENV", "development")).lower()
    if name not in CONFIGS:
        raise ValueError(f"APP_ENV inconnu : {name!r} (attendu : {', '.join(CONFIGS)})")
    cfg = CONFIGS[name]
    if hasattr(cfg, "validate"):
        cfg.validate()
    return cfg
