"""
Trace les courbes d'évolution des métriques (par itération de retour de pertinence) à partir des
fichiers *_summary.csv produits par scripts/evaluate.py.

    python scripts/make_figures.py results/eval_classic_summary.csv [results/eval_strict_summary.csv]
    -> docs/figures/metrics_classic.png (+ metrics_strict.png)
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

LABELS = {"precision_at_k": "Precision@K", "recall_at_k": "Recall@K", "map_at_k": "MAP@K", "ndcg_at_k": "nDCG@K"}


def read_summary(path: Path) -> list[dict]:
    with Path(path).open(encoding="utf-8-sig") as f:
        return [{k: float(v) for k, v in row.items()} for row in csv.DictReader(f)]


def plot_summary(rows: list[dict], out: Path, title: str) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    its = [r["iteration"] for r in rows]
    fig, axes = plt.subplots(1, 4, figsize=(13, 3.1))
    for ax, (key, label) in zip(axes, LABELS.items(), strict=True):
        ax.plot(its, [r[key] for r in rows], marker="o", lw=2, color="#2b6cb0")
        ax.set_title(label, fontsize=10)
        ax.set_xlabel("Itération (0 = recherche simple)", fontsize=8)
        ax.set_xticks(its)
        ax.grid(alpha=.3)
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=170)
    plt.close(fig)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("classic", type=Path)
    ap.add_argument("strict", type=Path, nargs="?")
    ap.add_argument("--outdir", type=Path, default=Path("docs/figures"))
    a = ap.parse_args()
    print(plot_summary(read_summary(a.classic), a.outdir / "metrics_classic.png",
                       "Évolution des métriques — protocole classique"))
    if a.strict:
        print(plot_summary(read_summary(a.strict), a.outdir / "metrics_strict.png",
                           "Évolution des métriques — protocole strict (images jugées exclues)"))


if __name__ == "__main__":
    main()
