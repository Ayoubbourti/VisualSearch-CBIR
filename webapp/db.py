"""
Couche d'accès SQLite : schéma, utilitaires et requêtes sur la hiérarchie de catégories.
Toutes les fonctions prennent une connexion `conn` -> utilisables hors Flask (scripts).
"""
import json
import sqlite3
from pathlib import Path

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
-- Hiérarchie de catégories : liste d'adjacence (parent_id). Supprimer un parent supprime ses enfants.
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    parent_id INTEGER REFERENCES categories(id) ON DELETE CASCADE
);
-- Une image appartient à (au plus) une catégorie ; supprimer la catégorie "désclasse" l'image.
CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    parent_image_id INTEGER REFERENCES images(id) ON DELETE SET NULL,  -- image source d'une transformation
    filename TEXT NOT NULL,            -- nom d'origine (affiché)
    stored_name TEXT NOT NULL,         -- nom unique sur disque
    width INTEGER, height INTEGER, size_bytes INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_images_user_cat ON images(user_id, category_id);
-- Descripteurs : vecteur global (float32 binaire, pour la recherche) + détails JSON (pour l'affichage).
CREATE TABLE IF NOT EXISTS descriptors (
    image_id INTEGER PRIMARY KEY REFERENCES images(id) ON DELETE CASCADE,
    vector BLOB NOT NULL,
    details TEXT NOT NULL
);
"""


# Version du schéma, stockée dans PRAGMA user_version. Les migrations ne font QUE des ajouts
# compatibles (index) : une base indexée avec une ancienne version du projet reste utilisable.
SCHEMA_VERSION = 2
MIGRATIONS = {
    2: """CREATE INDEX IF NOT EXISTS idx_images_parent ON images(parent_image_id);
          CREATE INDEX IF NOT EXISTS idx_images_user_filename ON images(user_id, filename);
          CREATE INDEX IF NOT EXISTS idx_categories_user_parent ON categories(user_id, parent_id);""",
}


def connect(path) -> sqlite3.Connection:
    """Ouvre une connexion SQLite configurée pour un usage web concurrent.

    * clés étrangères activées (désactivées par défaut dans SQLite !) ;
    * mode WAL : les lectures ne bloquent pas l'écriture (galerie + indexation simultanées) ;
    * busy_timeout : attend jusqu'à 10 s au lieu d'échouer immédiatement sur « database is locked ».
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def init_db(path) -> None:
    """Crée le schéma si besoin puis applique les migrations manquantes (idempotent)."""
    conn = connect(path)
    conn.executescript(SCHEMA)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for v in sorted(MIGRATIONS):
        if v > version:
            conn.executescript(MIGRATIONS[v])
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
    conn.close()


# ----------------------------- Catégories --------------------------------- #
def category_tree(conn, user_id: int) -> list[dict]:
    """Arbre imbriqué [{id, name, count, children: [...]}, ...] ; count = images directes."""
    rows = conn.execute("SELECT id, name, parent_id FROM categories WHERE user_id=? ORDER BY name COLLATE NOCASE",
                        (user_id,)).fetchall()
    counts = dict(conn.execute("SELECT category_id, COUNT(*) FROM images WHERE user_id=? AND category_id IS NOT NULL "
                               "GROUP BY category_id", (user_id,)).fetchall())
    nodes = {r["id"]: {"id": r["id"], "name": r["name"], "count": counts.get(r["id"], 0), "children": []}
             for r in rows}
    roots = []
    for r in rows:
        (nodes[r["parent_id"]]["children"] if r["parent_id"] in nodes else roots).append(nodes[r["id"]])
    return roots


def flatten_tree(tree, depth=0):
    """Liste (id, libellé indenté) en parcours profond : pour les <select> de catégories."""
    out = []
    for n in tree:
        out.append((n["id"], "\u2003" * depth + ("↳ " if depth else "") + n["name"]))
        out += flatten_tree(n["children"], depth + 1)
    return out


def descendant_ids(conn, category_id: int) -> list[int]:
    """Catégorie + toutes ses sous-catégories (CTE récursive)."""
    rows = conn.execute("""WITH RECURSIVE sub(id) AS (
                               SELECT ? UNION ALL
                               SELECT c.id FROM categories c JOIN sub ON c.parent_id = sub.id)
                           SELECT id FROM sub""", (category_id,)).fetchall()
    return [r[0] for r in rows]


def category_path(conn, category_id: int) -> list[dict]:
    """Fil d'Ariane racine -> catégorie courante."""
    rows = conn.execute("""WITH RECURSIVE up(id, name, parent_id, lvl) AS (
                               SELECT id, name, parent_id, 0 FROM categories WHERE id = ?
                               UNION ALL
                               SELECT c.id, c.name, c.parent_id, up.lvl + 1
                               FROM categories c JOIN up ON c.id = up.parent_id)
                           SELECT id, name FROM up ORDER BY lvl DESC""", (category_id,)).fetchall()
    return [dict(r) for r in rows]


def get_or_create_category(conn, user_id, name, parent_id=None) -> int:
    row = conn.execute("SELECT id FROM categories WHERE user_id=? AND name=? AND parent_id IS ?",
                       (user_id, name, parent_id)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute("INSERT INTO categories(user_id, name, parent_id) VALUES (?,?,?)", (user_id, name, parent_id))
    return cur.lastrowid


def is_descendant(conn, category_id: int, ancestor_id: int) -> bool:
    """Vrai si `category_id` est `ancestor_id` ou l'une de ses sous-catégories (détection de cycle)."""
    return category_id in descendant_ids(conn, ancestor_id)


def move_category(conn, user_id: int, category_id: int, new_parent_id) -> None:
    """Déplace une catégorie sous un autre parent (None = racine).
    Lève ValueError si le déplacement créerait un cycle (une catégorie dans sa propre descendance)."""
    if new_parent_id is not None and is_descendant(conn, new_parent_id, category_id):
        raise ValueError("Impossible de déplacer une catégorie dans l'une de ses sous-catégories.")
    conn.execute("UPDATE categories SET parent_id=? WHERE id=? AND user_id=?", (new_parent_id, category_id, user_id))


def format_stats(conn, user_id: int, limit: int = 6) -> list[tuple[str, int]]:
    """Répartition par extension (calculée en Python : « a.b.jpg » -> « jpg », ce que SQL fait mal)."""
    counts: dict[str, int] = {}
    for (name,) in conn.execute("SELECT filename FROM images WHERE user_id=?", (user_id,)):
        ext = Path(name).suffix.lower().lstrip(".") or "?"
        counts[ext] = counts.get(ext, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])[:limit]


# ------------------------------ Images ------------------------------------ #
def insert_image(conn, user_id, filename, stored_name, width, height, size_bytes,
                 category_id=None, parent_image_id=None) -> int:
    cur = conn.execute("""INSERT INTO images(user_id, category_id, parent_image_id, filename, stored_name,
                                             width, height, size_bytes) VALUES (?,?,?,?,?,?,?,?)""",
                       (user_id, category_id, parent_image_id, filename, stored_name, width, height, size_bytes))
    return cur.lastrowid


def save_descriptor(conn, image_id: int, result: dict) -> None:
    """Enregistre la réponse de l'API pour une image (vecteur en float32 + détails JSON)."""
    vec = np.asarray(result["vector"], dtype=np.float32).tobytes()
    details = json.dumps({"color": result["color"], "texture": result["texture"]})
    conn.execute("INSERT OR REPLACE INTO descriptors(image_id, vector, details) VALUES (?,?,?)",
                 (image_id, vec, details))
