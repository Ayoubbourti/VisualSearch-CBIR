"""
Évaluation reproductible de la recherche CBIR sur les catégories de la galerie.

La catégorie d'une image sert de vérité terrain (pertinence binaire). L'utilisateur simulé marque
comme pertinentes les images de la même catégorie que la requête. Cette simulation mesure un
scénario IDÉAL fondé sur les labels ; elle ne remplace pas une étude utilisateur.

Deux protocoles de comptage après retour de pertinence :
  * « classique » (défaut)   : les images déjà jugées pertinentes peuvent revenir dans les K résultats,
                               ce qui est l'usage dans une interface réelle mais GONFLE les métriques ;
  * « --exclude-judged »     : les images déjà jugées sont retirées du classement, les K résultats
                               comptés sont uniquement des images NOUVELLES (protocole plus strict,
                               à privilégier pour affirmer qu'un retour de pertinence « améliore »).

Métriques par itération : Precision@K, Recall@K, AP@K (-> MAP@K en moyenne), nDCG@K.

Exemples :
  python scripts/evaluate.py --username admin --queries 200 --scope 25 --iterations 5
  python scripts/evaluate.py --username admin --exclude-judged --output results/eval_strict.csv
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from webapp import db as dbl                    # noqa: E402
from webapp.config import Config               # noqa: E402
from webapp.services import retrieval           # noqa: E402

METRICS = ("precision_at_k", "recall_at_k", "map_at_k", "ndcg_at_k")


def ranking_metrics(ranked_ids, query_id, query_label, labels, k):
    """Métriques d'un classement pour une requête. `labels` : {image_id: catégorie}."""
    ranked = [i for i in ranked_ids if i != query_id][:k]
    if not ranked:
        return dict.fromkeys(METRICS, 0.0)
    rel = np.asarray([1 if labels.get(i) == query_label else 0 for i in ranked], dtype=float)
    total_relevant = max(1, sum(1 for i, lab in labels.items() if lab == query_label and i != query_id))
    precision = float(rel.sum() / len(ranked))
    recall = float(rel.sum() / total_relevant)
    precisions = np.cumsum(rel) / np.arange(1, len(rel) + 1)
    ap = float((precisions * rel).sum() / min(total_relevant, k))
    discounts = 1.0 / np.log2(np.arange(2, len(rel) + 2))
    dcg = float((rel * discounts).sum())
    idcg = float(discounts[:min(total_relevant, len(rel))].sum())
    return {"precision_at_k": precision, "recall_at_k": recall, "map_at_k": ap,
            "ndcg_at_k": dcg / idcg if idcg else 0.0}


def run_query(space, qid, labels, scope, iterations, max_ratio, exclude_judged=False):
    """Simule une session complète (recherche simple + `iterations` retours de pertinence).
    Retourne la liste des lignes {query_id, iteration, <métriques>}."""
    qlabel = labels[qid]
    result = space.simple_search(qid, scope)
    shown, judged, rows = list(result["ids"]), set(), []
    for iteration in range(iterations + 1):
        metrics = ranking_metrics(shown, qid, qlabel, labels, scope)
        rows.append({"query_id": qid, "iteration": iteration, **metrics})
        if iteration == iterations:
            break
        judged.update(i for i in shown if labels.get(i) == qlabel)       # l'utilisateur simulé clique
        want = scope + (len(judged) if exclude_judged else 0)
        updated = space.feedback_type1(qid, sorted(judged), shown, want, max_ratio)
        if updated is None:                       # aucun résultat pertinent : la courbe reste plate
            rows += [{"query_id": qid, "iteration": later, **metrics}
                     for later in range(iteration + 1, iterations + 1)]
            break
        ids = [i for i in updated["ids"] if not (exclude_judged and i in judged)]
        shown = ids[:scope]
    return rows


def summarize(rows, iterations):
    """Moyenne des métriques par itération -> liste de dicts."""
    out = []
    for it in range(iterations + 1):
        grp = [r for r in rows if r["iteration"] == it]
        out.append({"iteration": it, "n_queries": len(grp),
                    **{m: float(np.mean([r[m] for r in grp])) for m in METRICS}})
    return out


def select_queries(labels, n, seed):
    """Échantillon reproductible de requêtes, restreint aux catégories d'au moins 2 images."""
    counts: dict = {}
    for lab in labels.values():
        counts[lab] = counts.get(lab, 0) + 1
    pool = [i for i, lab in labels.items() if counts[lab] >= 2]
    random.Random(seed).shuffle(pool)
    return pool[:max(1, min(n, len(pool)))] if pool else []


def write_csv(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--username", default="admin")
    ap.add_argument("--queries", type=int, default=200)
    ap.add_argument("--scope", type=int, default=25)
    ap.add_argument("--iterations", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--exclude-judged", action="store_true", help="protocole strict (voir en-tête)")
    ap.add_argument("--output", type=Path, default=Path("results/cbir_evaluation.csv"))
    args = ap.parse_args()

    if not Path(Config.DATABASE).exists():
        raise SystemExit(f"Base introuvable : {Config.DATABASE} (indexez d'abord les images : scripts/index_dataset.py)")
    conn = dbl.connect(Config.DATABASE)
    user = conn.execute("SELECT id FROM users WHERE username=?", (args.username,)).fetchone()
    if user is None:
        raise SystemExit(f"Utilisateur introuvable : {args.username}")
    space = retrieval.get_space(conn, user["id"])
    if space is None:
        raise SystemExit("Au moins deux images indexées avec descripteurs sont nécessaires.")
    indexed = {int(i) for i in space.index}
    labels = {int(r["id"]): int(r["category_id"]) for r in conn.execute(
        "SELECT id, category_id FROM images WHERE user_id=? AND category_id IS NOT NULL", (user["id"],))
        if int(r["id"]) in indexed}
    queries = select_queries(labels, args.queries, args.seed)
    if not queries:
        raise SystemExit("Aucune catégorie ne contient au moins deux images indexées.")

    rows = []
    for n, qid in enumerate(queries, 1):
        rows += run_query(space, qid, labels, args.scope, args.iterations,
                          Config.MAX_WEIGHT_RATIO, args.exclude_judged)
        if n % 50 == 0:
            print(f"  {n}/{len(queries)} requêtes…", file=sys.stderr)

    summary = summarize(rows, args.iterations)
    write_csv(args.output, rows)
    write_csv(args.output.with_name(args.output.stem + "_summary.csv"), summary)

    proto = "strict (images jugées exclues)" if args.exclude_judged else "classique (images jugées conservées)"
    print(f"\nÉvaluation : {len(queries)} requêtes | K={args.scope} | {args.iterations} itérations | protocole {proto}")
    print("Vérité terrain : catégorie de l'image (simulation d'un utilisateur idéal).\n")
    print("Itération | Precision@K | Recall@K | MAP@K  | nDCG@K")
    print("-" * 58)
    for s in summary:
        print(f"{s['iteration']:9d} | {s['precision_at_k']*100:10.2f}% | {s['recall_at_k']*100:7.2f}% | "
              f"{s['map_at_k']:.4f} | {s['ndcg_at_k']:.4f}")
    print(f"\nCSV détaillé : {args.output.resolve()}")
    print(f"CSV résumé   : {args.output.with_name(args.output.stem + '_summary.csv').resolve()}")
    print("Rappel : les catégories sont un proxy de pertinence, pas un jugement humain.")


if __name__ == "__main__":
    main()
