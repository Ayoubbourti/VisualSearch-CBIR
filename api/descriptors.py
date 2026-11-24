"""
Calcul des descripteurs visuels d'une image (couleur + texture).

Ce module est PUR (aucune dépendance à Flask) : il peut donc être testé seul
et réutilisé par le script d'indexation en masse (scripts/index_dataset.py).

Descripteurs implémentés
------------------------
COULEUR
  * Histogramme de couleur   : histogramme 3D quantifié dans l'espace HSV
                               (8 teintes x 3 saturations x 3 valeurs = 72 bins), normalisé (somme = 1).
  * Moments de couleur       : moyenne, écart-type, asymétrie (skewness) de chaque canal H, S, V (9 valeurs).
  * Couleurs dominantes      : K-Means (k = 5) sur les pixels RGB ; on retourne les centres et leur proportion.

TEXTURE
  * Matrice de co-occurrence des niveaux de gris (GLCM) : contraste, corrélation, énergie,
    homogénéité, dissimilarité, entropie (moyennées sur 4 orientations 0°, 45°, 90°, 135°).
  * LBP (Local Binary Patterns, variante "uniform", P=8, R=1) : histogramme de 10 bins normalisé.

Le vecteur global utilisé par la recherche par similarité est la concaténation :
  [hist couleur (72) | moments (9) | GLCM (6) | LBP (10)]  ->  97 composantes.
"""
from __future__ import annotations

import numpy as np
from PIL import Image
from skimage.feature import graycomatrix, graycoprops, local_binary_pattern
from sklearn.cluster import KMeans

# --------------------------------------------------------------------------- #
# Paramètres
# --------------------------------------------------------------------------- #
MAX_SIDE = 256                  # les images sont réduites (plus grand côté) avant calcul : vitesse
H_BINS, S_BINS, V_BINS = 8, 3, 3
GLCM_LEVELS = 32                # quantification des gris (256 niveaux rendrait la GLCM trop lourde)
GLCM_ANGLES = [0, np.pi / 4, np.pi / 2, 3 * np.pi / 4]
GLCM_PROPS = ["contrast", "correlation", "energy", "homogeneity", "dissimilarity"]  # + "entropy"
LBP_P, LBP_R = 8, 1
LBP_BINS = LBP_P + 2            # méthode "uniform" -> P + 2 valeurs possibles
N_DOMINANT = 5
KMEANS_SAMPLE = 2000            # pixels échantillonnés pour les couleurs dominantes (affichage uniquement)
KMEANS_INIT = 3                 # initialisations K-Means (10 par défaut dans sklearn : 3 suffisent ici)

# Structure du vecteur global (nom du bloc, nombre de composantes).
# Le serveur web utilise la même structure pour équilibrer les blocs lors de la comparaison.
LAYOUT = [
    ("color_histogram", H_BINS * S_BINS * V_BINS),
    ("color_moments", 9),
    ("glcm", len(GLCM_PROPS) + 1),
    ("lbp", LBP_BINS),
]
VECTOR_DIM = sum(n for _, n in LAYOUT)


# --------------------------------------------------------------------------- #
# Chargement
# --------------------------------------------------------------------------- #
def load_image(source) -> Image.Image:
    """Ouvre une image (chemin ou flux), la convertit en RGB et la redimensionne."""
    img = Image.open(source).convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    return img


# --------------------------------------------------------------------------- #
# Couleur
# --------------------------------------------------------------------------- #
def color_histogram(hsv: np.ndarray) -> np.ndarray:
    """Histogramme 3D HSV quantifié, aplati et normalisé. `hsv` : (N, 3) dans [0, 1]."""
    hist, _ = np.histogramdd(hsv, bins=(H_BINS, S_BINS, V_BINS), range=((0, 1),) * 3)
    hist = hist.ravel()
    return hist / max(hist.sum(), 1e-12)


def color_moments(hsv: np.ndarray) -> dict:
    """Trois premiers moments (moyenne, écart-type, asymétrie) de chaque canal HSV."""
    out = {}
    for k, name in enumerate("HSV"):
        x = hsv[:, k]
        mean = float(x.mean())
        std = float(x.std())
        # Asymétrie standardisée (skewness), sans division par zéro.
        skew = float((((x - mean) / std) ** 3).mean()) if std > 1e-12 else 0.0
        out[name] = {"mean": mean, "std": std, "skewness": skew}
    return out


