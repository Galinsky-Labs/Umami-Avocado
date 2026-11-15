from conftest import settings
from fastapi.testclient import TestClient

from umami_api.main import create_app


def make(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=root></div>")
    (dist / "assets" / "app-123.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("private-owner-fixture")
    monkeypatch.setenv("WEB_DIST_DIR", str(dist))
    return TestClient(create_app(settings()))


def test_console_is_served_with_spa_fallback_and_security_headers(tmp_path, monkeypatch):
    client = make(tmp_path, monkeypatch)
    root = client.get("/")
    assert root.status_code == 200 and "root" in root.text
    assert "frame-ancestors 'none'" in root.headers["content-security-policy"]
    assert client.get("/projects/abc").text == root.text
    asset = client.get("/assets/app-123.js")
    assert asset.status_code == 200 and "immutable" in asset.headers["cache-control"]
    assert client.get("/assets/missing.js").status_code == 404
    assert "private-owner-fixture" not in client.get("/../secret.txt").text
    assert "private-owner-fixture" not in client.get("/%2e%2e/secret.txt").text


def test_api_paths_never_fall_back_to_the_console(tmp_path, monkeypatch):
    client = make(tmp_path, monkeypatch)
    missing = client.get("/api/unknown")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert client.post("/api/health").status_code == 405
    assert client.post("/anything").status_code == 404


def test_without_a_build_non_api_paths_are_plain_404(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_DIST_DIR", str(tmp_path / "none"))
    client = TestClient(create_app(settings()))
    assert client.get("/").status_code == 404
