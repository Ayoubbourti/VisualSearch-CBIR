"""Moteur de recherche CBIR et retour de pertinence Re-weighting Type-1."""
import numpy as np
import pytest

from webapp.services.retrieval import DIM, EPS, FeatureSpace, get_space


def clusters(n=10, sep=2.0, seed=7, noise=0.15):
    rng = np.random.default_rng(seed)
    X = np.vstack([rng.normal(0, noise, (n, DIM)), rng.normal(sep, noise, (n, DIM))])
    return FeatureSpace(range(1, 2 * n + 1), X)


def test_simple_search_excludes_query_and_orders_by_distance():
    s = clusters()
    r = s.simple_search(1, 5)
    assert len(r["ids"]) == 5 and 1 not in r["ids"]
    assert r["distances"] == sorted(r["distances"])
    assert set(r["ids"]) <= set(range(2, 11))                       # voisins du même groupe
    assert set(r["weights"]) == {"Histogramme couleur", "Moments de couleur", "GLCM (texture)", "LBP (texture)"}
    assert all(v == pytest.approx(1.0) for v in r["weights"].values())


def test_k_is_capped_to_database_size():
    s = clusters(n=3)
    assert len(s.simple_search(1, 100)["ids"]) == 5


def test_zscore_normalisation():
    s = FeatureSpace(range(20), np.random.default_rng(1).normal(5, 3, (20, DIM)))
    assert np.allclose(s.Z.mean(axis=0), 0, atol=1e-9) and np.allclose(s.Z.std(axis=0), 1, atol=1e-9)


def test_constant_column_does_not_produce_nan():
    X = np.random.default_rng(1).normal(size=(10, DIM))
    X[:, 5] = 3.0
    assert np.isfinite(FeatureSpace(range(10), X).Z).all()


def test_type1_weight_formula_matches_paper():
    """w_i = (eps + sigma_Nr,i) / (eps + sigma_rel,i), avant bornage et normalisation."""
    s = clusters()
    simple = s.simple_search(1, 8)
    rel = [2, 3, 4]
    Zr, Zn = s.Z[[s.index[i] for i in [1] + rel]], s.Z[[s.index[i] for i in simple["ids"]]]
    expected = (EPS + Zn.std(axis=0)) / (EPS + Zr.std(axis=0))
    med = np.median(expected)
    expected = np.clip(expected, med / 20, med * 20)
    expected *= DIM / expected.sum()
    res = s.feedback_type1(1, rel, simple["ids"], 8, 20.0)
    ww = s.group_weights(expected)
    for name, v in res["weights"].items():
        assert v == pytest.approx(ww[name])


def test_type1_query_is_mean_of_relevant_vectors():
    s = clusters()
    ids, rel = s.simple_search(1, 8)["ids"], [2, 3]
    res = s.feedback_type1(1, rel, ids, 5, 20.0)
    assert res["updated"] and res["n_relevant"] == 3 and 1 not in res["ids"]


def test_feedback_requires_non_query_relevant_image():
    s = clusters()
    assert s.feedback_type1(1, [], [2, 3], 3) is None
    assert s.feedback_type1(1, [1], [2, 3], 3) is None               # la requête seule ne compte pas
    assert s.feedback_type1(1, [999], [2, 3], 3) is None             # id inconnu ignoré
    assert s.feedback_type1(1, [2], [], 3) is None                   # pas d'ensemble retourné


def test_weights_normalised_and_bounded():
    s = clusters()
    res = s.feedback_type1(1, [2, 3, 4], s.simple_search(1, 8)["ids"], 5, 20.0)
    assert all(np.isfinite(list(res["weights"].values())))
    # somme des poids = DIM  =>  moyenne des poids de bloc pondérée par la taille = 1
    sizes = {"Histogramme couleur": 72, "Moments de couleur": 9, "GLCM (texture)": 6, "LBP (texture)": 10}
    assert sum(res["weights"][n] * sizes[n] for n in sizes) / DIM == pytest.approx(1.0)


def test_duplicate_relevant_ids_are_ignored():
    s = clusters()
    ids = s.simple_search(1, 8)["ids"]
    a = s.feedback_type1(1, [2, 3], ids, 5, 20.0)
    b = s.feedback_type1(1, [2, 2, 3, 3], ids, 5, 20.0)
    assert a["ids"] == b["ids"] and a["weights"] == b["weights"]


def test_feedback_pulls_relevant_images_toward_the_top():
    """Données synthétiques : 3 groupes ; la requête est atypique. Après feedback, le groupe
    de la requête doit être mieux classé qu'avant (comportement attendu du retour de pertinence)."""
    rng = np.random.default_rng(3)
    informative = slice(0, 20)                                      # seules 20 dimensions séparent les groupes
    A = rng.normal(0, 1, (30, DIM)); A[:, informative] = rng.normal(0, 0.2, (30, 20))
    B = rng.normal(0, 1, (30, DIM)); B[:, informative] = rng.normal(2, 0.2, (30, 20))
    s = FeatureSpace(range(60), np.vstack([A, B]))
    prec = lambda ids: np.mean([i < 30 for i in ids])               # noqa: E731
    before = s.simple_search(0, 20)
    after = s.feedback_type1(0, [i for i in before["ids"] if i < 30], before["ids"], 20, 20.0)
    assert prec(after["ids"]) >= prec(before["ids"])
    assert prec(after["ids"]) >= 0.9


def test_get_space_cache_and_invalidation(app, gallery):
    from webapp import db as dbl
    with app.app_context():
        conn = dbl.connect(app.config["DATABASE"])
        uid = conn.execute("SELECT id FROM users").fetchone()[0]
        s1 = get_space(conn, uid)
        assert s1 is not None and len(s1.ids) == 6
        assert get_space(conn, uid) is s1                           # cache
        conn.execute("DELETE FROM images WHERE id=(SELECT MIN(id) FROM images)")
        conn.commit()
        s2 = get_space(conn, uid)
        assert s2 is not s1 and len(s2.ids) == 5                    # invalidé par la suppression
        conn.close()
