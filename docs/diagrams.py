"""Génère les schémas du rapport (architecture, modèle de données, boucle de retour de pertinence) avec matplotlib."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt                        # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch   # noqa: E402

BLUE, GREEN, ORANGE, GREY, RED = "#dbeafe", "#dcfce7", "#ffedd5", "#f1f5f9", "#fee2e2"
EDGE = "#334155"


def box(ax, x, y, w, h, text, fc=GREY, fs=9, bold=False, ec=EDGE):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08", fc=fc, ec=ec, lw=1.2))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs,
            fontweight="bold" if bold else "normal", linespacing=1.35)


def arrow(ax, p, q, text=None, both=False, off=(0, 0.12), fs=8):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="<|-|>" if both else "-|>", mutation_scale=13, lw=1.3, color=EDGE))
    if text:
        ax.text((p[0] + q[0]) / 2 + off[0], (p[1] + q[1]) / 2 + off[1], text, ha="center", va="bottom", fontsize=fs,
                color="#1e293b", bbox={"fc": "white", "ec": "none", "pad": 0.8})


def canvas(w, h):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(0, w); ax.set_ylim(0, h); ax.axis("off")
    return fig, ax


def architecture(path: Path):
    fig, ax = canvas(10, 6.4)
    box(ax, 3.2, 5.5, 3.6, 0.7, "Navigateur\nHTML · CSS · JavaScript", BLUE, bold=True)
    box(ax, 2.2, 3.3, 5.6, 1.7, "Application web — Flask (webapp/)\n\nAuthentification · Galerie · Catégories\nImport/Export · Transformations · Recherche CBIR", GREEN, bold=True)
    box(ax, 0.2, 0.3, 2.9, 1.8, "SQLite\n\nusers · categories\nimages · descriptors\n(vecteurs float32)", ORANGE)
    box(ax, 3.55, 0.3, 2.9, 1.8, "Disque\n\nimages originales\nimages transformées\nvignettes", ORANGE)
    box(ax, 6.9, 0.3, 2.9, 1.8, "API REST — Flask-RESTful\n(api/)\n\ndescriptors.py\nCouleur + Texture", BLUE, bold=True)
    arrow(ax, (5, 5.5), (5, 5.0), "HTTP", both=True, off=(0.45, -0.1))
    arrow(ax, (3.2, 3.3), (1.65, 2.1), "SQL", both=True, off=(-0.35, 0.05))
    arrow(ax, (5, 3.3), (5, 2.1), "fichiers", both=True, off=(0.5, 0.05))
    arrow(ax, (6.8, 3.3), (8.3, 2.1), "HTTP multipart\n(images → descripteurs JSON)", off=(0.75, 0.1))
    ax.text(5, 6.3, "Architecture logique de VisualSearch", ha="center", fontsize=11, fontweight="bold")
    fig.savefig(path, dpi=180, bbox_inches="tight"); plt.close(fig)


def er_diagram(path: Path):
    fig, ax = canvas(10, 6.0)
    RH = 0.32

    def table(x, y, w, title, rows, fc):
        h = RH * (len(rows) + 1)
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.01,rounding_size=0.05", fc="white", ec=EDGE, lw=1.2))
        ax.add_patch(FancyBboxPatch((x, y + h - RH), w, RH, boxstyle="round,pad=0.01,rounding_size=0.05", fc=fc, ec=EDGE, lw=1.2))
        ax.text(x + w / 2, y + h - RH / 2, title, ha="center", va="center", fontsize=10, fontweight="bold")
        for i, r in enumerate(rows):
            ax.text(x + 0.12, y + h - RH - RH / 2 - i * RH, r, va="center", fontsize=8, family="DejaVu Sans Mono")

    table(0.2, 2.9, 2.9, "users", ["id  PK", "username  UNIQUE", "password_hash", "created_at"], BLUE)
    table(3.8, 3.7, 3.0, "categories", ["id  PK", "user_id  FK -> users", "name", "parent_id  FK -> categories"], GREEN)
    table(3.8, 0.3, 3.0, "images", ["id  PK", "user_id  FK -> users", "category_id  FK -> categories",
                                    "parent_image_id  FK -> images", "filename, stored_name", "width, height, size_bytes"], ORANGE)
    table(7.5, 1.0, 2.4, "descriptors", ["image_id  PK, FK", "vector  BLOB 97xf32", "details  JSON"], RED)
    arrow(ax, (3.1, 4.3), (3.8, 4.5), "1..n", off=(0, 0.12))
    arrow(ax, (3.1, 3.2), (3.8, 1.6), "1..n", off=(-0.45, 0.2))
    arrow(ax, (5.3, 3.7), (5.3, 2.55), "0..1 - n", off=(0.55, 0))
    arrow(ax, (6.8, 1.3), (7.5, 1.3), "1 - 1", off=(0, 0.12))
    ax.text(5.0, 5.75, "Modele de donnees (SQLite)".replace("Modele", "Modèle").replace("donnees", "données"),
            ha="center", fontsize=11, fontweight="bold")
    ax.text(5.0, 5.45, "Hiérarchies : liste d'adjacence (parent_id) pour les catégories et les images dérivées ; parcours par CTE récursive",
            fontsize=7.8, ha="center", style="italic")
    ax.set_ylim(0, 6.0)
    fig.savefig(path, dpi=180, bbox_inches="tight"); plt.close(fig)


def feedback_loop(path: Path):
    fig, ax = canvas(10, 4.6)
    steps = [("1. Image requête\nq", BLUE), ("2. Recherche simple\nw = 1, distance euclidienne", GREEN),
             ("3. Affichage des K\nrésultats (Nr)", GREEN), ("4. L'utilisateur marque\nles images pertinentes R", ORANGE)]
    xs = [0.2, 2.75, 5.3, 7.85]
    for (t, c), x in zip(steps, xs, strict=True):
        box(ax, x, 2.9, 2.0, 1.1, t, c, fs=8.5)
    for a, b in zip(xs[:-1], xs[1:], strict=True):
        arrow(ax, (a + 2.0, 3.45), (b, 3.45))
    box(ax, 7.85, 0.9, 2.0, 1.2, "5. Ré-estimation Type-1\nwᵢ = (ε+σ_Nr,i)/(ε+σ_rel,i)\nq' = moyenne de R", RED, fs=8)
    box(ax, 5.0, 0.9, 2.35, 1.2, "6. Nouveau classement\nD(q', x) pondérée par w", GREEN, fs=8.5)
    box(ax, 2.2, 0.9, 2.2, 1.2, "7. Satisfait ?\nnon → retour à l'étape 3\noui → fin", GREY, fs=8.5)
    arrow(ax, (8.85, 2.9), (8.85, 2.1))
    arrow(ax, (7.85, 1.5), (7.35, 1.5))
    arrow(ax, (5.0, 1.5), (4.4, 1.5))
    arrow(ax, (3.3, 2.1), (6.3, 2.9), "itération suivante", off=(-0.4, 0.15))
    ax.text(5, 4.45, "Boucle de retour de pertinence — Re-weighting Type-1", ha="center", fontsize=11, fontweight="bold")
    ax.set_ylim(0.5, 4.7)
    fig.savefig(path, dpi=180, bbox_inches="tight"); plt.close(fig)


def equation(latex: str, path: Path, fs: int = 15):
    fig = plt.figure(figsize=(0.1, 0.1))
    fig.text(0, 0, f"${latex}$", fontsize=fs)
    fig.savefig(path, dpi=220, bbox_inches="tight", pad_inches=0.04, transparent=False, facecolor="white")
    plt.close(fig)


def build_all(outdir: Path) -> dict[str, Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    paths = {"architecture": outdir / "architecture.png", "er": outdir / "er.png", "loop": outdir / "feedback_loop.png"}
    architecture(paths["architecture"]); er_diagram(paths["er"]); feedback_loop(paths["loop"])
    return paths


if __name__ == "__main__":
    print(build_all(Path(__file__).parent / "figures"))
