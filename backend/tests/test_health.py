from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_reports_database_and_redis(client: TestClient) -> None:
    response = client.get("/api/v1/ready")
    body = response.json()
    assert response.status_code == 200, body
    assert body == {
        "status": "ready",
        "database": {"status": "ok", "detail": None},
        "redis": {"status": "ok", "detail": None},
    }


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_ready_returns_503_when_redis_is_unreachable(client: TestClient, monkeypatch) -> None:
    from app.api.v1 import health
    from app.core.config import get_settings

    broken = get_settings().model_copy(update={"redis_url": "redis://127.0.0.1:1/0"})
    monkeypatch.setattr(health, "get_settings", lambda: broken)

    response = client.get("/api/v1/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["database"]["status"] == "ok"
    assert body["redis"] == {"status": "error", "detail": "Redis is unreachable."}
