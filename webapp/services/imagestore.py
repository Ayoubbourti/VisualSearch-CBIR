"""Stockage des fichiers images sur disque : un dossier par utilisateur + vignettes JPEG."""
import shutil
import uuid
from pathlib import Path

from PIL import Image, ImageOps


def user_dir(storage_dir: Path, user_id: int) -> Path:
    d = Path(storage_dir) / str(user_id)
    (d / "thumbs").mkdir(parents=True, exist_ok=True)
    return d


# Extension imposée par le format RÉEL détecté par Pillow (et non par le nom fourni par le client).
FORMAT_EXT = {"JPEG": ".jpg", "PNG": ".png", "BMP": ".bmp", "GIF": ".gif",
              "WEBP": ".webp", "TIFF": ".tif"}


class InvalidImage(ValueError):
    """Fichier illisible, format non géré ou dimensions excessives."""


def save_stream(storage_dir, user_id, stream, original_name=None, max_pixels=50_000_000) -> str:
    """Valide qu'il s'agit bien d'une image puis copie le flux sur disque.

    Contrôles : (1) Pillow doit pouvoir décoder le fichier (`verify`) ; (2) le format détecté doit
    être dans la liste autorisée ; (3) le nombre de pixels est borné (« bombe de décompression »).
    Retourne le nom unique de stockage : on ne fait JAMAIS confiance au nom fourni par le client.
    """
    stream.seek(0)
    try:
        with Image.open(stream) as im:
            fmt, (w, h) = im.format, im.size
            if fmt not in FORMAT_EXT:
                raise InvalidImage(f"Format non géré : {fmt}")
            if w * h > max_pixels:
                raise InvalidImage(f"Image trop grande ({w}×{h} px).")
            im.verify()
    except InvalidImage:
        raise
    except Exception as exc:                       # fichier corrompu, bombe détectée par Pillow, etc.
        raise InvalidImage(str(exc)) from exc
    stream.seek(0)
    stored = f"{uuid.uuid4().hex}{FORMAT_EXT[fmt]}"
    with open(user_dir(storage_dir, user_id) / stored, "wb") as out:
        shutil.copyfileobj(stream, out)
    return stored


def save_pil(storage_dir, user_id, img: Image.Image) -> str:
    """Enregistre une image PIL (résultat d'une transformation) : PNG si transparence, JPEG sinon."""
    has_alpha = img.mode in ("RGBA", "LA", "P")
    ext, fmt = (".png", "PNG") if has_alpha else (".jpg", "JPEG")
    if not has_alpha:
        img = img.convert("RGB")
    stored = f"{uuid.uuid4().hex}{ext}"
    img.save(user_dir(storage_dir, user_id) / stored, fmt, **({} if has_alpha else {"quality": 92}))
    return stored


def image_info(path) -> tuple[int, int, int]:
    with Image.open(path) as im:
        return im.size[0], im.size[1], Path(path).stat().st_size


def make_thumb(src, dest, size=(256, 256)) -> None:
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail(size, Image.LANCZOS)
        im.save(dest, "JPEG", quality=80)


def thumb_path(storage_dir, user_id, stored_name) -> Path:
    return user_dir(storage_dir, user_id) / "thumbs" / (stored_name + ".jpg")


def delete_files(storage_dir, user_id, stored_name) -> None:
    d = user_dir(storage_dir, user_id)
    (d / stored_name).unlink(missing_ok=True)
    (d / "thumbs" / (stored_name + ".jpg")).unlink(missing_ok=True)
