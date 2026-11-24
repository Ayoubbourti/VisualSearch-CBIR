"""Client HTTP de l'API de descripteurs : l'application web ne calcule rien elle-même."""
from contextlib import ExitStack
from pathlib import Path

import requests


class ApiUnavailable(Exception):
    """L'API de descripteurs est injoignable ou a renvoyé une erreur."""


def _headers(api_key: str = "") -> dict:
    return {"X-API-Key": api_key} if api_key else {}


def compute_descriptors(paths: list[Path], api_url: str, timeout: int = 300, api_key: str = "") -> list[dict]:
    """Envoie un LOT d'images à POST /api/descriptors ; retourne la liste des résultats (même ordre).
    Chaque élément est soit un dict de descripteurs, soit {"error": ...}."""
    if not paths:
        return []
    try:
        with ExitStack() as stack:                       # garantit la fermeture de tous les fichiers
            files = [("images", (Path(p).name, stack.enter_context(open(p, "rb")))) for p in paths]
            resp = requests.post(f"{api_url}/api/descriptors", files=files, timeout=timeout,
                                 headers=_headers(api_key))
        resp.raise_for_status()
        results = resp.json()["results"]
        if len(results) != len(paths):
            raise ValueError("Réponse incohérente de l'API (nombre de résultats).")
    except (requests.RequestException, KeyError, ValueError) as exc:
        raise ApiUnavailable(str(exc)) from exc
    return results


def is_up(api_url: str) -> bool:
    try:
        return requests.get(f"{api_url}/api/health", timeout=2).ok
    except requests.RequestException:
        return False
