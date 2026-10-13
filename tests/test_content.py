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


def test_backup_export_and_restore_roundtrip(client, tmp_path):
    import zipfile
    from bridge import backup
    from bridge.config import settings
    admin_login(client)
    title = f"Backup Drama {uuid.uuid4().hex[:5]}"
    db = SessionLocal()
    try:
        from bridge import uploads
        series = uploads.create_series(db, title)
        series.local_cover = f"{series.source_id}.webp"
        db.commit()
        (settings.COVERS_DIR / series.local_cover).write_bytes(b"RIFF....WEBPVP8 ")
    finally:
        db.close()

    r = client.get("/admin/backup/download?covers=1")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    archive = tmp_path / "backup.zip"
    archive.write_bytes(r.content)
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
    assert "dramabiliki.db" in names and "manifest.json" in names and any(n.startswith("covers/") for n in names)

    # Simulate a fresh server: the series and its cover disappear
    db = SessionLocal()
    try:
        db.delete(db.query(Series).filter(Series.title == title).one())
        db.commit()
    finally:
        db.close()
    for f in settings.COVERS_DIR.glob("up-*.webp"):
        f.unlink()

    # Refused without confirmation, refused for a non-database file
    assert "confirmation" in client.post("/admin/backup/restore", files={"file": ("b.zip", archive.read_bytes())}).text
    bad = client.post("/admin/backup/restore", data={"confirm": "yes"}, files={"file": ("x.db", b"not a database")})
    assert "refusée" in bad.text

    ok = client.post("/admin/backup/restore", data={"confirm": "yes"}, files={"file": ("b.zip", archive.read_bytes())})
    assert ok.status_code == 200 and "Restauration terminée" in ok.text
    db = SessionLocal()
    try:
        restored = db.query(Series).filter(Series.title == title).one()
        assert (settings.COVERS_DIR / restored.local_cover).exists()
    finally:
        db.close()
    assert any((settings.DATA_DIR / "backups").glob("before-restore-*.db"))
    assert backup.sqlite_path() is not None


def test_chunked_apk_upload_then_settings(client):
    from bridge.api.v1.routes_app import LATEST_APK
    admin_login(client)
    apk = b"PK" + bytes(range(256)) * 400  # ~100 KB fake APK
    job = client.post("/admin/app/apk/init", json={"size": len(apk)}).json()
    chunk = 30000
    for offset in range(0, len(apk), chunk):
        assert client.put(f"/admin/app/apk/{job['id']}?offset={offset}", content=apk[offset:offset + chunk]).status_code == 200
    done = client.post(f"/admin/app/apk/{job['id']}/complete")
    assert done.status_code == 200 and done.json()["apk"]["sha"]
    assert LATEST_APK.read_bytes() == apk

    # Version settings are saved by a plain form post (no file)
    r = client.post("/admin/app/update", data={"latest_version": "2.0.0", "min_version": "1.0.0", "notes": "n"}, follow_redirects=False)
    assert r.status_code == 303
    assert client.get("/api/v1/app/version?current=1.9.0").json()["latest_version"] == "2.0.0"
    page = client.get("/admin/app").text
    assert "APK actuellement publié" in page and done.json()["apk"]["sha"] in page

    # A non-APK file is rejected
    job = client.post("/admin/app/apk/init", json={"size": 2048}).json()
    client.put(f"/admin/app/apk/{job['id']}?offset=0", content=b"x" * 2048)
    assert client.post(f"/admin/app/apk/{job['id']}/complete").status_code == 400


# ---------------------------------------------------------------------------
# Series information files
# ---------------------------------------------------------------------------

