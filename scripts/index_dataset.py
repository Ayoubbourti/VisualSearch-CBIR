"""
Importe en masse un dossier d'images (ex. GHIM-10K) dans la galerie d'un utilisateur et calcule leurs
descripteurs EN PARALLÈLE (appel direct du module api/descriptors.py : plus rapide que 10 000 appels HTTP ;
les valeurs sont strictement identiques à celles de l'API REST).

Catégories créées :
  * dossier avec sous-dossiers -> la hiérarchie de dossiers devient la hiérarchie de catégories ;
  * dossier plat + --group-size N -> « Classe 00 », « Classe 01 »... (images triées par numéro,
    N images par classe : GHIM-10K = 500 images par classe, d'où le défaut 500).

Exemple :
  python scripts/index_dataset.py --folder ~/data/ghim-10k --username admin --password secret123
Le script est relançable : les images déjà importées (même chemin relatif) sont ignorées.
"""
import argparse
import re
import sys
import hashlib
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import cpu_count
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from werkzeug.security import generate_password_hash  # noqa: E402
from webapp import db as dbl                           # noqa: E402
from webapp.config import Config                      # noqa: E402
from webapp.services import imagestore                 # noqa: E402
from api import descriptors                            # noqa: E402

EXTS = Config.ALLOWED_EXTENSIONS


def _compute(path):
    """Exécuté dans un processus fils : renvoie (chemin, résultat | None)."""
    try:
        return path, descriptors.compute_all(path)
    except Exception as exc:
        print(f"  ! {path}: {exc}")
        return path, None


def natural_key(p: Path):
    """Tri « naturel » : 2.jpg avant 10.jpg (indispensable pour découper GHIM-10K par numéro)."""
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", p.name)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--folder", required=True, type=Path)
    ap.add_argument("--username", default="admin")
    ap.add_argument("--password", default="admin123", help="utilisé seulement si le compte doit être créé")
    ap.add_argument("--group-size", type=int, default=500, help="images par classe si le dossier est plat (0 = pas de classe)")
    ap.add_argument("--workers", type=int, default=min(3, max(1, cpu_count() - 1)),
                    help="processus parallèles (défaut prudent : max 3, pour limiter la RAM)")
    ap.add_argument("--limit", type=int, default=0, help="ne traiter que N images (test rapide)")
    a = ap.parse_args()

    dbl.init_db(Config.DATABASE)
    conn = dbl.connect(Config.DATABASE)
    user = conn.execute("SELECT id FROM users WHERE username=?", (a.username,)).fetchone()
    if user is None:
        cur = conn.execute("INSERT INTO users(username, password_hash) VALUES (?,?)",
                           (a.username, generate_password_hash(a.password)))
        conn.commit()
        uid = cur.lastrowid
        print(f"Compte créé : {a.username}")
    else:
        uid = user["id"]

    files = sorted((p for p in a.folder.rglob("*") if p.suffix.lower() in EXTS), key=lambda p: (p.parent, natural_key(p)))
    if a.limit:
        files = files[:a.limit]
    done = {r[0] for r in conn.execute("SELECT filename FROM images WHERE user_id=?", (uid,))}
    todo = []
    for idx, p in enumerate(files):
        rel = p.relative_to(a.folder).as_posix()
        if rel in done:
            continue
        # Catégorie : sous-dossiers, sinon découpage par numéro.
        if p.parent != a.folder:
            parent = None
            for part in p.parent.relative_to(a.folder).parts:
                parent = dbl.get_or_create_category(conn, uid, part, parent)
            cat = parent
        elif a.group_size:
            # Le découpage suit l'ordre naturel des fichiers (0.jpg, 1.jpg, 10.jpg...).
            # Il suppose que cet ordre regroupe effectivement les classes du dataset.
            cat = dbl.get_or_create_category(conn, uid, f"Classe {idx // a.group_size:02d}")
        else:
            cat = None
        todo.append((p, rel, cat))
    print(f"{len(files)} image(s) trouvée(s), {len(todo)} à importer.")
    print(f"Calcul parallèle avec {max(1, a.workers)} worker(s). Pour un PC avec 8 Go RAM, "
          "commencez avec --workers 2.")

    # Calcul parallèle des descripteurs, puis insertion séquentielle (SQLite = un seul écrivain).
    with ProcessPoolExecutor(max_workers=max(1, a.workers)) as pool:
        results = pool.map(_compute, [str(t[0]) for t in todo], chunksize=8)
        for n, ((p, rel, cat), (_, res)) in enumerate(zip(todo, results, strict=True), 1):
            if res is None:
                continue
            # Nom déterministe et sans collision, même si deux dossiers contiennent "image.jpg".
            digest = hashlib.sha1(rel.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
            stored = f"{digest}_{Path(rel).name}"
            dest = imagestore.user_dir(Config.STORAGE_DIR, uid) / stored
            dest.write_bytes(p.read_bytes())
            imagestore.make_thumb(dest, imagestore.thumb_path(Config.STORAGE_DIR, uid, stored), Config.THUMB_SIZE)
            w, h, size = imagestore.image_info(dest)
            iid = dbl.insert_image(conn, uid, rel, stored, w, h, size, cat)
            dbl.save_descriptor(conn, iid, res)
            if n % 200 == 0:
                conn.commit()
                print(f"  {n}/{len(todo)}")
    conn.commit()
    print("Terminé.")


if __name__ == "__main__":
    main()
