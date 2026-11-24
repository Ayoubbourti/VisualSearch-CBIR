"""Application web de bout en bout : authentification, galerie, catégories, transformations, recherche."""
import io
import re
import zipfile

import pytest
from PIL import Image

from tests.conftest import Session, make_image_bytes, register_and_login


def ids_in_db(app, sql="SELECT id FROM images ORDER BY id"):
    from webapp import db as dbl
    conn = dbl.connect(app.config["DATABASE"])
    try:
        return [r[0] for r in conn.execute(sql)]
    finally:
        conn.close()


# ----------------------------- Authentification --------------------------------------
def test_anonymous_is_redirected_to_login(client):
    r = client.get("/")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_api_returns_401_json_when_anonymous(client):
    r = client.post("/api/search", json={}, headers={"X-CSRF-Token": "x"})
    assert r.status_code in (400, 401)                    # CSRF refusé avant l'authentification


def test_register_validation(client):
    s = Session(client)
    assert b"8 caract" in s.post("/register", {"username": "bob", "password": "short"}, follow_redirects=True).data
    assert b"Identifiant" in s.post("/register", {"username": "a b", "password": "longenough1"}, follow_redirects=True).data
    assert b"Compte cr" in s.post("/register", {"username": "bob", "password": "longenough1"}, follow_redirects=True).data
    assert b"existe d" in s.post("/register", {"username": "bob", "password": "longenough1"}, follow_redirects=True).data


def test_login_logout_cycle(client):
    s = register_and_login(client)
    assert s.get("/").status_code == 200
    s.post("/logout")
    assert s.get("/").status_code == 302


def test_wrong_password_is_rejected(client):
    s = Session(client)
    s.post("/register", {"username": "carol", "password": "longenough1"})
    r = s.post("/login", {"username": "carol", "password": "nope"}, follow_redirects=True)
    assert b"incorrects" in r.data and s.get("/").status_code == 302


def test_login_rate_limit_blocks_after_repeated_failures(client):
    s = Session(client)
    s.post("/register", {"username": "dave", "password": "longenough1"})
    for _ in range(3):                                      # TestingConfig.LOGIN_MAX_FAILURES = 3
        s.post("/login", {"username": "dave", "password": "bad"})
    r = s.post("/login", {"username": "dave", "password": "longenough1"})
    assert r.status_code == 429                             # même le bon mot de passe est refusé


def test_open_redirect_is_blocked(client):
    s = Session(client)
    s.post("/register", {"username": "erin", "password": "longenough1"})
    r = s.post("/login?next=https://evil.example/", {"username": "erin", "password": "longenough1"})
    assert r.status_code == 302 and "evil.example" not in r.headers["Location"]
    s.post("/logout")
    r = s.post("/login?next=//evil.example", {"username": "erin", "password": "longenough1"})
    assert "evil.example" not in r.headers["Location"]


# ----------------------------- Import / téléchargement / suppression ------------------
def test_upload_multiple_images_computes_descriptors(gallery, app):
    assert len(ids_in_db(app)) == 6
    assert len(ids_in_db(app, "SELECT image_id FROM descriptors")) == 6
    assert b"red_0.png" in gallery.get("/").data


def test_upload_rejects_bad_extension_and_fake_images(user, app):
    r = user.upload([("notes.txt", b"hello"), ("fake.png", b"not really a png"),
                     ("ok.png", make_image_bytes())])
    assert b"1 image(s) import" in r.data and b"2 fichier(s) rejet" in r.data
    assert len(ids_in_db(app)) == 1


def test_stored_extension_follows_real_format_not_client_name(user, app):
    user.upload([("sneaky.png", make_image_bytes(fmt="JPEG"))])      # JPEG déguisé en .png
    from webapp import db as dbl
    conn = dbl.connect(app.config["DATABASE"])
    stored = conn.execute("SELECT stored_name FROM images").fetchone()[0]
    conn.close()
    assert stored.endswith(".jpg")


def test_decompression_bomb_is_rejected(user, app):
    app.config["MAX_IMAGE_PIXELS"] = 1000
    r = user.upload([("big.png", make_image_bytes(size=(100, 100)))])
    assert b"0 image(s) import" in r.data and len(ids_in_db(app)) == 0


def test_upload_without_api_keeps_image_without_descriptors(user, app, fake_descriptor_api):
    fake_descriptor_api["up"] = False
    r = user.upload([("a.png", make_image_bytes())])
    assert b"injoignable" in r.data
    assert len(ids_in_db(app)) == 1 and len(ids_in_db(app, "SELECT image_id FROM descriptors")) == 0
    fake_descriptor_api["up"] = True
    user.post("/descriptors/refresh")
    assert len(ids_in_db(app, "SELECT image_id FROM descriptors")) == 1