def test_parse_example_info_files():
    from pathlib import Path
    from bridge.metadata import parse_metadata
    root = Path(__file__).resolve().parent.parent / "docs" / "exemples"
    for name in ("info.txt", "info.json"):
        meta = parse_metadata(name, (root / name).read_bytes())
        assert meta["title"] == "Harem Wars - System vs. Queen"
        assert meta["genres"] == ["Romance", "Historique", "Vengeance", "Palais"]
        assert meta["description"] and meta["title_fr"] and meta["title_ar"]
        assert meta["rating"] == 4.8 and meta["release_year"] == 2024


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_batch_upload_applies_info_file(client, tmp_path):
    admin_login(client)
    app_settings.set_many({"upload_destination": "local", "upload_convert_ts": "true"})
    title = f"Info Drama {uuid.uuid4().hex[:5]}"
    info = f"Titre: {title}\nGenres: Romance, Vengeance\nNote: 4.2\nSynopsis:\nLigne 1\nLigne 2\n".encode()
    meta = client.post("/admin/uploads/metadata",
                       files={"file": ("info.txt", info), "cover": ("cover.png", _png_bytes(), "image/png")}).json()
    assert meta["meta"]["title"] == title and meta["has_cover"]

    src = tmp_path / "ep.ts"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=360x640:rate=25",
                    "-f", "lavfi", "-i", "sine=frequency=440", "-t", "2", "-c:v", "libx264", "-c:a", "aac",
                    "-f", "mpegts", str(src)], check=True)
    data = src.read_bytes()
    # The file name carries another title: the info file wins
    job = client.post("/admin/uploads/init", json={"filename": "whatever - S01E02.ts", "size": len(data),
                                                   "mode": "auto", "meta_id": meta["id"]}).json()
    client.put(f"/admin/uploads/{job['id']}?offset=0", content=data)
    client.post(f"/admin/uploads/{job['id']}/complete")
    for _ in range(100):
        status = next(j for j in client.get("/admin/uploads/jobs").json() if j["id"] == job["id"])
        if status["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert status["status"] == "done", status
    db = SessionLocal()
    try:
        s = db.get(Series, status["result_series_id"])
        assert s.title == title and s.description == "Ligne 1\nLigne 2" and s.rating == 4.2
        assert sorted(g.name for g in s.genres) == ["Romance", "Vengeance"] and s.local_cover
    finally:
        db.close()


def test_series_form_info_file_endpoints(client):
    admin_login(client)
    r = client.post("/admin/metadata/parse", files={"file": ("i.json", b'{"title":"T","genres":"A, B"}')})
    assert r.json() == {"title": "T", "genres": ["A", "B"]}
    assert client.post("/admin/metadata/parse", files={"file": ("i.txt", b"rien")}).status_code == 400
    db = SessionLocal()
    try:
        from bridge import uploads
        sid = uploads.create_series(db, f"Plain {uuid.uuid4().hex[:5]}").id
        db.commit()
    finally:
        db.close()
    client.post(f"/admin/series/{sid}/metadata", files={"file": ("i.txt", "Synopsis: Résumé\nGenres: Drame".encode())})
    db = SessionLocal()
    try:
        s = db.get(Series, sid)
        assert s.description == "Résumé" and [g.name for g in s.genres] == ["Drame"]
    finally:
        db.close()


def test_info_file_cover_url(client, monkeypatch):
    import bridge.metadata as md
    from bridge.metadata import parse_metadata
    info = ("Titre: Cover Drama\nTitre FR: \nCouverture: https://cdn.example.com/c/480.webp\n"
            "Genres: Action\nNote: \nSynopsis:\nLigne\n\nSynopsis FR: \n").encode()
    meta = parse_metadata("info.txt", info)
    assert meta == {"title": "Cover Drama", "cover_url": "https://cdn.example.com/c/480.webp",
                    "genres": ["Action"], "description": "Ligne"}

    admin_login(client)
    # Download works: the poster is stored for the batch
    async def ok(url):
        return _png_bytes()
    monkeypatch.setattr(md, "download_cover", ok)
    r = client.post("/admin/uploads/metadata", files={"file": ("info.txt", info)}).json()
    assert r["has_cover"] and not r["cover_url_failed"]

    # Download fails: the URL is kept so the app loads the image directly
    async def ko(url):
        return None
    monkeypatch.setattr(md, "download_cover", ko)
    r = client.post("/admin/uploads/metadata", files={"file": ("info.txt", info)}).json()
    assert not r["has_cover"] and r["cover_url_failed"]
    db = SessionLocal()
    try:
        from bridge import uploads
        s = uploads.create_series(db, "Cover target")
        md.apply_metadata(db, s, meta)
        assert s.cover_url == "https://cdn.example.com/c/480.webp"
        db.rollback()
    finally:
        db.close()
