"""Tableau de bord, galerie paginée et hiérarchie de catégories."""
import numpy as np
from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for)

from webapp import db as dbl
from webapp.core import back, get_db, login_required, parse_category
from webapp.services import api_client

bp = Blueprint("gallery", __name__)


def _like_escape(text: str) -> str:
    """Échappe % et _ pour que la recherche par nom soit littérale."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


HUE_NAMES = ["Rouge-orange", "Jaune", "Vert clair", "Vert-cyan", "Cyan-bleu", "Bleu", "Violet", "Rose-rouge"]
SORTS = {"new": "id DESC", "old": "id ASC", "name": "filename COLLATE NOCASE ASC", "size": "size_bytes DESC"}


def hue_distribution(conn, user_id, limit=3000):
    """Répartition des teintes de la galerie, calculée à partir des histogrammes HSV (8 teintes × 3 × 3).

    Seuls les pixels chromatiques comptent (saturation et valeur non minimales) : le gris, le noir et le
    blanc n'ont pas de teinte. Retourne ([{name, pct, color}], part_de_pixels_neutres_en_%)."""
    rows = conn.execute("""SELECT d.vector FROM descriptors d JOIN images i ON i.id = d.image_id
                           WHERE i.user_id = ? ORDER BY d.image_id DESC LIMIT ?""", (user_id, limit)).fetchall()
    if not rows:
        return [], 0.0
    hist = np.vstack([np.frombuffer(r["vector"], dtype=np.float32)[:72] for r in rows]).reshape(-1, 8, 3, 3)
    chromatic = hist[:, :, 1:, 1:].sum(axis=(0, 2, 3))
    total_mass = hist.sum()
    if chromatic.sum() <= 0:
        return [], 100.0
    shares = chromatic / chromatic.sum() * 100
    hues = [{"name": HUE_NAMES[k], "pct": round(float(shares[k]), 1),
             "color": f"hsl({(k + 0.5) * 45:.0f}, 82%, 58%)"} for k in range(8)]
    return hues, round(float(100 * (1 - chromatic.sum() / total_mass)), 1)


@bp.get("/dashboard")
@login_required
def dashboard():
    db, uid = get_db(), g.user["id"]
    one = lambda sql: db.execute(sql, (uid,)).fetchone()[0]      # noqa: E731
    total = one("SELECT COUNT(*) FROM images WHERE user_id=?")
    indexed = one("SELECT COUNT(*) FROM descriptors d JOIN images i ON i.id=d.image_id WHERE i.user_id=?")
    categories = one("SELECT COUNT(*) FROM categories WHERE user_id=?")
    total_bytes = one("SELECT COALESCE(SUM(size_bytes),0) FROM images WHERE user_id=?")
    recent = db.execute("SELECT id, filename, width, height FROM images WHERE user_id=? ORDER BY id DESC LIMIT 8",
                        (uid,)).fetchall()
    hues, neutral_pct = hue_distribution(db, uid)
    return render_template("dashboard.html", hues=hues, neutral_pct=neutral_pct, total=total, indexed=indexed, categories=categories,
                           total_bytes=total_bytes, formats=dbl.format_stats(db, uid), recent=recent,
                           api_up=api_client.is_up(current_app.config["API_URL"]),
                           api_port=current_app.config["API_URL"].rsplit(":", 1)[-1])


@bp.route("/")
@login_required
def index():
    db, uid = get_db(), g.user["id"]
    cat = request.args.get("category", "")                     # "", "none" ou id numérique
    page = max(request.args.get("page", 1, type=int), 1)
    where, params = ["user_id=?"], [uid]
    current_cat, crumbs = None, []
    if cat == "none":
        where.append("category_id IS NULL")
    elif cat.isdigit():
        current_cat = int(cat)
        if not db.execute("SELECT 1 FROM categories WHERE id=? AND user_id=?", (current_cat, uid)).fetchone():
            abort(404)
        crumbs = dbl.category_path(db, current_cat)
        ids = dbl.descendant_ids(db, current_cat)              # inclut les sous-catégories
        where.append(f"category_id IN ({','.join('?' * len(ids))})")
        params += ids
    q = request.args.get("q", "").strip()
    if q:
        where.append("filename LIKE ? ESCAPE '\\'")
        params.append(f"%{_like_escape(q)}%")
    sort = request.args.get("sort", "new")
    sort = sort if sort in SORTS else "new"
    clause = " AND ".join(where)
    size = current_app.config["PAGE_SIZE"]
    total = db.execute(f"SELECT COUNT(*) FROM images WHERE {clause}", params).fetchone()[0]
    images = db.execute(f"""SELECT i.*, EXISTS(SELECT 1 FROM descriptors d WHERE d.image_id=i.id) AS has_desc
                            FROM images i WHERE {clause} ORDER BY {SORTS[sort]} LIMIT ? OFFSET ?""",
                        params + [size, (page - 1) * size]).fetchall()
    tree = dbl.category_tree(db, uid)
    return render_template("gallery.html", images=images, total=total, page=page,
                           pages=max((total + size - 1) // size, 1), tree=tree,
                           flat_cats=dbl.flatten_tree(tree), cat=cat, current_cat=current_cat,
                           crumbs=crumbs, q=q, sort=sort, api_up=api_client.is_up(current_app.config["API_URL"]))


# ----------------------------- Catégories --------------------------------- #
@bp.post("/categories")
@login_required
def create_category():
    name = request.form.get("name", "").strip()[:80]
    if name:
        dbl.get_or_create_category(get_db(), g.user["id"], name, parse_category(request.form.get("parent_id")))
        get_db().commit()
    return back()


@bp.post("/categories/<int:cid>/rename")
@login_required
def rename_category(cid):
    parse_category(str(cid))
    name = request.form.get("name", "").strip()[:80] or "Sans nom"
    get_db().execute("UPDATE categories SET name=? WHERE id=? AND user_id=?", (name, cid, g.user["id"]))
    get_db().commit()
    return redirect(url_for("gallery.index", category=cid))


@bp.post("/categories/<int:cid>/move")
@login_required
def move_category(cid):
    """Rattache la catégorie à un autre parent (ou à la racine) en refusant les cycles."""
    parse_category(str(cid))
    try:
        dbl.move_category(get_db(), g.user["id"], cid, parse_category(request.form.get("parent_id")))
        get_db().commit()
        flash("Catégorie déplacée.", "success")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("gallery.index", category=cid))


@bp.post("/categories/<int:cid>/delete")
@login_required
def delete_category(cid):
    parse_category(str(cid))
    get_db().execute("DELETE FROM categories WHERE id=? AND user_id=?", (cid, g.user["id"]))  # cascade sur les enfants
    get_db().commit()
    flash("Catégorie supprimée (ses images sont conservées, sans catégorie).", "success")
    return redirect(url_for("gallery.index"))


@bp.post("/images/move")
@login_required
def move_images():
    from webapp.core import own_image
    ids = request.form.getlist("ids", type=int)
    target = parse_category(request.form.get("target_category"))
    for i in ids:
        own_image(i)
        get_db().execute("UPDATE images SET category_id=? WHERE id=?", (target, i))
    get_db().commit()
    flash(f"{len(ids)} image(s) déplacée(s).", "success")
    return back()
