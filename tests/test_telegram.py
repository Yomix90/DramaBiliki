import asyncio
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from bridge.api.app import app
from bridge.database import SessionLocal, init_db
from bridge.models import Episode, Series, TelegramChannel
from bridge.telegram import sync as tg_sync
from bridge.telegram.client import telegram_service
from bridge.telegram.sync import parse_caption


@pytest.mark.parametrize("caption,expected", [
    ("Mon Drama - Épisode 3", ("Mon Drama", 3)),
    ("The CEO's Secret Wife EP12", ("The CEO's Secret Wife", 12)),
    ("#TheCEO #5", ("TheCEO", 5)),
    ("مسلسل الحب الأخير الحلقة ٧", ("مسلسل الحب الأخير", 7)),
    ("Mafia Boss 3/80", ("Mafia Boss", 3)),
    ("Love in Paris", ("Love in Paris", None)),
    ("Episode 4", (None, 4)),
    ("", (None, None)),
])
def test_parse_caption(caption, expected):
    assert parse_caption(caption) == expected


def _video(msg_id, caption, size=1000):
    return SimpleNamespace(
        id=msg_id,
        message=caption,
        video=object(),
        file=SimpleNamespace(size=size, duration=95, mime_type="video/mp4"),
    )


class FakeClient:
    def __init__(self, messages):
        self.messages = messages

    async def iter_messages(self, peer, min_id=0, reverse=True):
        for m in self.messages:
            if m.id > min_id:
                yield m

    async def download_media(self, *args, **kwargs):
        return None


@pytest.fixture()
def channel():
    init_db()
    db = SessionLocal()
    ch = TelegramChannel(peer_id=-1009990001, access_hash=1, title="Ma Chaîne", mode="caption")
    db.add(ch)
    db.commit()
    yield db, ch
    for s in db.query(Series).filter(Series.tg_channel_id == ch.id).all():
        db.delete(s)
    db.delete(ch)
    db.commit()
    db.close()


def test_sync_groups_videos_by_caption(channel, monkeypatch):
    db, ch = channel
    messages = [
        _video(10, "Love Story - Episode 1"),
        SimpleNamespace(id=11, message="just text", video=None, file=None),
        _video(12, "Love Story - Episode 2"),
        _video(13, "Other Drama EP 1"),
        _video(14, "Love Story"),  # no number -> next free (3)
    ]

    async def fake_client(*args):
        return FakeClient(messages)

    monkeypatch.setattr(telegram_service, "authorized_client", fake_client)
    added = asyncio.run(tg_sync.sync_channel(db, ch))
    assert added == 4

    love = db.query(Series).filter(Series.tg_channel_id == ch.id, Series.title == "Love Story").one()
    assert love.source_type == "telegram"
    assert love.available_episodes == 3
    assert sorted(e.num for e in love.episodes) == [1, 2, 3]
    assert love.genres == []  # no automatic category per channel
    assert ch.last_message_id == 14

    # Second run only looks at newer messages and is idempotent
    messages.append(_video(15, "Love Story - Episode 4"))
    assert asyncio.run(tg_sync.sync_channel(db, ch)) == 1


def test_single_mode_makes_one_series(channel, monkeypatch):
    db, ch = channel
    ch.mode = "single"
    db.commit()

    async def fake_client(*args):
        return FakeClient([_video(1, "Trailer"), _video(2, ""), _video(3, "whatever")])

    monkeypatch.setattr(telegram_service, "authorized_client", fake_client)
    asyncio.run(tg_sync.sync_channel(db, ch))
    series = db.query(Series).filter(Series.tg_channel_id == ch.id).all()
    assert len(series) == 1
    assert series[0].title == "Ma Chaîne"
    assert series[0].available_episodes == 3