def test_download_single_and_zip(gallery, app):
    ids = ids_in_db(app)
    r = gallery.get(f"/images/{ids[0]}/download")
    assert r.status_code == 200 and "attachment" in r.headers["Content-Disposition"]
    Image.open(io.BytesIO(r.data)).verify()
    z = gallery.post("/images/download-zip", {"ids": ids[:3]})
    names = zipfile.ZipFile(io.BytesIO(z.data)).namelist()
    assert sorted(names) == ["red_0.png", "red_1.png", "red_2.png"]


def test_zip_handles_duplicate_filenames(user, app):
    user.upload([("same.png", make_image_bytes()), ("same.png", make_image_bytes((9, 9, 9)))])
    z = user.post("/images/download-zip", {"ids": ids_in_db(app)})
    assert len(set(zipfile.ZipFile(io.BytesIO(z.data)).namelist())) == 2


def test_delete_multiple_removes_files_and_descriptors(gallery, app, tmp_path):
    ids = ids_in_db(app)
    gallery.post("/images/delete", {"ids": ids[:4]})
    assert ids_in_db(app) == ids[4:]
    assert ids_in_db(app, "SELECT image_id FROM descriptors") == ids[4:]
    files = [p for p in (tmp_path / "storage").rglob("*") if p.is_file() and "thumbs" not in p.parts]
    assert len(files) == 2


def test_delete_parent_image_keeps_derived_image(gallery, app):
    parent = ids_in_db(app)[0]
    gallery.post(f"/image/{parent}/transform", {"op": "grayscale"})
    child = ids_in_db(app)[-1]
    gallery.post("/images/delete", {"ids": [parent]})
    assert child in ids_in_db(app)


# ----------------------------- Isolation entre utilisateurs ---------------------------
def test_users_cannot_access_each_others_images(app):
    a = register_and_login(app.test_client(), "alice", "longenough1")
    a.upload([("secret.png", make_image_bytes())])
    iid = ids_in_db(app)[0]
    b = register_and_login(app.test_client(), "bob", "longenough1")
    for url in (f"/images/{iid}/file", f"/images/{iid}/thumb", f"/images/{iid}/download", f"/image/{iid}"):
        assert b.get(url).status_code == 404, url
    assert b.post("/images/delete", {"ids": [iid]}).status_code == 404
    assert b.post("/images/download-zip", {"ids": [iid]}).status_code == 404
    assert b.post(f"/image/{iid}/transform", {"op": "invert"}).status_code == 404
    assert ids_in_db(app) == [iid]


def test_cannot_use_someone_elses_category(app):
    a = register_and_login(app.test_client(), "alice", "longenough1")
    a.post("/categories", {"name": "Privée"})
    cid = ids_in_db(app, "SELECT id FROM categories")[0]
    b = register_and_login(app.test_client(), "bob", "longenough1")
    assert b.get(f"/?category={cid}").status_code == 404
    assert b.post(f"/categories/{cid}/delete").status_code == 400
    assert ids_in_db(app, "SELECT id FROM categories") == [cid]


# ----------------------------- Catégories ---------------------------------------------
def test_category_hierarchy_and_recursive_filter(user, app):
    user.post("/categories", {"name": "Nature"})
    nature = ids_in_db(app, "SELECT id FROM categories")[0]
    user.post("/categories", {"name": "Montagnes", "parent_id": nature})
    mount = ids_in_db(app, "SELECT id FROM categories WHERE name='Montagnes'")[0]
    user.upload([("m.png", make_image_bytes())], category_id=str(mount))
    user.upload([("n.png", make_image_bytes((1, 2, 3)))], category_id=str(nature))
    parent_view = user.get(f"/?category={nature}").data
    assert b"m.png" in parent_view and b"n.png" in parent_view       # le parent inclut ses sous-catégories
    child_view = user.get(f"/?category={mount}").data
    assert b"m.png" in child_view and b"n.png" not in child_view


def test_rename_move_and_delete_category(user, app):
    user.post("/categories", {"name": "A"})
    user.post("/categories", {"name": "B"})
    a, b = ids_in_db(app, "SELECT id FROM categories ORDER BY id")
    user.post(f"/categories/{a}/rename", {"name": "Alpha"})
    user.post(f"/categories/{a}/move", {"parent_id": b})
    row = ids_in_db(app, f"SELECT parent_id FROM categories WHERE id={a}")
    assert row == [b]
    r = user.post(f"/categories/{b}/move", {"parent_id": a}, follow_redirects=True)    # cycle !
    assert b"sous-cat" in r.data
    assert ids_in_db(app, f"SELECT COALESCE(parent_id,0) FROM categories WHERE id={b}") == [0]
    user.upload([("x.png", make_image_bytes())], category_id=str(a))
    user.post(f"/categories/{b}/delete")                                               # supprime B et A (cascade)
    assert ids_in_db(app, "SELECT id FROM categories") == []
    assert len(ids_in_db(app)) == 1                                                    # l'image est conservée
    assert ids_in_db(app, "SELECT category_id FROM images") == [None]


