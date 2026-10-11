import pytest
from starlette.testclient import TestClient
from bridge.api.app import app
from bridge.database import init_db

@pytest.fixture(scope="module")
def client():
    init_db()
    with TestClient(app) as c:
        yield c

def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"

def test_get_home_feed(client):
    response = client.get("/api/v1/home?lang=en")
    assert response.status_code == 200
    data = response.json()
    assert "banners" in data
    assert "sections" in data

def test_device_auth_and_favorites(client):
    import uuid
    unique_dev = f"test_phone_{uuid.uuid4().hex[:8]}"
    auth_resp = client.post("/api/v1/auth/device", json={"device_id": unique_dev})
    assert auth_resp.status_code == 200
    token = auth_resp.json()["access_token"]
    assert token

    headers = {"Authorization": f"Bearer {token}"}

    # 2. List series
    series_resp = client.get("/api/v1/series?limit=5")
    assert series_resp.status_code == 200
    series_list = series_resp.json()
    assert len(series_list) > 0
    test_series_id = series_list[0]["id"]

    # 3. Toggle favorite
    fav_resp = client.post(
        "/api/v1/favorites",
        json={"series_id": test_series_id},
        headers=headers,
    )
    assert fav_resp.status_code == 200
    assert fav_resp.json()["is_favorite"] is True

    # 4. Check library
    lib_resp = client.get("/api/v1/me/library", headers=headers)
    assert lib_resp.status_code == 200
    favs = lib_resp.json()["favorites"]
    assert any(f["id"] == test_series_id for f in favs)

def test_admin_dashboard_page(client):
    response = client.get("/admin")
    assert response.status_code == 200
    assert "DramaBiliki Bridge Admin" in response.text
