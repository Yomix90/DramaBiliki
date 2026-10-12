import io
import shutil
import subprocess
import time
import uuid

import pytest
from PIL import Image
from starlette.testclient import TestClient

from bridge import app_settings
from bridge.api.app import app
from bridge.database import SessionLocal, init_db
from bridge.models import Episode, Series
from bridge.parsing import parse_video_name


@pytest.fixture(scope="module")
def client():
    init_db()
    with TestClient(app) as c:
        yield c


def admin_login(client):
    client.cookies.clear()
    r = client.post("/admin/login", data={"username": "admin", "password": "test-admin-password"}, follow_redirects=False)
    assert r.status_code == 303


@pytest.mark.parametrize("name,expected", [
    ("Harem Wars - System vs. Queen - S01E03.ts", ("Harem Wars - System vs. Queen", 1, 3)),
    ("Harem.Wars.S02E10.1080p.WEB-DL.x264.mkv", ("Harem Wars", 2, 10)),
    ("[Telegram] Rich Girl (EP 09) 720p.mp4", ("Rich Girl", None, 9)),
    ("video_2026-10-11_20-01-33.mp4", (None, None, None)),
    ("The_Boss_1x05.ts", ("The Boss", 1, 5)),
])
def test_parse_file_names(name, expected):
    assert tuple(parse_video_name(name, is_filename=True)) == expected


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def test_register_upgrades_guest_and_login(client):
    device = f"dev-{uuid.uuid4().hex[:8]}"
    guest = client.post("/api/v1/auth/device", json={"device_id": device}).json()
    headers = {"Authorization": f"Bearer {guest['access_token']}"}
    assert guest["is_guest"] is True

    email = f"user{uuid.uuid4().hex[:6]}@example.com"
    r = client.post("/api/v1/auth/register", json={"email": email, "password": "secret123", "username": "Yasmine"}, headers=headers)
    assert r.status_code == 200, r.text
    account = r.json()
    assert account["user_id"] == guest["user_id"]  # same user: favorites/history kept
    assert account["is_guest"] is False

    assert client.post("/api/v1/auth/register", json={"email": email, "password": "secret123"}).status_code == 409
    assert client.post("/api/v1/auth/login", json={"email": email, "password": "wrong"}).status_code == 401

    login = client.post("/api/v1/auth/login", json={"email": email.upper(), "password": "secret123"}).json()
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {login['access_token']}"}).json()
    assert me["email"] == email and me["username"] == "Yasmine" and me["is_guest"] is False

    # The device gets a brand-new guest after logging out
    again = client.post("/api/v1/auth/device", json={"device_id": device}).json()
    assert again["user_id"] != guest["user_id"]


def test_register_validation(client):
    assert client.post("/api/v1/auth/register", json={"email": "nope", "password": "secret123"}).status_code == 400
    assert client.post("/api/v1/auth/register", json={"email": "a@b.co", "password": "123"}).status_code == 400


# ---------------------------------------------------------------------------
# App update & ads
# ---------------------------------------------------------------------------

def test_app_version_and_ads_config(client):
    app_settings.set_many({"app_latest_version": "1.3.0", "app_min_version": "1.1.0",
                           "app_update_url": "https://example.com/app.apk", "app_update_force": "false",
                           "ads_enabled": "true", "ads_every_n_episodes": "5"})
    old = client.get("/api/v1/app/version?current=1.0.9").json()
    assert old["has_update"] and old["force_update"]
    recent = client.get("/api/v1/app/version?current=1.2.0").json()
    assert recent["has_update"] and not recent["force_update"]
    assert not client.get("/api/v1/app/version?current=1.3.0").json()["has_update"]

    ads = client.get("/api/v1/config/ads").json()
    assert ads == {"enabled": True, "every_n_episodes": 5, "rewarded_unit_id": ""}


# ---------------------------------------------------------------------------
# Admin: series & uploads
# ---------------------------------------------------------------------------

def _png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (300, 400), (200, 30, 60)).save(buf, "PNG")
    return buf.getvalue()