def test_stream_supports_range_requests(channel, monkeypatch):
    db, ch = channel
    payload = bytes(range(256)) * 4  # 1024 bytes
    series = Series(source_id="tg-test-stream", slug="tg-test-stream", title="S", source_type="telegram",
                    tg_channel_id=ch.id, status="active", available_episodes=1, total_episodes=1)
    db.add(series)
    db.flush()
    db.add(Episode(series_id=series.id, num=1, tg_peer_id=ch.peer_id, tg_message_id=42,
                   file_size=len(payload), mime_type="video/mp4"))
    db.commit()

    async def fake_get_message(peer_id, access_hash, message_id, refresh=False):
        assert message_id == 42
        return SimpleNamespace(file=SimpleNamespace(size=len(payload)))

    async def fake_iter_bytes(message, start, end):
        for i in range(start, end + 1, 100):
            yield payload[i:min(i + 100, end + 1)]

    monkeypatch.setattr(telegram_service, "get_message", fake_get_message)
    monkeypatch.setattr(telegram_service, "iter_bytes", fake_iter_bytes)

    with TestClient(app) as client:
        r = client.get(f"/stream/{series.id}/1.mp4", headers={"Range": "bytes=100-299"})
        assert r.status_code == 206
        assert r.headers["content-range"] == "bytes 100-299/1024"
        assert r.content == payload[100:300]

        r = client.get(f"/stream/{series.id}/1.mp4")
        assert r.status_code == 200
        assert r.content == payload

        assert client.get(f"/stream/{series.id}/1.mp4", headers={"Range": "bytes=5000-"}).status_code == 416
        assert client.get(f"/stream/{series.id}/9.mp4").status_code == 404
        assert client.get(f"/subtitles/{series.id}/1").text.startswith("WEBVTT")


# ---------------------------------------------------------------------------
# Admin: deleting on Telegram, orphan videos, dashboard
# ---------------------------------------------------------------------------

def _admin(client):
    client.cookies.clear()
    client.post("/admin/login", data={"username": "admin", "password": "test-admin-password"})


def test_bulk_delete_and_series_delete_remove_telegram_messages(channel, monkeypatch):
    db, ch = channel
    deleted = []

    async def fake_delete(peer_id, access_hash, ids):
        deleted.extend(ids)
        return len(ids), ""

    monkeypatch.setattr(telegram_service, "delete_messages", fake_delete)
    series = Series(source_id=f"tg-del-{ch.id}", slug=f"tg-del-{ch.id}", title="Del", source_type="telegram",
                    tg_channel_id=ch.id, status="active")
    db.add(series)
    db.flush()
    eps = [Episode(series_id=series.id, num=n, tg_peer_id=ch.peer_id, tg_message_id=100 + n) for n in (1, 2, 3)]
    db.add_all(eps)
    db.commit()
    ids = [e.id for e in eps]
    series_id = series.id

    with TestClient(app) as client:
        _admin(client)
        r = client.post(f"/admin/series/{series.id}/delete-episodes",
                        data={"episode_id": [str(ids[0]), str(ids[1])], "delete_telegram": "1"})
        assert "2 épisode(s) supprimé(s)" in r.text and sorted(deleted) == [101, 102]

        # Without the option, Telegram is left untouched
        deleted.clear()
        client.post(f"/admin/series/{series.id}/delete", data={})
        assert deleted == []
    db.expire_all()
    assert db.get(Series, series_id) is None


def test_orphan_videos_listing_attach_and_delete(channel, monkeypatch):
    db, ch = channel
    msgs = [_video(201, "Lost Love EP 2"), _video(202, "Lost Love EP 1"), _video(203, "")]
    db.add(Series(source_id=f"tg-or-{ch.id}", slug=f"tg-or-{ch.id}", title="Known", status="active"))
    db.flush()
    known = db.query(Series).filter_by(source_id=f"tg-or-{ch.id}").one()
    db.add(Episode(series_id=known.id, num=1, tg_peer_id=ch.peer_id, tg_message_id=203))
    db.commit()

    class Client(FakeClient):
        async def iter_messages(self, peer, limit=None, min_id=0, reverse=False):
            for m in self.messages:
                yield m

        async def get_messages(self, peer, ids):
            return [m for m in self.messages if m.id in ids]

    async def fake_client(*args):
        return Client(msgs)

    async def fake_status():
        return {"configured": True, "authorized": True, "account": "Me", "pending_phone": "", "needs_password": False, "error": ""}

    monkeypatch.setattr(telegram_service, "authorized_client", fake_client)
    monkeypatch.setattr(telegram_service, "status", fake_status)
    deleted = []

    async def fake_delete(peer_id, access_hash, ids):
        deleted.extend(ids)
        return len(ids), ""

    monkeypatch.setattr(telegram_service, "delete_messages", fake_delete)

    with TestClient(app) as client:
        _admin(client)
        page = client.get("/admin/telegram/orphans").text
        assert f"{ch.peer_id}:201" in page and f"{ch.peer_id}:202" in page
        assert f"{ch.peer_id}:203" not in page  # already an episode

        r = client.post("/admin/telegram/orphans/attach", data={
            "item": [f"{ch.peer_id}:201", f"{ch.peer_id}:202"], "series_id": "new", "new_title": "Lost Love"})
        assert "2 vidéo(s) ajoutée(s)" in r.text
        lost = db.query(Series).filter_by(title="Lost Love").one()
        assert sorted((e.num, e.tg_message_id) for e in lost.episodes) == [(1, 202), (2, 201)]

        client.post("/admin/telegram/orphans/delete", data={"item": [f"{ch.peer_id}:999"]})
        assert deleted == [999]
        db.delete(lost)
        db.delete(known)
        db.commit()


