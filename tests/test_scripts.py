"""Client HTTP de l'API + scripts en ligne de commande (indexation, évaluation)."""
import csv
import sys
from pathlib import Path

import pytest
import requests

from tests.conftest import make_image_bytes
from webapp import db as dbl
from webapp.config import Config
from webapp.services.api_client import ApiUnavailable, is_up
from webapp.services.api_client import compute_descriptors as real_compute   # référence AVANT le patch autouse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import evaluate  # noqa: E402
import index_dataset  # noqa: E402


class FakeResp:
    def __init__(self, payload, status=200):
        self.payload, self.status = payload, status
        self.ok = status < 400

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(str(self.status))

    def json(self):
        return self.payload


@pytest.fixture
def two_files(tmp_path):
    paths = []
    for i in range(2):
        p = tmp_path / f"{i}.png"
        p.write_bytes(make_image_bytes((i * 90, 10, 10)))
        paths.append(p)
    return paths


def test_client_sends_key_and_returns_results(monkeypatch, two_files):
    seen = {}

    def fake_post(url, files, timeout, headers):
        seen.update(url=url, n=len(files), headers=headers)
        return FakeResp({"results": [{"vector": [0]}, {"vector": [1]}]})

    monkeypatch.setattr(requests, "post", fake_post)
    assert len(real_compute(two_files, "http://x", 5, api_key="k")) == 2
    assert seen == {"url": "http://x/api/descriptors", "n": 2, "headers": {"X-API-Key": "k"}}


def test_client_wraps_all_failures_in_api_unavailable(monkeypatch, two_files):
    monkeypatch.setattr(requests, "post", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("down")))
    with pytest.raises(ApiUnavailable):
        real_compute(two_files, "http://x")
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp({}, 500))
    with pytest.raises(ApiUnavailable):
        real_compute(two_files, "http://x")
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp({"results": [{}]}))      # 1 résultat pour 2 images
    with pytest.raises(ApiUnavailable):
        real_compute(two_files, "http://x")


def test_client_empty_list_and_health(monkeypatch):
    assert real_compute([], "http://x") == []
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResp({}))
    assert is_up("http://x") is True
    monkeypatch.setattr(requests, "get", lambda *a, **k: (_ for _ in ()).throw(requests.Timeout()))
    assert is_up("http://x") is False


@pytest.fixture
def dataset(tmp_path):
    root = tmp_path / "data"
    (root / "plage").mkdir(parents=True)
    (root / "foret" / "pins").mkdir(parents=True)
    for i in range(6):
        (root / "plage" / f"{i}.png").write_bytes(make_image_bytes((220, 200, 120), noise=10, seed=i))
        (root / "foret" / "pins" / f"{i}.png").write_bytes(make_image_bytes((20, 120, 40), noise=50, seed=i))
    (root / "notes.txt").write_text("ignoré")
    return root


def run_index(monkeypatch, tmp_path, folder, *extra):
    monkeypatch.setattr(Config, "DATABASE", tmp_path / "idx.db")
    monkeypatch.setattr(Config, "STORAGE_DIR", tmp_path / "idx_storage")
    monkeypatch.setattr(sys, "argv", ["index_dataset", "--folder", str(folder), "--username", "admin",
                                      "--workers", "1", *extra])
    index_dataset.main()
    return dbl.connect(tmp_path / "idx.db")


def test_index_dataset_builds_category_hierarchy_and_is_rerunnable(monkeypatch, tmp_path, dataset, capsys):
    conn = run_index(monkeypatch, tmp_path, dataset)
    assert conn.execute("SELECT COUNT(*) FROM images").fetchone()[0] == 12
    assert conn.execute("SELECT COUNT(*) FROM descriptors").fetchone()[0] == 12
    names = {r["name"]: r["parent_id"] for r in conn.execute("SELECT * FROM categories")}
    assert set(names) == {"plage", "foret", "pins"} and names["pins"] is not None
    assert {p.name for p in (tmp_path / "idx_storage" / "1").iterdir() if p.is_file()}
    conn.close()
    conn = run_index(monkeypatch, tmp_path, dataset)                                   # 2e passage : rien de nouveau
    assert conn.execute("SELECT COUNT(*) FROM images").fetchone()[0] == 12
    assert "0 à importer" in capsys.readouterr().out
    conn.close()


def test_index_dataset_flat_folder_grouping_and_limit(monkeypatch, tmp_path):
    flat = tmp_path / "flat"
    flat.mkdir()
    for i in range(10):
        (flat / f"{i}.png").write_bytes(make_image_bytes((i * 20, 50, 50)))
    conn = run_index(monkeypatch, tmp_path, flat, "--group-size", "5", "--limit", "8")
    assert conn.execute("SELECT COUNT(*) FROM images").fetchone()[0] == 8
    assert [r[0] for r in conn.execute("SELECT name FROM categories ORDER BY name")] == ["Classe 00", "Classe 01"]
    conn.close()


def test_natural_sort_key():
    names = sorted([Path("10.jpg"), Path("2.jpg"), Path("1.jpg")], key=index_dataset.natural_key)
    assert [p.name for p in names] == ["1.jpg", "2.jpg", "10.jpg"]


def test_evaluate_cli_writes_detail_and_summary_csv(monkeypatch, tmp_path, dataset, capsys):
    run_index(monkeypatch, tmp_path, dataset).close()
    out = tmp_path / "res" / "e.csv"
    monkeypatch.setattr(sys, "argv", ["evaluate", "--username", "admin", "--queries", "5", "--scope", "4",
                                      "--iterations", "2", "--output", str(out)])
    evaluate.main()
    detail = list(csv.DictReader(out.open(encoding="utf-8-sig")))
    summary = list(csv.DictReader((tmp_path / "res" / "e_summary.csv").open(encoding="utf-8-sig")))
    assert len(detail) == 5 * 3 and [r["iteration"] for r in summary] == ["0", "1", "2"]
    assert "Precision@K" in capsys.readouterr().out


def test_evaluate_cli_errors(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "DATABASE", tmp_path / "missing.db")
    monkeypatch.setattr(sys, "argv", ["evaluate"])
    with pytest.raises(SystemExit, match="introuvable"):
        evaluate.main()
