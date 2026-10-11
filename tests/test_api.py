import pytest
from starlette.testclient import TestClient
from bridge.api.app import app
from bridge.database import SessionLocal, init_db
from bridge.models import Series


@pytest.fixture(scope="module")
def client():
    init_db()
    db = SessionLocal()
    try:
        if not db.query(Series).filter_by(source_id="test-1").first():
            db.add(Series(
                source_id="test-1",
                slug="test-drama",
                title="Test Drama",
                status="active",
                total_episodes=10,
                available_episodes=10,
                local_cover="test-1.webp",
            ))
            db.commit()
    finally:
        db.close()
    with TestClient(app) as c:
        yield c


def login(client):
    return client.post(
        "/admin/login",
        data={"username": "admin", "password": "test-admin-password"},
        follow_redirects=False,
    )


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_get_home_feed(client):
    response = client.get("/api/v1/home?lang=en")
    assert response.status_code == 200
    data = response.json()
    assert "banners" in data
    assert "sections" in data


def test_urls_follow_forwarded_proto(client):
    # Behind Traefik the request arrives over http with X-Forwarded-* headers.
    response = client.get("/api/v1/series?limit=5", headers={"host": "api.example.com"})
    covers = [s["cover_url"] for s in response.json()]
    assert "http://api.example.com/media/covers/test-1.webp" in covers


def test_public_base_url_overrides_request(client, monkeypatch):
    from bridge.config import settings
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://api.dramabiliki.com")
    covers = [s["cover_url"] for s in client.get("/api/v1/series?limit=5").json()]
    assert "https://api.dramabiliki.com/media/covers/test-1.webp" in covers


def test_device_auth_and_favorites(client):
    import uuid
    unique_dev = f"test_phone_{uuid.uuid4().hex[:8]}"
    auth_resp = client.post("/api/v1/auth/device", json={"device_id": unique_dev})
    assert auth_resp.status_code == 200
    token = auth_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    series_list = client.get("/api/v1/series?limit=5").json()
    assert len(series_list) > 0
    test_series_id = series_list[0]["id"]

    fav_resp = client.post("/api/v1/favorites", json={"series_id": test_series_id}, headers=headers)
    assert fav_resp.status_code == 200
    assert fav_resp.json()["is_favorite"] is True

    lib_resp = client.get("/api/v1/me/library?lang=fr", headers=headers)
    assert lib_resp.status_code == 200
    assert any(f["id"] == test_series_id for f in lib_resp.json()["favorites"])


def test_cover_route_rejects_bad_filenames(client):
    assert client.get("/media/covers/..").status_code == 404
    assert client.get("/media/covers/evil.txt").status_code == 404


def test_admin_requires_login(client):
    client.cookies.clear()
    response = client.get("/admin", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"

    # Mutations are refused too
    response = client.post("/admin/sync/trigger", data={"sync_type": "light"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def test_admin_wrong_password(client):
    client.cookies.clear()
    response = client.post(
        "/admin/login", data={"username": "admin", "password": "nope"}, follow_redirects=False
    )
    assert response.headers["location"] == "/admin/login?error=invalid"


def test_admin_dashboard_after_login(client):
    client.cookies.clear()
    response = login(client)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin"

    page = client.get("/admin")
    assert page.status_code == 200
    assert "Bridge Admin" in page.text
    assert "Test Drama" in page.text

    status = client.get("/admin/api/status")
    assert status.status_code == 200
    assert status.json()["sync_running"] is False


def test_admin_banner_without_series(client):
    client.cookies.clear()
    login(client)
    response = client.post(
        "/admin/banners/create",
        data={"title": "Promo", "image_url": "https://example.com/b.jpg", "target_series_id": "", "sort_order": "1"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "Banni" in client.get(response.headers["location"]).text


def test_admin_rejects_cross_origin_post(client):
    client.cookies.clear()
    login(client)
    response = client.post(
        "/admin/banners/create",
        data={"title": "x", "image_url": "https://e.com/x.jpg"},
        headers={"origin": "https://evil.example"},
        follow_redirects=False,
    )
    assert response.status_code == 403


def test_source_proxy_option(monkeypatch):
    from bridge.config import settings
    monkeypatch.setattr(settings, "SOURCE_PROXY", "")
    assert settings.source_client_kwargs() == {}
    monkeypatch.setattr(settings, "SOURCE_PROXY", "http://user:pw@proxy.example:8080")
    assert settings.source_client_kwargs() == {"proxy": "http://user:pw@proxy.example:8080"}
