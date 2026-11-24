"""Fixtures partagées : application de test isolée (base + stockage temporaires), client connecté, images synthétiques."""
import re
import sys
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api import descriptors                         # noqa: E402
from webapp import create_app                       # noqa: E402
from webapp.services import api_client             # noqa: E402


def make_image_bytes(color=(120, 80, 40), size=(64, 48), fmt="PNG", noise=0, seed=0) -> bytes:
    """Image synthétique en mémoire. `noise` > 0 ajoute du bruit (texture)."""
    arr = np.full((size[1], size[0], 3), color, dtype=np.uint8)
    if noise:
        rng = np.random.default_rng(seed)
        arr = np.clip(arr + rng.integers(-noise, noise + 1, arr.shape), 0, 255).astype(np.uint8)
    buf = BytesIO()
    Image.fromarray(arr).save(buf, format=fmt)
    return buf.getvalue()


@pytest.fixture
def png_bytes():
    return make_image_bytes()


@pytest.fixture(autouse=True)
def fake_descriptor_api(monkeypatch):
    """Remplace l'appel HTTP vers l'API REST par un appel direct à descriptors.py (mêmes valeurs,
    sans réseau). Le comportement réel de l'API est testé séparément dans test_api.py."""
    state = {"up": True, "calls": 0}

    def fake_compute(paths, api_url, timeout=300, api_key=""):
        state["calls"] += 1
        if not state["up"]:
            raise api_client.ApiUnavailable("API arrêtée (test)")
        out = []
        for p in paths:
            try:
                out.append({"filename": Path(p).name, **descriptors.compute_all(str(p))})
            except Exception as exc:
                out.append({"filename": Path(p).name, "error": str(exc)})
        return out

    monkeypatch.setattr(api_client, "compute_descriptors", fake_compute)
    monkeypatch.setattr(api_client, "is_up", lambda url: state["up"])
    return state


@pytest.fixture
def app(tmp_path):
    return create_app("testing", DATABASE=tmp_path / "t.db", STORAGE_DIR=tmp_path / "storage")


@pytest.fixture
def client(app):
    return app.test_client()


def csrf_of(client, url="/login") -> str:
    html = client.get(url).get_data(as_text=True)
    m = re.search(r'name="csrf_token" value="([0-9a-f]+)"', html)
    assert m, "jeton CSRF introuvable dans la page"
    return m.group(1)


class Session:
    """Petit utilitaire : requêtes POST avec jeton CSRF automatique."""
    def __init__(self, client):
        self.c = client

    def token(self):
        return csrf_of(self.c, "/login")

    def post(self, url, data=None, **kw):
        data = dict(data or {})
        data.setdefault("csrf_token", self.token())
        return self.c.post(url, data=data, **kw)

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def upload(self, files, category_id=""):
        """files : liste de (nom, octets)."""
        data = {"csrf_token": self.token(), "category_id": category_id,
                "files": [(BytesIO(b), n) for n, b in files]}
        return self.c.post("/upload", data=data, content_type="multipart/form-data", follow_redirects=True)

    def json_post(self, url, payload):
        return self.c.post(url, json=payload, headers={"X-CSRF-Token": self.token()})


def register_and_login(client, username="alice", password="s3cretpass"):  # noqa: S107
    s = Session(client)
    s.post("/register", {"username": username, "password": password})
    s.post("/login", {"username": username, "password": password})
    return s


@pytest.fixture
def user(client):
    return register_and_login(client)


@pytest.fixture
def gallery(user, app):
    """Utilisateur connecté + 6 images (2 groupes visuellement distincts) importées avec descripteurs."""
    files = [(f"red_{i}.png", make_image_bytes((200 + i, 30, 30), noise=8, seed=i)) for i in range(3)]
    files += [(f"blue_{i}.png", make_image_bytes((30, 40, 200 + i), noise=40, seed=10 + i)) for i in range(3)]
    user.upload(files)
    return user
