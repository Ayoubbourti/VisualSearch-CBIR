"""Fichiers : import, téléchargement, suppression, page de détail, transformations, descripteurs."""
import io
import json
import zipfile
from pathlib import Path

from flask import (Blueprint, current_app, flash, g, redirect, render_template, request, send_file, url_for)
from PIL import Image

from webapp import db as dbl
from webapp.core import back, get_db, image_path, login_required, own_image, parse_category
from webapp.services import api_client, imagestore, transforms

bp = Blueprint("images", __name__)


# --------------------------------------------------------------------------- #
# Fonctions internes
# --------------------------------------------------------------------------- #
def _storage():
    return current_app.config["STORAGE_DIR"]


def ingest(items):
    """Calcule via l'API REST les descripteurs d'une liste de (image_id, chemin) et les enregistre.
    Retourne (nb_ok, nb_échecs). Si l'API est arrêtée, l'image reste dans la galerie sans descripteurs
    (le bouton « Calculer les descripteurs manquants » permet de rattraper)."""
    cfg, ok, fail = current_app.config, 0, 0
    step = cfg["API_BATCH_SIZE"]
    for s in range(0, len(items), step):
        chunk = items[s:s + step]
        try:
            results = api_client.compute_descriptors([p for _, p in chunk], cfg["API_URL"],
                                                     cfg["API_TIMEOUT"], cfg["API_KEY"])
        except api_client.ApiUnavailable as exc:
            current_app.logger.warning("API de descripteurs indisponible : %s", exc)
            get_db().commit()
            return ok, fail + len(items) - s
        for (image_id, _), res in zip(chunk, results, strict=True):
            if "error" in res:
                fail += 1
            else:
                dbl.save_descriptor(get_db(), image_id, res)
                ok += 1
    get_db().commit()
    return ok, fail


def register_file(stored_name, original_name, category_id, parent_id=None) -> int:
    """Crée la ligne `images` + la vignette pour un fichier déjà écrit sur disque."""
    path = imagestore.user_dir(_storage(), g.user["id"]) / stored_name
    w, h, size = imagestore.image_info(path)
    imagestore.make_thumb(path, imagestore.thumb_path(_storage(), g.user["id"], stored_name),
                          current_app.config["THUMB_SIZE"])
    return dbl.insert_image(get_db(), g.user["id"], original_name, stored_name, w, h, size, category_id, parent_id)


# --------------------------------------------------------------------------- #
# Import / téléchargement / suppression
# --------------------------------------------------------------------------- #
@bp.post("/upload")
@login_required
def upload():
    cfg = current_app.config
    category_id = parse_category(request.form.get("category_id"))
    to_process, rejected = [], []
    for f in request.files.getlist("files"):
        name = Path(f.filename or "").name
        if Path(name).suffix.lower() not in cfg["ALLOWED_EXTENSIONS"]:
            rejected.append(name or "?")
            continue
        try:
            stored = imagestore.save_stream(_storage(), g.user["id"], f.stream, name, cfg["MAX_IMAGE_PIXELS"])
        except imagestore.InvalidImage as exc:
            current_app.logger.info("Import refusé (%s) : %s", name, exc)
            rejected.append(name)
            continue
        image_id = register_file(stored, name, category_id)
        to_process.append((image_id, imagestore.user_dir(_storage(), g.user["id"]) / stored))
    get_db().commit()
    ok, fail = ingest(to_process)
    msg = f"{len(to_process)} image(s) importée(s), descripteurs calculés pour {ok}."
    if rejected:
        shown = ", ".join(rejected[:3]) + ("…" if len(rejected) > 3 else "")
        msg += f" {len(rejected)} fichier(s) rejeté(s) ({shown})."
    if fail:
        msg += " ⚠ API de descripteurs injoignable ou en erreur pour certaines images."
    flash(msg, "warning" if fail or rejected else "success")
    return back()


@bp.get("/images/<int:iid>/file")
@login_required
def image_file(iid):
    return send_file(image_path(own_image(iid)), max_age=3600)


@bp.get("/images/<int:iid>/thumb")
@login_required
def image_thumb(iid):
    row = own_image(iid)
    t = imagestore.thumb_path(_storage(), g.user["id"], row["stored_name"])
    return send_file(t if t.exists() else image_path(row), max_age=86400)