def test_dashboard_shows_live_activity_and_disk():
    from bridge.activity import record_progress, record_stream, snapshot
    record_progress(424242, 1, 1)
    record_stream("10.0.0.9", 1, 1)
    live = snapshot()
    assert live["viewers"] >= 1 and live["streams"] >= 1
    with TestClient(app) as client:
        _admin(client)
        page = client.get("/admin?tab=overview").text
        assert "Spectateurs actifs" in page and "Stockage du serveur" in page
        assert client.get("/admin/api/status").json()["live"]["viewers"] >= 1
        r = client.post("/admin/cache/clear", follow_redirects=False)
        assert r.status_code == 303


def test_legacy_session_migrates_to_accounts_and_channels_route_per_account(monkeypatch):
    from bridge.models import AppConfig, TelegramAccount
    from bridge.telegram import client as tg_client
    init_db()
    db = SessionLocal()
    for row in db.query(TelegramAccount).all():
        db.delete(row)
    db.add(AppConfig(key=tg_client.KEY_SESSION, value="legacy-session", description=""))
    old = TelegramChannel(peer_id=-1009990077, access_hash=7, title="Ancienne")
    db.add(old)
    db.commit()
    telegram_service._migrated = False
    telegram_service._accounts.clear()

    rows = telegram_service.account_rows()
    assert len(rows) == 1 and rows[0].session == "legacy-session"
    db.refresh(old)
    assert old.account_id == rows[0].id
    assert db.query(AppConfig).filter(AppConfig.key == tg_client.KEY_SESSION).first() is None

    # A second account: channels use their own account's client
    second = TelegramAccount(session="second-session", name="Second")
    db.add(second)
    db.commit()
    other = TelegramChannel(peer_id=-1009990078, access_hash=8, title="Nouvelle", account_id=second.id)
    db.add(other)
    db.commit()
    used = []

    async def fake_authorized(self):
        used.append(self.account_id)
        return SimpleNamespace(account=self.account_id)

    monkeypatch.setattr(tg_client.AccountClient, "authorized_client", fake_authorized)
    assert asyncio.run(telegram_service.client_for_channel(other)).account == second.id
    assert asyncio.run(telegram_service.client_for_channel(old)).account == rows[0].id
    assert used == [second.id, rows[0].id]

    for obj in (old, other, second):
        db.delete(obj)
    db.delete(db.get(TelegramAccount, rows[0].id))
    db.commit()
    db.close()
    telegram_service._accounts.clear()


def test_create_channel_links_it_and_sets_upload_target(monkeypatch):
    from bridge import app_settings
    from bridge.models import TelegramAccount
    init_db()
    db = SessionLocal()
    account = TelegramAccount(session="s", name="Créateur")
    db.add(account)
    db.commit()
    created = {}

    async def fake_create(account_id, title, about="", username=""):
        created.update(account_id=account_id, title=title, username=username)
        return SimpleNamespace(id=555001, access_hash=99, title=title, username="", broadcast=True), "Le nom public @pris est refusé"

    monkeypatch.setattr(telegram_service, "create_channel", fake_create)
    monkeypatch.setattr("telethon.utils.get_peer_id", lambda entity: -1000000555001)
    with TestClient(app) as client:
        _admin(client)
        r = client.post("/admin/telegram/channels/create", data={
            "title": "Stock 2", "account_id": account.id, "username": "pris", "mode": "caption", "upload_target": "1",
        }, follow_redirects=False)
        assert r.status_code == 303
    ch = db.query(TelegramChannel).filter(TelegramChannel.peer_id == -1000000555001).one()
    assert (ch.title, ch.account_id, ch.access_hash) == ("Stock 2", account.id, 99)
    assert created == {"account_id": account.id, "title": "Stock 2", "username": "pris"}
    assert app_settings.get("upload_channel_id") == str(ch.id)
    db.delete(ch)
    db.delete(account)
    db.commit()
    db.close()


def test_telegram_tab_lists_accounts(monkeypatch):
    async def fake_status():
        return {"configured": True, "authorized": True, "account": "Alice, Bob", "pending_phone": "", "needs_password": False,
                "error": "", "accounts": [
                    {"id": 1, "name": "Alice", "phone": "+1", "authorized": True, "error": "", "channels": 2},
                    {"id": 2, "name": "Bob", "phone": "+2", "authorized": True, "error": "", "channels": 0},
                ]}

    monkeypatch.setattr(telegram_service, "status", fake_status)
    with TestClient(app) as client:
        _admin(client)
        page = client.get("/admin?tab=telegram").text
    assert "Alice" in page and "Bob" in page
    assert "Ajouter un autre compte" in page
    assert "Créer une nouvelle chaîne Telegram" in page and "Créer avec : Bob" in page