def test_move_images_between_categories(gallery, app):
    gallery.post("/categories", {"name": "Rouges"})
    cid = ids_in_db(app, "SELECT id FROM categories")[0]
    gallery.post("/images/move", {"ids": ids_in_db(app)[:3], "target_category": cid})
    assert ids_in_db(app, f"SELECT id FROM images WHERE category_id={cid}") == ids_in_db(app)[:3]


def test_gallery_search_filter_is_literal(user, app):
    user.upload([("100%_sure.png", make_image_bytes()), ("other.png", make_image_bytes((5, 5, 5)))])
    r = user.get("/?q=%25_").data                    # « %_ » ne doit pas agir comme joker
    assert b"100%_sure.png" in r and b"other.png" not in r


def test_gallery_pagination(user, app):
    app.config["PAGE_SIZE"] = 2
    user.upload([(f"{i}.png", make_image_bytes((i * 20, 0, 0))) for i in range(5)])
    assert b"Page 1 / 3" in user.get("/").data and b"Page 3 / 3" in user.get("/?page=3").data


# ----------------------------- Transformations ----------------------------------------
@pytest.mark.parametrize("op,params", [
    ("crop", {"x": 0, "y": 0, "w": 20, "h": 10}), ("resize", {"scale": 50}), ("resize", {"width": 32}),
    ("rotate", {"angle": 45}), ("flip_h", {}), ("flip_v", {}), ("grayscale", {}), ("blur", {"radius": 1.5}),
    ("sharpen", {}), ("brightness", {"factor": 1.5}), ("contrast", {"factor": 0.5}),
    ("saturation", {"factor": 2}), ("invert", {})])
def test_every_transformation_creates_a_linked_new_image(user, app, op, params):
    user.upload([("src.png", make_image_bytes(size=(64, 48), noise=30))])
    src = ids_in_db(app)[0]
    r = user.post(f"/image/{src}/transform", {"op": op, **params}, follow_redirects=True)
    assert r.status_code == 200
    ids = ids_in_db(app)
    assert len(ids) == 2                                                     # l'original est conservé
    assert ids_in_db(app, f"SELECT parent_image_id FROM images WHERE id={ids[1]}") == [src]
    assert ids_in_db(app, f"SELECT image_id FROM descriptors WHERE image_id={ids[1]}") == [ids[1]]


def test_transform_changes_dimensions_as_requested(user, app):
    user.upload([("src.png", make_image_bytes(size=(100, 80)))])
    src = ids_in_db(app)[0]
    user.post(f"/image/{src}/transform", {"op": "crop", "x": 10, "y": 10, "w": 30, "h": 20})
    user.post(f"/image/{src}/transform", {"op": "resize", "scale": 50})
    sizes = ids_in_db(app, "SELECT width*1000+height FROM images WHERE parent_image_id IS NOT NULL ORDER BY id")
    assert sizes == [30020, 50040]


@pytest.mark.parametrize("op,params", [
    ("crop", {"x": 50, "y": 0, "w": 100, "h": 10}), ("resize", {}), ("resize", {"scale": "abc"}),
    ("blur", {"radius": 9999}), ("brightness", {"factor": "nan"}), ("resize", {"scale": 100000}),
    ("unknown", {})])
def test_invalid_transform_parameters_are_refused(user, app, op, params):
    user.upload([("src.png", make_image_bytes(size=(64, 48)))])
    r = user.post(f"/image/{ids_in_db(app)[0]}/transform", {"op": op, **params}, follow_redirects=True)
    assert r.status_code == 200 and len(ids_in_db(app)) == 1


# ----------------------------- Détail & descripteurs ----------------------------------
def test_detail_page_shows_descriptors_and_derivatives(gallery, app):
    iid = ids_in_db(app)[0]
    gallery.post(f"/image/{iid}/transform", {"op": "invert"})
    html = gallery.get(f"/image/{iid}").data.decode()
    assert "descriptors-data" in html and "Moments de couleur" in html and "Images dérivées" in html
    assert "<script>" not in html.replace('<script src', '')            # aucun script inline (CSP)


def test_dashboard_stats(gallery):
    html = gallery.get("/dashboard").data.decode()
    assert "Images indexées" in html and "100.0 % avec descripteurs" in html


# ----------------------------- Recherche CBIR -----------------------------------------
def test_search_page_requires_own_image(gallery, app):
    assert gallery.get(f"/search?query_id={ids_in_db(app)[0]}").status_code == 200
    assert gallery.get("/search?query_id=99999").status_code == 404


