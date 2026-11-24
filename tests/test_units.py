"""Tests unitaires : transformations, base de données, stockage, script d'évaluation."""
import sys
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from tests.conftest import make_image_bytes
from webapp import db as dbl
from webapp.services import imagestore, transforms

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import evaluate  # noqa: E402


# ----------------------------- transformations ---------------------------------------
def img(w=40, h=30):
    return Image.new("RGB", (w, h), (10, 20, 30))


def test_crop_resize_rotate_dimensions():
    assert transforms.apply(img(), "crop", {"x": 5, "y": 5, "w": 10, "h": 8}).size == (10, 8)
    assert transforms.apply(img(), "resize", {"scale": 200}).size == (80, 60)
    assert transforms.apply(img(), "resize", {"height": 15}).size == (20, 15)         # ratio conservé
    assert transforms.apply(img(), "rotate", {"angle": 90}).size == (30, 40)


def test_transform_never_modifies_source():
    src = img()
    before = src.tobytes()
    transforms.apply(src, "invert", {})
    assert src.tobytes() == before


def test_invert_and_grayscale_values():
    assert transforms.apply(img(), "invert", {}).getpixel((0, 0)) == (245, 235, 225)
    r, g, b = transforms.apply(img(), "grayscale", {}).getpixel((0, 0))
    assert r == g == b


def test_resize_cap_on_total_pixels():
    with pytest.raises(ValueError):
        transforms.apply(img(), "resize", {"width": 9000, "height": 9000})


def test_exif_orientation_is_applied():
    base = Image.new("RGB", (40, 20))
    exif = base.getexif(); exif[0x0112] = 6                       # rotation 90° horaire
    buf = BytesIO(); base.save(buf, "JPEG", exif=exif); buf.seek(0)
    assert transforms.apply(Image.open(buf), "flip_h", {}).size == (20, 40)


# ----------------------------- stockage ----------------------------------------------
def test_save_stream_validates_and_names_files(tmp_path):
    name = imagestore.save_stream(tmp_path, 1, BytesIO(make_image_bytes(fmt="JPEG")), "../x.png")
    assert name.endswith(".jpg") and (tmp_path / "1" / name).exists()
    with pytest.raises(imagestore.InvalidImage):
        imagestore.save_stream(tmp_path, 1, BytesIO(b"junk"), "a.png")
    with pytest.raises(imagestore.InvalidImage):
        imagestore.save_stream(tmp_path, 1, BytesIO(make_image_bytes(size=(50, 50))), "a.png", max_pixels=100)


def test_thumbnail_and_delete(tmp_path):
    name = imagestore.save_stream(tmp_path, 1, BytesIO(make_image_bytes(size=(600, 300))), "a.png")
    t = imagestore.thumb_path(tmp_path, 1, name)
    imagestore.make_thumb(tmp_path / "1" / name, t)
    assert max(Image.open(t).size) == 256
    imagestore.delete_files(tmp_path, 1, name)
    assert not t.exists() and not (tmp_path / "1" / name).exists()


# ----------------------------- base de données ---------------------------------------
@pytest.fixture
def conn(tmp_path):
    dbl.init_db(tmp_path / "t.db")
    c = dbl.connect(tmp_path / "t.db")
    c.execute("INSERT INTO users(username, password_hash) VALUES ('u','h')")
    c.commit()
    yield c
    c.close()


def test_init_db_is_idempotent_and_versioned(tmp_path):
    for _ in range(2):
        dbl.init_db(tmp_path / "x.db")
    c = dbl.connect(tmp_path / "x.db")
    assert c.execute("PRAGMA user_version").fetchone()[0] == dbl.SCHEMA_VERSION
    assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_category_tree_path_and_descendants(conn):
    a = dbl.get_or_create_category(conn, 1, "A")
    b = dbl.get_or_create_category(conn, 1, "B", a)
    c = dbl.get_or_create_category(conn, 1, "C", b)
    assert dbl.get_or_create_category(conn, 1, "A") == a                      # pas de doublon
    assert sorted(dbl.descendant_ids(conn, a)) == [a, b, c]
    assert [x["name"] for x in dbl.category_path(conn, c)] == ["A", "B", "C"]
    assert [n["name"] for n in dbl.category_tree(conn, 1)[0]["children"]] == ["B"]
    assert [label for _, label in dbl.flatten_tree(dbl.category_tree(conn, 1))][-1].endswith("C")