def test_loadtest_page_and_start(monkeypatch):
    from bridge import loadtest
    started = {}
    monkeypatch.setattr(loadtest, "start", lambda cfg: started.update(cfg))
    init_db()
    db = SessionLocal()
    series = Series(source_id="lt-1", slug="lt-1", title="LT", status="active", source_type="upload")
    db.add(series)
    db.commit()
    db.add(Episode(series_id=series.id, num=1, local_file="x.mp4", duration=100, file_size=25_000_000))
    db.commit()
    with TestClient(app) as client:
        _admin(client)
        page = client.get("/admin/loadtest").text
        assert "test de charge" in page and "Lancer le test" in page and "Trafic sortant ce mois" in page
        r = client.post("/admin/loadtest/start", data={"custom_steps": "3, 9", "step_seconds": "30", "source": "local",
                                                       "target": "internal", "bandwidth_mbps": "1000"}, follow_redirects=False)
        assert r.status_code == 303
        assert client.get("/admin/loadtest/status").json()["state"] in ("idle", "running", "done", "stopped")
    assert started["steps"] == [3, 9] and started["bandwidth_mbps"] == 1000
    mine = [e for e in started["episodes"] if e["series_id"] == series.id]
    assert mine and mine[0]["bitrate_bps"] == 2_000_000
    data = {"config": {"bitrate_bps": 2_000_000, "bandwidth_mbps": 1000},
            "steps": [{"users": 3, "healthy": True}, {"users": 9, "healthy": False}]}
    loadtest.finalize(data)
    assert data["capacity"] == 3 and data["network_capacity"] == 400
    db.delete(series)
    db.commit()
    db.close()


def test_telegram_cache_serves_copy_without_switching_mid_playback(channel, monkeypatch, tmp_path):
    import shutil
    from bridge import optimizer
    db, ch = channel
    series = Series(source_id="cache-1", slug="cache-1", title="Cache", source_type="telegram",
                    tg_channel_id=ch.id, status="active", available_episodes=1, total_episodes=1)
    db.add(series)
    db.commit()
    original = b"O" * 5000
    db.add(Episode(series_id=series.id, num=1, tg_peer_id=ch.peer_id, tg_message_id=777, file_size=len(original), mime_type="video/mp4"))
    db.commit()

    src = tmp_path / "telegram.mp4"
    src.write_bytes(original)

    class Msg:
        file = SimpleNamespace(size=len(original), duration=60)

        async def download_media(self, file):
            shutil.copy(src, file)

    async def fake_get_message(peer_id, access_hash, message_id, refresh=False):
        return Msg()

    async def fake_iter_bytes(message, start, end):
        yield original[start:end + 1]

    async def fake_compress(a, b):
        b.write_bytes(b"C" * 1000)  # the compressed copy has different bytes
        return True

    monkeypatch.setattr(telegram_service, "get_message", fake_get_message)
    monkeypatch.setattr(telegram_service, "iter_bytes", fake_iter_bytes)
    monkeypatch.setattr(optimizer, "compress", fake_compress)
    monkeypatch.setattr(optimizer, "needs_compression", lambda size, duration: True)
    optimizer.telegram_cache.clear()

    with TestClient(app) as client:
        url = f"/stream/{series.id}/1.mp4"
        # First playback comes from Telegram and queues the episode for the cache
        r = client.get(url, headers={"Range": "bytes=0-99"})
        assert r.status_code == 206 and r.content == original[:100]
        asyncio.run(optimizer.telegram_cache._cache_one(ch.peer_id, 1, 777))
        assert optimizer.cache_path(ch.peer_id, 777).read_bytes() == b"C" * 1000
        # Same playback continues (Range not at 0): still the original bytes
        r = client.get(url, headers={"Range": "bytes=100-199"})
        assert r.content == original[100:200]
        # A new playback gets the compressed copy from disk
        r = client.get(url, headers={"Range": "bytes=0-"})
        assert r.content == b"C" * 1000
        r = client.get(url, headers={"Range": "bytes=500-599"})
        assert r.content == b"C" * 100
    assert optimizer.telegram_cache.saved_bytes >= 4000
    optimizer.telegram_cache.clear()
    db.delete(series)
    db.commit()


