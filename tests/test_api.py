"""API REST Flask-RESTful (client de test, sans serveur réseau)."""
from io import BytesIO

import pytest

from api.app import create_app
from tests.conftest import make_image_bytes


@pytest.fixture
def api():
    return create_app(TESTING=True).test_client()


def files(*pairs):
    return {"images": [(BytesIO(b), n) for n, b in pairs]}


def test_health(api):
    r = api.get("/api/health")
    assert r.status_code == 200 and r.json["status"] == "ok" and r.json["vector_dim"] == 97


def test_info_describes_layout(api):
    j = api.get("/api/descriptors/info").json
    assert sum(b["size"] for b in j["layout"]) == j["vector_dim"] == 97
    assert j["parameters"]["lbp"]["method"] == "uniform"


def test_full_descriptors_single_and_batch(api):
    png = make_image_bytes()
    r = api.post("/api/descriptors", data=files(("a.png", png), ("b.png", png)), content_type="multipart/form-data")
    assert r.status_code == 200 and r.json["count"] == 2
    assert [x["filename"] for x in r.json["results"]] == ["a.png", "b.png"]
    assert len(r.json["results"][0]["vector"]) == 97


def test_color_and_texture_endpoints_return_only_their_block(api):
    d = files(("a.png", make_image_bytes()))
    color = api.post("/api/descriptors/color", data=d, content_type="multipart/form-data").json["results"][0]
    assert "color" in color and "texture" not in color
    d = files(("a.png", make_image_bytes()))
    tex = api.post("/api/descriptors/texture", data=d, content_type="multipart/form-data").json["results"][0]
    assert "texture" in tex and "color" not in tex


def test_one_bad_image_does_not_fail_the_batch(api):
    r = api.post("/api/descriptors", data=files(("ok.png", make_image_bytes()), ("bad.png", b"garbage")),
                 content_type="multipart/form-data")
    assert r.status_code == 200
    ok, bad = r.json["results"]
    assert "vector" in ok and "error" in bad and "vector" not in bad


def test_missing_files_is_400(api):
    assert api.post("/api/descriptors").status_code == 400


def test_too_many_files_is_413():
    c = create_app(TESTING=True, MAX_FILES=2).test_client()
    png = make_image_bytes()
    r = c.post("/api/descriptors", data=files(*[(f"{i}.png", png) for i in range(3)]),
               content_type="multipart/form-data")
    assert r.status_code == 413


def test_api_key_enforced_except_health():
    c = create_app(TESTING=True, API_KEY="s3cret").test_client()
    d = lambda: files(("a.png", make_image_bytes()))            # noqa: E731
    assert c.get("/api/health").status_code == 200
    assert c.post("/api/descriptors", data=d(), content_type="multipart/form-data").status_code == 401
    assert c.post("/api/descriptors", data=d(), content_type="multipart/form-data",
                  headers={"X-API-Key": "wrong"}).status_code == 401
    assert c.post("/api/descriptors", data=d(), content_type="multipart/form-data",
                  headers={"X-API-Key": "s3cret"}).status_code == 200


def test_unknown_route_returns_json_404(api):
    r = api.get("/api/nope")
    assert r.status_code == 404 and r.is_json