@bp.get("/images/<int:iid>/download")
@login_required
def image_download(iid):
    row = own_image(iid)
    return send_file(image_path(row), as_attachment=True, download_name=row["filename"])


@bp.post("/images/download-zip")
@login_required
def download_zip():
    """Télécharge un ensemble d'images dans une archive ZIP (construite en mémoire)."""
    ids = request.form.getlist("ids", type=int)
    if not ids:
        flash("Aucune image sélectionnée.", "error")
        return back()
    buf, used = io.BytesIO(), set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:     # JPEG/PNG déjà compressés
        for i in ids:
            row = own_image(i)
            name, n = Path(row["filename"]).name, 1             # .name : aucun chemin dans l'archive
            while name in used:                                  # noms uniques dans l'archive
                name, n = f"{Path(row['filename']).stem}_{n}{Path(row['filename']).suffix}", n + 1
            used.add(name)
            z.write(image_path(row), name)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="galerie.zip", mimetype="application/zip")


@bp.post("/images/delete")
@login_required
def delete_images():
    ids = request.form.getlist("ids", type=int)
    for i in ids:
        row = own_image(i)
        imagestore.delete_files(_storage(), g.user["id"], row["stored_name"])
        get_db().execute("DELETE FROM images WHERE id=?", (i,))  # descripteurs supprimés en cascade
    get_db().commit()
    flash(f"{len(ids)} image(s) supprimée(s).", "success")
    ref = request.referrer or ""
    return redirect(url_for("gallery.index")) if "/image/" in ref else back()


# --------------------------------------------------------------------------- #
# Détail & transformations
# --------------------------------------------------------------------------- #
@bp.get("/image/<int:iid>")
@login_required
def image_detail(iid):
    db, row = get_db(), own_image(iid)
    d = db.execute("SELECT details FROM descriptors WHERE image_id=?", (iid,)).fetchone()
    tree = dbl.category_tree(db, g.user["id"])
    parent = db.execute("SELECT id, filename FROM images WHERE id=?", (row["parent_image_id"],)).fetchone() \
        if row["parent_image_id"] else None
    children = db.execute("SELECT id, filename FROM images WHERE parent_image_id=? AND user_id=? ORDER BY id",
                          (iid, g.user["id"])).fetchall()
    return render_template("image.html", img=row, details=json.loads(d["details"]) if d else None,
                           flat_cats=dbl.flatten_tree(tree), parent=parent, children=children,
                           crumbs=dbl.category_path(db, row["category_id"]) if row["category_id"] else [])


@bp.post("/image/<int:iid>/transform")
@login_required
def transform(iid):
    """Crée une NOUVELLE image = transformation de l'image existante (l'original est conservé)."""
    row, op = own_image(iid), request.form.get("op", "")
    try:
        with Image.open(image_path(row)) as src:
            result = transforms.apply(src.copy(), op, request.form)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("images.image_detail", iid=iid))
    stored = imagestore.save_pil(_storage(), g.user["id"], result)
    new_name = f"{Path(row['filename']).stem}_{op}{Path(stored).suffix}"
    new_id = register_file(stored, new_name, row["category_id"], parent_id=iid)
    get_db().commit()
    ingest([(new_id, imagestore.user_dir(_storage(), g.user["id"]) / stored)])
    flash(f"Nouvelle image créée : {new_name}", "success")
    return redirect(url_for("images.image_detail", iid=new_id))


@bp.post("/descriptors/refresh")
@login_required
def refresh_descriptors():
    """Calcule les descripteurs des images qui n'en ont pas encore (API arrêtée lors de l'import...)."""
    rows = get_db().execute("""SELECT i.* FROM images i LEFT JOIN descriptors d ON d.image_id=i.id
                               WHERE i.user_id=? AND d.image_id IS NULL""", (g.user["id"],)).fetchall()
    ok, fail = ingest([(r["id"], image_path(r)) for r in rows])
    flash(f"Descripteurs calculés : {ok} ; échecs : {fail}.", "warning" if fail else "success")
    return back()