def test_move_category_rejects_cycles(conn):
    a = dbl.get_or_create_category(conn, 1, "A")
    b = dbl.get_or_create_category(conn, 1, "B", a)
    with pytest.raises(ValueError):
        dbl.move_category(conn, 1, a, b)
    with pytest.raises(ValueError):
        dbl.move_category(conn, 1, a, a)
    dbl.move_category(conn, 1, b, None)
    assert conn.execute("SELECT parent_id FROM categories WHERE id=?", (b,)).fetchone()[0] is None


def test_format_stats_handles_multiple_dots(conn):
    for n in ("a.b.jpg", "c.JPG", "d.png"):
        dbl.insert_image(conn, 1, n, n, 1, 1, 1)
    assert dbl.format_stats(conn, 1) == [("jpg", 2), ("png", 1)]


def test_cascade_delete_image_removes_descriptor(conn):
    iid = dbl.insert_image(conn, 1, "a.png", "a", 1, 1, 1)
    dbl.save_descriptor(conn, iid, {"vector": [0.0] * 97, "color": {}, "texture": {}})
    conn.execute("DELETE FROM images WHERE id=?", (iid,))
    assert conn.execute("SELECT COUNT(*) FROM descriptors").fetchone()[0] == 0


# ----------------------------- évaluation --------------------------------------------
LABELS = {1: "a", 2: "a", 3: "a", 4: "b", 5: "b", 6: "a"}


def test_metrics_perfect_ranking():
    m = evaluate.ranking_metrics([2, 3, 6], 1, "a", LABELS, 3)
    assert m["precision_at_k"] == 1.0 and m["map_at_k"] == 1.0 and m["ndcg_at_k"] == pytest.approx(1.0)
    assert m["recall_at_k"] == pytest.approx(3 / 3)


def test_metrics_worst_ranking_and_known_values():
    assert evaluate.ranking_metrics([4, 5], 1, "a", LABELS, 2)["precision_at_k"] == 0.0
    m = evaluate.ranking_metrics([4, 2, 5, 3], 1, "a", LABELS, 4)                   # pertinents aux rangs 2 et 4
    assert m["precision_at_k"] == 0.5
    assert m["map_at_k"] == pytest.approx((1 / 2 + 2 / 4) / 3)                      # 3 pertinents au total, K=4
    dcg = 1 / np.log2(3) + 1 / np.log2(5)
    idcg = 1 + 1 / np.log2(3) + 1 / np.log2(4)
    assert m["ndcg_at_k"] == pytest.approx(dcg / idcg)


def test_metrics_ignore_query_and_handle_empty():
    assert evaluate.ranking_metrics([1, 2], 1, "a", LABELS, 5)["precision_at_k"] == 1.0   # requête ignorée
    assert evaluate.ranking_metrics([], 1, "a", LABELS, 5) == dict.fromkeys(evaluate.METRICS, 0.0)


def _synthetic_space(n_per=40, groups=4, seed=0):
    from webapp.services.retrieval import DIM, FeatureSpace
    rng = np.random.default_rng(seed)
    X, labels = [], {}
    for g in range(groups):
        centre = np.zeros(DIM); centre[g * 10:(g + 1) * 10 + 5] = 1.5          # dimensions informatives du groupe
        X.append(rng.normal(centre, 1.0, (n_per, DIM)))
        labels.update({g * n_per + i: g for i in range(n_per)})
    return FeatureSpace(range(groups * n_per), np.vstack(X)), labels


def test_run_query_produces_all_iterations_and_improves_on_average():
    space, labels = _synthetic_space()
    queries = evaluate.select_queries(labels, 20, seed=1)
    rows = [r for q in queries for r in evaluate.run_query(space, q, labels, 15, 3, 20.0)]
    summary = evaluate.summarize(rows, 3)
    assert [s["iteration"] for s in summary] == [0, 1, 2, 3] and all(s["n_queries"] == 20 for s in summary)
    assert summary[-1]["precision_at_k"] > summary[0]["precision_at_k"]           # le retour de pertinence aide


def test_strict_protocol_counts_only_new_images():
    space, labels = _synthetic_space()
    q = evaluate.select_queries(labels, 1, seed=2)[0]
    rows = evaluate.run_query(space, q, labels, 10, 2, 20.0, exclude_judged=True)
    assert len(rows) == 3 and all(0 <= r["precision_at_k"] <= 1 for r in rows)


def test_select_queries_is_reproducible_and_skips_singletons():
    labels = {i: i % 3 for i in range(30)}
    labels[99] = "lonely"
    a, b = evaluate.select_queries(labels, 10, 7), evaluate.select_queries(labels, 10, 7)
    assert a == b and 99 not in a
