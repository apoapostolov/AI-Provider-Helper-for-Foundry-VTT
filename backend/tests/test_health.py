from __future__ import annotations


def test_health(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "ai-provider-library"
    assert body["port"] == 8090


def test_catalog_seed(client) -> None:
    response = client.get("/v1/catalog")
    assert response.status_code == 200
    body = response.json()
    ids = [row["id"] for row in body["providers"]]
    assert "openai" in ids
    assert "huggingface" in ids
    assert "openrouter" in ids


def test_catalog_filters_image_gen(client) -> None:
    response = client.get("/v1/catalog", params={"capability": "image-gen"})
    body = response.json()
    ids = {row["id"] for row in body["providers"]}
    assert "openai" in ids
    assert "ollama" not in ids


def test_fetch_image_blocks_localhost(client) -> None:
    response = client.post("/v1/fetch-image", json={"url": "http://127.0.0.1/secret.png"})
    assert response.status_code == 400


def _preflight(client, origin: str):
    return client.options(
        "/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Private-Network": "true",
        },
    )


def test_cors_allows_lan_foundry_origin(client) -> None:
    response = _preflight(client, "http://192.168.1.217:30002")
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://192.168.1.217:30002"
    assert response.headers.get("access-control-allow-private-network") == "true"


def test_cors_rejects_public_origin(client) -> None:
    response = _preflight(client, "https://evil.example")
    assert response.headers.get("access-control-allow-origin") in (None, "")


def test_cors_allows_hosted_origin_when_configured(tmp_path) -> None:
    from app.config import Config
    from app.main import create_app
    from fastapi.testclient import TestClient

    cfg = Config(
        host="127.0.0.1",
        port=8090,
        cache_dir=tmp_path / "cache",
        cors_origins="https://*.forge-vtt.com",
    )
    hosted = TestClient(create_app(cfg))
    response = _preflight(hosted, "https://abc.forge-vtt.com")
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "https://abc.forge-vtt.com"
    blocked = _preflight(hosted, "https://evil.example")
    assert blocked.headers.get("access-control-allow-origin") in (None, "")
