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

    async def fake_client():
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

    async def fake_client():
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
