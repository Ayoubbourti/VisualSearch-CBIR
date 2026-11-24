"""
Recherche d'images par le contenu (CBIR) + retour de pertinence « Re-weighting Type-1 ».

1) Espace de caractéristiques (FeatureSpace)
   - Normalisation gaussienne par composante (z-score) : sans elle, une composante de grande échelle
     (ex. le contraste GLCM) écraserait les bins d'histogramme (valeurs < 1).
   - Équilibrage des blocs : chaque bloc (histogramme couleur 72, moments 9, GLCM 6, LBP 10) reçoit un
     poids de base 1/taille_du_bloc, de sorte que couleur et texture pèsent autant malgré leurs
     dimensions différentes. C'est un a priori fixe, distinct des poids appris par le retour de pertinence.

2) Distance euclidienne pondérée (papier, éq. 3) :
        D(X, Y) = sqrt( sum_i w_i * b_i * (x_i - y_i)^2 / sum_i w_i * b_i )
   w_i : poids appris par le retour de pertinence (1 au départ) ; b_i : poids de base du bloc.

3) Re-weighting Type-1 (papier, éq. 5) à chaque itération k :
        w_i^{k+1} = (eps + sigma_{Nr,i}) / (eps + sigma_{rel,i}),   eps = 1e-4
   sigma_{Nr,i}  : écart-type de la composante i sur les Nr images retournées à l'itération
   sigma_{rel,i} : écart-type de la composante i sur les images jugées pertinentes (+ la requête)
   -> une composante peu variable sur les images pertinentes est "caractéristique" du concept
      recherché : elle reçoit un poids élevé.
   Le nouveau vecteur requête est la MOYENNE des vecteurs pertinents (tableau 1 du papier).
   Type-1 n'utilise que les images pertinentes : les images non pertinentes sont ignorées.

Deux garde-fous (ajouts documentés dans le README, absents du papier) :
   - il faut au moins UNE image pertinente en plus de la requête (sinon sigma_rel = 0 partout et les
     poids deviendraient proportionnels à sigma_Nr, ce qui n'a aucun sens) ;
   - les poids sont bornés à [médiane / R, médiane * R] (R = MAX_WEIGHT_RATIO) : avec 2 ou 3 exemples,
     une composante identique par hasard donnerait sinon un poids de l'ordre de 1/eps = 10^4.
"""
import threading

import numpy as np

EPS = 1e-4

# Doit rester identique à api/descriptors.py::LAYOUT
FEATURE_GROUPS = [("Histogramme couleur", 72), ("Moments de couleur", 9),
                  ("GLCM (texture)", 6), ("LBP (texture)", 10)]
DIM = sum(n for _, n in FEATURE_GROUPS)


class FeatureSpace:
    """Matrice de descripteurs normalisée de TOUTES les images d'un utilisateur."""

    def __init__(self, ids, X):
        self.ids = np.asarray(ids, dtype=np.int64)
        self.index = {int(i): k for k, i in enumerate(self.ids)}      # id image -> ligne
        mu, sd = X.mean(axis=0), X.std(axis=0)
        sd[sd < 1e-8] = 1.0                                           # composante constante : évite /0
        self.Z = (X - mu) / sd
        self.base = np.concatenate([np.full(n, 1.0 / n) for _, n in FEATURE_GROUPS])
        self.group_slices, start = [], 0
        for name, n in FEATURE_GROUPS:
            self.group_slices.append((name, slice(start, start + n)))
            start += n

    # ------------------------------------------------------------------ #
    def distances(self, q, w):
        """Distance euclidienne pondérée de la requête `q` à toutes les images."""
        ww = w * self.base
        return np.sqrt(((self.Z - q) ** 2 * ww).sum(axis=1) / ww.sum())

    def rank(self, q, w, k, exclude_id):
        """Les k images les plus proches (requête exclue) -> (ids, distances)."""
        d = self.distances(q, w)
        d[self.index[exclude_id]] = np.inf
        k = min(max(1, int(k)), len(d) - 1)
        top = np.argpartition(d, k - 1)[:k]
        top = top[np.argsort(d[top])]
        return self.ids[top].tolist(), d[top].tolist()

    def group_weights(self, w):
        """Poids moyen par bloc, relativement à la moyenne globale (1.0 = neutre) : pour l'affichage."""
        return {name: float(w[s].mean() / w.mean()) for name, s in self.group_slices}

    # ------------------------------------------------------------------ #
    def simple_search(self, query_id, k):
        """Recherche simple : distance euclidienne, poids uniformes."""
        w = np.ones(DIM)
        ids, dist = self.rank(self.Z[self.index[query_id]], w, k, query_id)
        return {"ids": ids, "distances": dist, "weights": self.group_weights(w), "updated": False}

    def feedback_type1(self, query_id, relevant_ids, retrieved_ids, k, max_ratio=20.0):
        """Une itération de retour de pertinence Re-weighting Type-1.

        relevant_ids  : images marquées pertinentes (cumul depuis la première itération)
        retrieved_ids : images affichées à l'itération qui vient d'être jugée (les Nr du papier)
        """
        rel = [query_id] + [i for i in dict.fromkeys(relevant_ids) if i != query_id and i in self.index]
        if len(rel) < 2:
            return None                                              # rien à apprendre (voir en-tête)
        Zr = self.Z[[self.index[i] for i in rel]]
        nr_ids = [i for i in dict.fromkeys(retrieved_ids) if i in self.index and i != query_id]
        if not nr_ids:
            return None
        Zn = self.Z[[self.index[i] for i in nr_ids]]

        q_new = Zr.mean(axis=0)                                      # requête = moyenne des pertinents
        w = (EPS + Zn.std(axis=0)) / (EPS + Zr.std(axis=0))          # éq. (5)
        med = np.median(w)
        w = np.clip(w, med / max_ratio, med * max_ratio)             # garde-fou anti-poids extrêmes
        w *= DIM / w.sum()                                           # normalisation (somme = DIM)

        ids, dist = self.rank(q_new, w, k, query_id)
        return {"ids": ids, "distances": dist, "weights": self.group_weights(w),
                "updated": True, "n_relevant": len(rel)}


# --------------------------------------------------------------------------- #
# Chargement + cache par utilisateur
# --------------------------------------------------------------------------- #
_CACHE: dict = {}
_LOCK = threading.Lock()


def get_space(conn, user_id) -> FeatureSpace | None:
    """Retourne l'espace de l'utilisateur ; reconstruit seulement si ses descripteurs ont changé
    (le « tampon » (nombre, max id, somme des id) détecte ajouts et suppressions)."""
    stamp = tuple(conn.execute(
        """SELECT COUNT(*), COALESCE(MAX(d.image_id),0), COALESCE(SUM(d.image_id),0)
           FROM descriptors d JOIN images i ON i.id = d.image_id WHERE i.user_id = ?""", (user_id,)).fetchone())
    with _LOCK:
        cached = _CACHE.get(user_id)
        if cached and cached[0] == stamp:
            return cached[1]
        if stamp[0] < 2:
            return None
        rows = conn.execute("""SELECT d.image_id, d.vector FROM descriptors d
                               JOIN images i ON i.id = d.image_id WHERE i.user_id = ? ORDER BY d.image_id""",
                            (user_id,)).fetchall()
        X = np.vstack([np.frombuffer(r["vector"], dtype=np.float32) for r in rows]).astype(np.float64)
        space = FeatureSpace([r["image_id"] for r in rows], X)
        _CACHE[user_id] = (stamp, space)
        return space