def test_traffic_counter_counts_video_bytes():
    from bridge import activity
    before = activity.traffic()["used"]
    activity.add_traffic(10 ** 9)
    info = activity.traffic()
    assert info["used"] - before == 10 ** 9
    assert info["quota"] == 20e12 and info["projected"] >= info["used"]
    activity.save_traffic()
    activity._traffic["month"] = ""  # reload from the database
    assert activity.traffic()["used"] - before == 10 ** 9


def test_nginx_accel_hands_local_videos_to_nginx(monkeypatch):
    from bridge import activity
    from bridge.config import settings
    from bridge.uploads import LOCAL_VIDEOS_DIR
    init_db()
    LOCAL_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    (LOCAL_VIDEOS_DIR / "accel.mp4").write_bytes(b"V" * 1000)
    (settings.MEDIA_DIR / ".accel-check").write_text("token")
    db = SessionLocal()
    series = Series(source_id="accel-1", slug="accel-1", title="Accel", status="active", source_type="upload")
    db.add(series)
    db.commit()
    db.add(Episode(series_id=series.id, num=1, local_file="accel.mp4", mime_type="video/mp4"))
    db.commit()
    with TestClient(app) as client:
        # Without nginx: Python sends the file
        r = client.get(f"/stream/{series.id}/1.mp4")
        assert r.content == b"V" * 1000 and "x-accel-redirect" not in r.headers
        monkeypatch.setenv("NGINX_ACCEL", "1")
        before = activity.traffic()["used"]
        r = client.get(f"/stream/{series.id}/1.mp4", headers={"Range": "bytes=100-299"})
        assert r.headers["x-accel-redirect"] == "/_protected/videos/local/accel.mp4"
        assert r.content == b""
        assert activity.traffic()["used"] - before == 200  # counted for nginx
        r = client.get("/health/accel")
        assert r.headers["x-accel-redirect"] == "/_protected/.accel-check"
    db.delete(series)
    db.commit()
    db.close()


def test_downloads_are_spread_between_member_accounts(monkeypatch):
    from bridge.models import TelegramAccount, TelegramChannelAccess
    from bridge.telegram import client as tg_client
    init_db()
    db = SessionLocal()
    accounts = [TelegramAccount(session=f"s{i}", name=f"Acc{i}") for i in range(3)]
    db.add_all(accounts)
    db.commit()
    ch = TelegramChannel(peer_id=-1009990555, access_hash=10, title="Partagée", account_id=accounts[0].id)
    db.add(ch)
    db.add_all([TelegramChannelAccess(peer_id=ch.peer_id, account_id=a.id, access_hash=20 + i) for i, a in enumerate(accounts[1:])])
    db.commit()
    telegram_service._accounts.clear()
    telegram_service._readers.clear()
    telegram_service._messages.clear()
    telegram_service._active.clear()

    class FakeClient:
        def __init__(self, acc):
            self.acc = acc

        async def get_messages(self, peer, ids):
            return SimpleNamespace(_client=self, acc=self.acc, peer_hash=peer.access_hash, media=None,
                                   file=SimpleNamespace(size=10))

        async def iter_download(self, media, offset, request_size, file_size):
            await asyncio.sleep(0.05)
            yield b"x" * 10

    async def fake_authorized(self):
        if getattr(self, "_client", None) is None:
            self._client = FakeClient(self.account_id)
        return self._client

    monkeypatch.setattr(tg_client.AccountClient, "authorized_client", fake_authorized)
    assert telegram_service.reader_counts()[ch.peer_id] == 3

    async def scenario():
        used = []
        streams = []
        for i in range(3):
            msg = await telegram_service.get_message(ch.peer_id, 10, 100 + i)
            used.append((msg.acc, msg.peer_hash))
            gen = telegram_service.iter_bytes(msg, 0, 9)
            await gen.__anext__()  # download in progress: this account is busy
            streams.append(gen)
        for gen in streams:
            await gen.aclose()
        return used

    used = asyncio.run(scenario())
    # Three simultaneous playbacks -> three different accounts, each with its own access hash
    assert sorted(acc for acc, _ in used) == sorted(a.id for a in accounts)
    assert dict(used)[accounts[0].id] == 10 and dict(used)[accounts[2].id] == 21
    assert telegram_service.active_downloads() == {}

    db.query(TelegramChannelAccess).filter(TelegramChannelAccess.peer_id == ch.peer_id).delete()
    db.delete(ch)
    for a in accounts:
        db.delete(a)
    db.commit()
    db.close()
    telegram_service._accounts.clear()
    telegram_service._readers.clear()