def test_admin_creates_series_with_cover(client):
    admin_login(client)
    r = client.post(
        "/admin/series/new",
        data={"title": "Manual Drama", "title_fr": "Drame Manuel", "description": "Synopsis",
              "genres": "Romance, Vengeance", "rating": "4.6", "release_year": "2026", "status": "active", "is_new": "true"},
        files={"cover": ("cover.png", _png_bytes(), "image/png")},
        follow_redirects=False,
    )
    assert r.status_code == 303
    series_id = int(r.headers["location"].split("/admin/series/")[1].split("?")[0])
    db = SessionLocal()
    try:
        s = db.get(Series, series_id)
        assert s.local_cover and s.titles_json["fr"] == "Drame Manuel"
        assert sorted(g.name for g in s.genres) == ["Romance", "Vengeance"]
        assert s.release_year == 2026 and s.source_type == "upload"
    finally:
        db.close()
    page = client.get(f"/admin/series/{series_id}")
    assert page.status_code == 200 and "Manual Drama" in page.text
    for path in ("/admin/upload", "/admin/users", "/admin/app"):
        assert client.get(path).status_code == 200, path


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_chunked_upload_creates_series_from_file_name(client, tmp_path):
    admin_login(client)
    app_settings.set_many({"upload_destination": "local", "upload_convert_ts": "true"})
    src = tmp_path / "clip.ts"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=360x640:rate=25",
                    "-f", "lavfi", "-i", "sine=frequency=440", "-t", "3", "-c:v", "libx264", "-c:a", "aac",
                    "-f", "mpegts", str(src)], check=True)
    data = src.read_bytes()
    name = f"Upload Test {uuid.uuid4().hex[:5]} - S01E03.ts"

    detected = client.post("/admin/uploads/detect", json={"filenames": [name]}).json()[0]
    assert detected["episode"] == 3 and detected["title"].startswith("Upload Test")

    job = client.post("/admin/uploads/init", json={"filename": name, "size": len(data), "mode": "auto"}).json()
    chunk = 64 * 1024
    offsets = list(range(0, len(data), chunk))[::-1]  # out of order on purpose
    for offset in offsets:
        assert client.put(f"/admin/uploads/{job['id']}?offset={offset}", content=data[offset:offset + chunk]).status_code == 200
    assert client.post(f"/admin/uploads/{job['id']}/complete").status_code == 200

    for _ in range(100):
        status = next(j for j in client.get("/admin/uploads/jobs").json() if j["id"] == job["id"])
        if status["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert status["status"] == "done", status

    db = SessionLocal()
    try:
        series = db.get(Series, status["result_series_id"])
        assert series.title == detected["title"] and series.local_cover
        ep = db.query(Episode).filter(Episode.series_id == series.id).one()
        assert ep.num == 3 and ep.local_file.endswith(".mp4") and ep.mime_type == "video/mp4" and ep.duration == 3
    finally:
        db.close()

    video = client.get(f"/stream/{series.id}/3.mp4", headers={"Range": "bytes=0-99"})
    assert video.status_code == 206 and len(video.content) == 100


def test_incomplete_upload_is_refused(client):
    admin_login(client)
    job = client.post("/admin/uploads/init", json={"filename": "A - S01E01.mp4", "size": 1000}).json()
    client.put(f"/admin/uploads/{job['id']}?offset=500", content=b"x" * 500)
    r = client.post(f"/admin/uploads/{job['id']}/complete")
    assert r.status_code == 400 and "incomplet" in r.json()["error"]
    assert client.post("/admin/uploads/init", json={"filename": "notes.txt", "size": 10}).status_code == 400


# ---------------------------------------------------------------------------
# Unplayable files (HLS fMP4 fragments without init segment)
# ---------------------------------------------------------------------------

FRAGMENT = b"\x00\x00\x04\xf8moof" + b"\x00" * 600  # what the broken .ts files start with


def test_check_header():
    from bridge.video_check import MISSING_INIT, check_header
    assert check_header(FRAGMENT) == MISSING_INIT
    assert check_header(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 40) is None
    ts = bytearray(400); ts[0] = ts[188] = 0x47
    assert check_header(bytes(ts)) is None


def test_upload_rejects_fragment_and_series_check_flags_it(client):
    admin_login(client)
    app_settings.set_many({"upload_destination": "local", "upload_convert_ts": "false"})
    name = f"Broken {uuid.uuid4().hex[:5]} - S01E01.ts"
    job = client.post("/admin/uploads/init", json={"filename": name, "size": len(FRAGMENT)}).json()
    client.put(f"/admin/uploads/{job['id']}?offset=0", content=FRAGMENT)
    client.post(f"/admin/uploads/{job['id']}/complete")
    for _ in range(50):
        status = next(j for j in client.get("/admin/uploads/jobs").json() if j["id"] == job["id"])
        if status["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert status["status"] == "error" and "init" in status["message"]

    # An already-imported broken episode is flagged by the series analysis
    from bridge import uploads
    db = SessionLocal()
    try:
        series = uploads.create_series(db, f"Legacy {uuid.uuid4().hex[:5]}")
        uploads.LOCAL_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
        (uploads.LOCAL_VIDEOS_DIR / f"broken-{series.id}.ts").write_bytes(FRAGMENT)
        db.add(Episode(series_id=series.id, num=1, local_file=f"broken-{series.id}.ts", mime_type="video/mp2t"))
        db.commit()
        series_id = series.id
    finally:
        db.close()
    page = client.get(f"/admin/series/{series_id}?check=1").text
    assert "épisode(s) illisible(s)" in page
    ep_id = SessionLocal().query(Episode).filter(Episode.series_id == series_id).one().id
    client.post(f"/admin/series/{series_id}/delete-episodes", data={"episode_id": str(ep_id)})
    assert SessionLocal().query(Episode).filter(Episode.series_id == series_id).count() == 0


def test_genres_api_hides_empty_categories_and_admin_page(client):
    from bridge.models import Genre
    db = SessionLocal()
    try:
        db.add(Genre(slug=f"empty-{uuid.uuid4().hex[:5]}", name="Empty Genre"))
        db.commit()
    finally:
        db.close()
    names = [g["name"] for g in client.get("/api/v1/genres").json()]
    assert "Empty Genre" not in names
    admin_login(client)
    page = client.get("/admin/genres")
    assert page.status_code == 200 and "Empty Genre" in page.text


def test_apk_download_keeps_content_length(client, tmp_path):
    from bridge.api.v1.routes_app import APK_DIR, LATEST_APK
    APK_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_APK.write_bytes(b"PK" + b"x" * 5000)
    r = client.get("/download/app.apk", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers.get("content-length") == "5002" and "content-encoding" not in r.headers
    # JSON is still compressed
    assert client.get("/api/v1/genres", headers={"Accept-Encoding": "gzip"}).status_code == 200
