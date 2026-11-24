"""Descripteurs de couleur et de texture (module pur api/descriptors.py)."""
from io import BytesIO

import numpy as np
import pytest
from PIL import Image

from api import descriptors
from tests.conftest import make_image_bytes


def compute(**kw):
    return descriptors.compute_all(BytesIO(make_image_bytes(**kw)))


def test_vector_dimension_and_histograms():
    r = compute()
    assert len(r["vector"]) == descriptors.VECTOR_DIM == 97
    assert abs(sum(r["color"]["histogram"]["values"]) - 1.0) < 1e-8
    assert abs(sum(r["texture"]["lbp_histogram"]) - 1.0) < 1e-8
    assert len(r["color"]["histogram"]["values"]) == 72
    assert len(r["texture"]["lbp_histogram"]) == 10


def test_layout_matches_retrieval_engine():
    """La structure du vecteur doit rester identique des deux côtés (API <-> moteur de recherche)."""
    from webapp.services.retrieval import FEATURE_GROUPS
    assert [s for _, s in descriptors.LAYOUT] == [s for _, s in FEATURE_GROUPS]


def test_constant_color_skewness_is_finite_and_zero():
    r = compute(color=(50, 50, 50), size=(32, 32))
    for ch in "HSV":
        assert np.isfinite(r["color"]["moments"][ch]["skewness"])
    assert r["color"]["moments"]["H"]["skewness"] == 0.0


def test_glcm_entropy_is_non_negative():
    assert descriptors.glcm_features(np.zeros((32, 32), dtype=np.uint8))["entropy"] >= 0.0


def test_glcm_uniform_image_is_maximally_homogeneous_and_zero_contrast():
    f = descriptors.glcm_features(np.full((40, 40), 128, dtype=np.uint8))
    assert f["contrast"] == pytest.approx(0.0)
    assert f["homogeneity"] == pytest.approx(1.0)
    assert f["energy"] == pytest.approx(1.0)


def test_noise_increases_glcm_contrast_and_entropy():
    smooth, noisy = compute(noise=0, size=(96, 96)), compute(noise=60, size=(96, 96))
    assert noisy["texture"]["glcm"]["contrast"] > smooth["texture"]["glcm"]["contrast"]
    assert noisy["texture"]["glcm"]["entropy"] > smooth["texture"]["glcm"]["entropy"]


def test_pure_red_has_expected_hue_and_dominant_color():
    r = compute(color=(255, 0, 0), size=(40, 40))
    assert r["color"]["moments"]["H"]["mean"] < 0.02                 # teinte ≈ 0 (rouge)
    assert r["color"]["dominant_colors"][0]["hex"] == "#ff0000"
    assert r["color"]["dominant_colors"][0]["proportion"] == pytest.approx(1.0)


def test_dominant_colors_two_halves():
    arr = np.zeros((40, 40, 3), dtype=np.uint8)
    arr[:, :20] = (255, 0, 0)
    arr[:, 20:] = (0, 0, 255)
    buf = BytesIO()
    Image.fromarray(arr).save(buf, "PNG")
    dom = descriptors.compute_all(BytesIO(buf.getvalue()))["color"]["dominant_colors"]
    assert {d["hex"] for d in dom} == {"#ff0000", "#0000ff"}
    assert sum(d["proportion"] for d in dom) == pytest.approx(1.0)


def test_computation_is_deterministic():
    assert compute(noise=30, seed=3)["vector"] == compute(noise=30, seed=3)["vector"]


def test_vector_is_finite_for_all_modes():
    for mode in ("RGB", "RGBA", "L", "P", "CMYK"):
        buf = BytesIO()
        Image.new(mode, (30, 30)).save(buf, "TIFF" if mode == "CMYK" else "PNG")
        assert np.isfinite(descriptors.compute_all(BytesIO(buf.getvalue()))["vector"]).all(), mode


def test_tiny_image_does_not_crash():
    assert len(compute(size=(3, 3))["vector"]) == 97


def test_large_image_is_downscaled():
    img = descriptors.load_image(BytesIO(make_image_bytes(size=(1000, 500))))
    assert max(img.size) == descriptors.MAX_SIDE


def test_corrupted_image_raises():
    with pytest.raises(Exception):
        descriptors.compute_all(BytesIO(b"not an image"))
