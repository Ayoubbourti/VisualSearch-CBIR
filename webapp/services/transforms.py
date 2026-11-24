"""
Transformations d'images (Pillow) : chaque fonction reçoit une image PIL + les paramètres du formulaire
et retourne une NOUVELLE image ; l'original n'est jamais modifié. Les erreurs de saisie lèvent ValueError.
"""
import math

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

MAX_PIXELS = 40_000_000      # borne de la taille d'une image produite (protège la mémoire du serveur)


def _num(p, key, default=None, cast=float, lo=None, hi=None):
    """Lit un paramètre numérique du formulaire ; refuse NaN/inf et les valeurs hors de [lo, hi]."""
    v = p.get(key)
    if v in (None, ""):
        if default is None:
            raise ValueError(f"Paramètre manquant : {key}")
        return default
    try:
        x = cast(v)
    except (ValueError, TypeError):
        raise ValueError(f"Valeur invalide pour {key} : {v!r}") from None
    if isinstance(x, float) and not math.isfinite(x):
        raise ValueError(f"Valeur invalide pour {key} : {v!r}")
    if (lo is not None and x < lo) or (hi is not None and x > hi):
        raise ValueError(f"{key} doit être compris entre {lo} et {hi}.")
    return x


def crop(img, p):
    x, y = _num(p, "x", 0, int), _num(p, "y", 0, int)
    w, h = _num(p, "w", cast=int), _num(p, "h", cast=int)
    if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > img.width or y + h > img.height:
        raise ValueError(f"Zone de recadrage hors de l'image ({img.width}×{img.height} px).")
    return img.crop((x, y, x + w, y + h))


def resize(img, p):
    """Soit un facteur d'échelle en %, soit largeur/hauteur (une seule dimension -> ratio conservé)."""
    if p.get("scale"):
        f = _num(p, "scale", lo=0.01, hi=1000) / 100
        w, h = round(img.width * f), round(img.height * f)
    else:
        w, h = _num(p, "width", 0, int), _num(p, "height", 0, int)
        if not w and not h:
            raise ValueError("Indiquez un pourcentage, ou une largeur et/ou une hauteur.")
        w = w or round(img.width * h / img.height)
        h = h or round(img.height * w / img.width)
    if not (1 <= w <= 10000 and 1 <= h <= 10000) or w * h > MAX_PIXELS:
        raise ValueError("Dimensions finales invalides (1 à 10000 px par côté, 40 Mpx au total).")
    return img.resize((w, h), Image.LANCZOS)


def rotate(img, p):
    return img.rotate(_num(p, "angle", 90, lo=-3600, hi=3600), expand=True, resample=Image.BICUBIC)


def _enhance(cls):
    return lambda img, p: cls(img).enhance(_num(p, "factor", 1.0, lo=0.0, hi=10.0))


# Registre : nom de l'opération -> fonction (img, params) -> img
OPERATIONS = {
    "crop": ("Recadrer (crop)", crop),
    "resize": ("Changer l'échelle", resize),
    "rotate": ("Rotation", rotate),
    "flip_h": ("Miroir horizontal", lambda img, p: ImageOps.mirror(img)),
    "flip_v": ("Miroir vertical", lambda img, p: ImageOps.flip(img)),
    "grayscale": ("Niveaux de gris", lambda img, p: ImageOps.grayscale(img).convert("RGB")),
    "blur": ("Flou gaussien", lambda img, p: img.filter(ImageFilter.GaussianBlur(_num(p, "radius", 2.0, lo=0.0, hi=50.0)))),
    "sharpen": ("Accentuation", lambda img, p: img.filter(ImageFilter.UnsharpMask(radius=2, percent=150))),
    "brightness": ("Luminosité", _enhance(ImageEnhance.Brightness)),
    "contrast": ("Contraste", _enhance(ImageEnhance.Contrast)),
    "saturation": ("Saturation", _enhance(ImageEnhance.Color)),
    "invert": ("Négatif", lambda img, p: ImageOps.invert(img.convert("RGB"))),
}


def apply(img: Image.Image, op: str, params: dict) -> Image.Image:
    if op not in OPERATIONS:
        raise ValueError("Transformation inconnue.")
    img = ImageOps.exif_transpose(img)                  # respecte l'orientation EXIF (photos de téléphone)
    result = OPERATIONS[op][1](img, params)
    if result.width * result.height > MAX_PIXELS:       # ex. rotation avec expansion d'une très grande image
        raise ValueError("L'image obtenue serait trop grande (40 Mpx maximum).")
    return result