def test_simple_search_api(gallery, app):
    qid = ids_in_db(app)[0]
    r = gallery.json_post("/api/search", {"query_id": qid, "k": 4})
    j = r.get_json()
    assert r.status_code == 200 and j["iteration"] == 0 and len(j["results"]) == 4
    assert qid not in [x["id"] for x in j["results"]]
    assert {"thumb", "url", "distance", "rank"} <= set(j["results"][0])


def test_similar_images_rank_first(gallery, app):
    """Les deux autres images rouges (peu bruitées) doivent précéder les images bleues très texturées."""
    ids = ids_in_db(app)
    j = gallery.json_post("/api/search", {"query_id": ids[0], "k": 5}).get_json()
    assert {x["id"] for x in j["results"][:2]} == {ids[1], ids[2]}


def test_feedback_api_roundtrip(gallery, app):
    ids = ids_in_db(app)
    first = gallery.json_post("/api/search", {"query_id": ids[0], "k": 5}).get_json()
    shown = [x["id"] for x in first["results"]]
    r = gallery.json_post("/api/feedback", {"query_id": ids[0], "k": 5, "iteration": 0,
                                            "relevant_ids": [ids[1], ids[2]], "retrieved_ids": shown})
    j = r.get_json()
    assert r.status_code == 200 and j["iteration"] == 1 and j["updated"] is True and j["n_relevant"] == 3
    assert set(j["weights"]) == {"Histogramme couleur", "Moments de couleur", "GLCM (texture)", "LBP (texture)"}


def test_feedback_without_relevant_image_is_422(gallery, app):
    ids = ids_in_db(app)
    r = gallery.json_post("/api/feedback", {"query_id": ids[0], "relevant_ids": [], "retrieved_ids": [ids[1]]})
    assert r.status_code == 422 and "pertinente" in r.get_json()["error"]


@pytest.mark.parametrize("payload", [{}, {"query_id": "abc"}, {"query_id": 424242}, [1, 2]])
def test_search_api_validates_input(gallery, payload):
    r = gallery.json_post("/api/search", payload)
    assert r.status_code in (400, 404)


def test_search_needs_descriptors(user, app, fake_descriptor_api):
    fake_descriptor_api["up"] = False
    user.upload([("a.png", make_image_bytes()), ("b.png", make_image_bytes((9, 9, 9)))])
    r = user.json_post("/api/search", {"query_id": ids_in_db(app)[0]})
    assert r.status_code == 400 and "Descripteurs manquants" in r.get_json()["error"]


def test_invalid_k_falls_back_to_default_and_k_is_capped(gallery, app):
    qid = ids_in_db(app)[0]
    assert len(gallery.json_post("/api/search", {"query_id": qid, "k": "x"}).get_json()["results"]) == 5   # 6 images - requête
    assert len(gallery.json_post("/api/search", {"query_id": qid, "k": 10**9}).get_json()["results"]) == 5


# ----------------------------- Interface (tri, teintes) -------------------------------
def test_gallery_sort_options(user, app):
    user.upload([("b.png", make_image_bytes((10, 10, 10), size=(10, 10))),
                 ("a.png", make_image_bytes((200, 10, 10), size=(60, 60), noise=50))])
    by_name = user.get("/?sort=name").data.decode()
    assert by_name.index("a.png") < by_name.index("b.png")
    by_size = user.get("/?sort=size").data.decode()
    assert by_size.index("a.png") < by_size.index("b.png")
    assert user.get("/?sort=injection;DROP").status_code == 200          # valeur inconnue -> tri par défaut


def test_dashboard_hue_spectrum_reflects_image_colors(user, app):
    user.upload([(f"red_{i}.png", make_image_bytes((230, 20, 20), noise=5, seed=i)) for i in range(3)])
    html = user.get("/dashboard").data.decode()
    assert "Les couleurs de votre galerie" in html and "Rouge-orange" in html
    from webapp.blueprints.gallery import hue_distribution
    from webapp import db as dbl
    conn = dbl.connect(app.config["DATABASE"])
    hues, neutral = hue_distribution(conn, 1)
    conn.close()
    # la teinte est circulaire : le rouge pur se répartit entre la 1re et la dernière tranche
    assert hues[0]["pct"] + hues[7]["pct"] > 90 and abs(sum(h["pct"] for h in hues) - 100) < 1 and 0 <= neutral <= 100


def test_dashboard_empty_state_and_theme_assets(user):
    html = user.get("/dashboard").data.decode()
    assert "Pas encore de couleurs" in html and "theme.js" in html
    assert user.get("/static/fonts/sora-latin-wght-normal.woff2").status_code == 200
