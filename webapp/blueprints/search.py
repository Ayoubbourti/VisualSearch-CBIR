"""Recherche par similarité : recherche simple + retour de pertinence Re-weighting Type-1."""
from flask import Blueprint, abort, current_app, g, jsonify, render_template, request, url_for

from webapp.core import get_db, login_required, own_image
from webapp.services import retrieval

bp = Blueprint("search", __name__)


def _int(value, name, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        if default is not None:
            return default
        abort(400, f"Paramètre invalide : {name}.")


def _int_list(values, name):
    if not isinstance(values, list):
        abort(400, f"Paramètre invalide : {name} (liste attendue).")
    return [_int(v, name) for v in values][:5000]


def _payload(result, query_id, iteration):
    """Enrichit les ids retournés par le moteur avec nom / URLs pour l'affichage côté navigateur."""
    ids = result["ids"]
    names = {r["id"]: r["filename"] for r in get_db().execute(
        f"SELECT id, filename FROM images WHERE id IN ({','.join('?' * len(ids))})", ids)}
    return {"query_id": query_id, "iteration": iteration, "weights": result["weights"],
            "updated": result["updated"], "n_relevant": result.get("n_relevant"),
            "results": [{"id": i, "name": names.get(i, ""), "rank": r + 1, "distance": round(d, 4),
                         "thumb": url_for("images.image_thumb", iid=i), "url": url_for("images.image_detail", iid=i)}
                        for r, (i, d) in enumerate(zip(ids, result["distances"], strict=True))]}


def _context(data):
    """Valide la requête JSON et retourne (espace de caractéristiques, id requête, k)."""
    if not isinstance(data, dict):
        abort(400, "Corps JSON attendu.")
    qid = _int(data.get("query_id"), "query_id")
    own_image(qid)
    space = retrieval.get_space(get_db(), g.user["id"])
    if space is None or qid not in space.index:
        abort(400, "Descripteurs manquants : calculez-les d'abord (bouton « Calculer les descripteurs manquants »).")
    k = max(1, min(_int(data.get("k"), "k", current_app.config["SEARCH_DEFAULT_K"]),
                   current_app.config["SEARCH_MAX_K"]))
    return space, qid, k


@bp.get("/search")
@login_required
def page():
    img = own_image(request.args.get("query_id", type=int) or 0)
    return render_template("search.html", img=img, default_k=current_app.config["SEARCH_DEFAULT_K"],
                           max_k=current_app.config["SEARCH_MAX_K"])


@bp.post("/api/search")
@login_required
def api_search():
    """Recherche simple (itération 0, poids uniformes)."""
    space, qid, k = _context(request.get_json(silent=True))
    return jsonify(_payload(space.simple_search(qid, k), qid, 0))


@bp.post("/api/feedback")
@login_required
def api_feedback():
    """Une itération de retour de pertinence. Le serveur est SANS ÉTAT : le navigateur renvoie la requête,
    les images pertinentes cumulées et les images affichées (Nr) ; le moteur recalcule requête et poids."""
    data = request.get_json(silent=True)
    space, qid, k = _context(data)
    res = space.feedback_type1(qid, _int_list(data.get("relevant_ids", []), "relevant_ids"),
                               _int_list(data.get("retrieved_ids", []), "retrieved_ids"), k,
                               current_app.config["MAX_WEIGHT_RATIO"])
    if res is None:
        return jsonify(error="Sélectionnez au moins une image pertinente (en plus de la requête)."), 422
    return jsonify(_payload(res, qid, max(0, _int(data.get("iteration"), "iteration", 0)) + 1))