def dominant_colors(rgb: np.ndarray, k: int = N_DOMINANT) -> list[dict]:
    """Couleurs dominantes par K-Means sur un échantillon de pixels (résultat reproductible)."""
    rng = np.random.default_rng(0)
    if len(rgb) > KMEANS_SAMPLE:
        rgb = rgb[rng.choice(len(rgb), KMEANS_SAMPLE, replace=False)]
    k = max(1, min(k, len(np.unique(rgb, axis=0))))        # image quasi uniforme -> moins de clusters
    km = KMeans(n_clusters=k, n_init=KMEANS_INIT, random_state=0).fit(rgb)
    props = np.bincount(km.labels_, minlength=k) / len(rgb)
    order = np.argsort(-props)
    result = []
    for i in order:
        r, g, b = (int(round(c)) for c in km.cluster_centers_[i])
        result.append({"rgb": [r, g, b], "hex": f"#{r:02x}{g:02x}{b:02x}", "proportion": float(props[i])})
    return result


def _color(img: Image.Image) -> dict:
    hsv = np.asarray(img.convert("HSV"), dtype=np.float64).reshape(-1, 3) / 255.0
    rgb = np.asarray(img, dtype=np.float64).reshape(-1, 3)
    return {
        "histogram": {"bins": {"h": H_BINS, "s": S_BINS, "v": V_BINS},
                      "values": color_histogram(hsv).tolist()},
        "moments": color_moments(hsv),
        "dominant_colors": dominant_colors(rgb),
    }


# --------------------------------------------------------------------------- #
# Texture
# --------------------------------------------------------------------------- #
def glcm_features(gray: np.ndarray) -> dict:
    """Caractéristiques de Haralick issues de la GLCM (moyenne sur 4 orientations)."""
    q = (gray // (256 // GLCM_LEVELS)).astype(np.uint8)            # quantification 0..31
    glcm = graycomatrix(q, distances=[1], angles=GLCM_ANGLES,
                        levels=GLCM_LEVELS, symmetric=True, normed=True)
    feats = {p: float(np.nan_to_num(graycoprops(glcm, p).mean(), nan=1.0)) for p in GLCM_PROPS}
    P = glcm[:, :, 0, :]                                           # (levels, levels, angles)
    # Les petites valeurs négatives dues à l'arrondi numérique sont ramenées à zéro.
    feats["entropy"] = max(0.0, float((-(P * np.log2(P + 1e-12)).sum(axis=(0, 1))).mean()))
    return feats


def lbp_histogram(gray: np.ndarray) -> np.ndarray:
    """Histogramme normalisé des motifs binaires locaux uniformes."""
    lbp = local_binary_pattern(gray, LBP_P, LBP_R, method="uniform")
    hist, _ = np.histogram(lbp, bins=LBP_BINS, range=(0, LBP_BINS))
    return hist / max(hist.sum(), 1)


def _texture(img: Image.Image) -> dict:
    gray = np.asarray(img.convert("L"))
    return {"glcm": glcm_features(gray), "lbp_histogram": lbp_histogram(gray).tolist()}


# --------------------------------------------------------------------------- #
# Vecteur global + API publique du module
# --------------------------------------------------------------------------- #
def build_vector(color: dict, texture: dict) -> list[float]:
    """Concatène tous les descripteurs en un vecteur de VECTOR_DIM composantes (ordre = LAYOUT)."""
    v = list(color["histogram"]["values"])
    for ch in "HSV":
        m = color["moments"][ch]
        v += [m["mean"], m["std"], m["skewness"]]
    v += [texture["glcm"][p] for p in GLCM_PROPS + ["entropy"]]
    v += list(texture["lbp_histogram"])
    assert len(v) == VECTOR_DIM
    return [float(x) for x in v]


def compute_color(source) -> dict:
    return {"color": _color(load_image(source))}


def compute_texture(source) -> dict:
    return {"texture": _texture(load_image(source))}


def compute_all(source) -> dict:
    """Tous les descripteurs + vecteur global (l'image n'est décodée qu'une seule fois)."""
    img = load_image(source)
    color, texture = _color(img), _texture(img)
    return {"color": color, "texture": texture,
            "vector": build_vector(color, texture),
            "layout": [{"name": n, "size": s} for n, s in LAYOUT]}
