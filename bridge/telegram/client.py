"""
Telegram account connection (Telethon / MTProto).

A *user* account is required: bots cannot read a channel's history nor
download files larger than 20 MB. The account is linked from the admin panel
(phone number → login code → optional 2FA password) and its session string is
stored in the app_config table, inside the persistent data volume.
"""
import asyncio
import logging
import time
from typing import AsyncIterator, Dict, List, Optional, Tuple

from telethon import TelegramClient, errors, utils
from telethon.sessions import StringSession
from telethon.tl.types import Channel, InputPeerChannel

from bridge.config import settings
from bridge.database import SessionLocal
from bridge.models import AppConfig

logger = logging.getLogger("bridge.telegram")

KEY_SESSION = "tg_session"
KEY_API_ID = "tg_api_id"
KEY_API_HASH = "tg_api_hash"

CHUNK_SIZE = 512 * 1024  # Telegram's maximum download request size
MESSAGE_CACHE_SECONDS = 20 * 60


def _get_config(key: str) -> str:
    db = SessionLocal()
    try:
        row = db.query(AppConfig).filter(AppConfig.key == key).first()
        return row.value if row else ""
    finally:
        db.close()


def _set_config(key: str, value: str, description: str = "") -> None:
    db = SessionLocal()
    try:
        row = db.query(AppConfig).filter(AppConfig.key == key).first()
        if not value:
            if row:
                db.delete(row)
        elif row:
            row.value = value
        else:
            db.add(AppConfig(key=key, value=value, description=description))
        db.commit()
    finally:
        db.close()


class TelegramService:
    def __init__(self):
        self._client: Optional[TelegramClient] = None
        self._lock = asyncio.Lock()
        self._pending_phone: Optional[str] = None
        self._pending_hash: Optional[str] = None
        self._needs_password = False
        self._me_name: str = ""
        self._messages: Dict[Tuple[int, int], Tuple[float, object]] = {}

    # ------------------------------------------------------------------
    # Credentials & connection
    # ------------------------------------------------------------------

    def credentials(self) -> Tuple[Optional[int], str]:
        api_id = settings.TG_API_ID or _get_config(KEY_API_ID)
        api_hash = settings.TG_API_HASH or _get_config(KEY_API_HASH)
        try:
            return (int(api_id) if api_id else None), api_hash
        except ValueError:
            return None, api_hash

    @property
    def configured(self) -> bool:
        api_id, api_hash = self.credentials()
        return bool(api_id and api_hash)

    def save_credentials(self, api_id: str, api_hash: str) -> None:
        _set_config(KEY_API_ID, api_id.strip(), "Telegram API ID")
        _set_config(KEY_API_HASH, api_hash.strip(), "Telegram API hash")

    async def client(self) -> Optional[TelegramClient]:
        """Connected client (authorized or not), or None when credentials are missing."""
        async with self._lock:
            if self._client is not None and self._client.is_connected():
                return self._client
            api_id, api_hash = self.credentials()
            if not api_id or not api_hash:
                return None
            if self._client is None:
                self._client = TelegramClient(
                    StringSession(_get_config(KEY_SESSION) or None),
                    api_id,
                    api_hash,
                    device_model="DramaBiliki Bridge",
                    app_version=settings.APP_VERSION,
                )
            await self._client.connect()
            return self._client

    async def authorized_client(self) -> Optional[TelegramClient]:
        client = await self.client()
        if client is None or not await client.is_user_authorized():
            return None
        return client

    async def reset(self) -> None:
        """Drops the client (e.g. after changing the API credentials)."""
        async with self._lock:
            if self._client is not None:
                await self._client.disconnect()
            self._client = None
            self._messages.clear()
            self._me_name = ""

    async def close(self) -> None:
        await self.reset()

    async def status(self) -> dict:
        info = {
            "configured": self.configured,
            "authorized": False,
            "account": "",
            "pending_phone": self._pending_phone or "",
            "needs_password": self._needs_password,
            "error": "",
        }
        if not info["configured"]:
            return info
        try:
            client = await self.authorized_client()
            if client is not None:
                info["authorized"] = True
                if not self._me_name:
                    me = await client.get_me()
                    self._me_name = " ".join(filter(None, [me.first_name, me.last_name])) or (me.username or "")
                    if me.username:
                        self._me_name += f" (@{me.username})"
                info["account"] = self._me_name
        except Exception as e:  # network errors must not break the dashboard
            info["error"] = str(e)
        return info

    # ------------------------------------------------------------------
    # Login flow
    # ------------------------------------------------------------------

    async def send_code(self, phone: str) -> None:
        client = await self.client()
        if client is None:
            raise RuntimeError("API ID / API hash manquants.")
        sent = await client.send_code_request(phone)
        self._pending_phone = phone
        self._pending_hash = sent.phone_code_hash
        self._needs_password = False

    async def sign_in(self, code: str = "", password: str = "") -> None:
        client = await self.client()
        if client is None:
            raise RuntimeError("API ID / API hash manquants.")
        try:
            if self._needs_password:
                await client.sign_in(password=password)
            else:
                if not self._pending_phone:
                    raise RuntimeError("Demandez d'abord un code de connexion.")
                try:
                    await client.sign_in(phone=self._pending_phone, code=code.strip(), phone_code_hash=self._pending_hash)
                except errors.SessionPasswordNeededError:
                    self._needs_password = True
                    if not password:
                        raise
                    await client.sign_in(password=password)
        except errors.SessionPasswordNeededError:
            raise
        _set_config(KEY_SESSION, client.session.save(), "Telegram account session (keep secret)")
        self._pending_phone = self._pending_hash = None
        self._needs_password = False
        self._me_name = ""

    async def log_out(self) -> None:
        client = await self.client()
        if client is not None:
            try:
                await client.log_out()
            except Exception:
                pass
        _set_config(KEY_SESSION, "")
        self._pending_phone = self._pending_hash = None
        self._needs_password = False
        await self.reset()

    # ------------------------------------------------------------------
    # Channels & messages
    # ------------------------------------------------------------------

    async def list_channels(self) -> List[dict]:
        """Broadcast channels and groups the account belongs to."""
        client = await self.authorized_client()
        if client is None:
            return []
        out = []
        async for dialog in client.iter_dialogs():
            entity = dialog.entity
            if isinstance(entity, Channel):
                out.append({
                    "peer_id": utils.get_peer_id(entity),
                    "title": entity.title,
                    "username": entity.username or "",
                    "broadcast": bool(entity.broadcast),
                })
        return out

    async def resolve_channel(self, ref: str) -> Channel:
        """Accepts a peer id from the dialog list, @username or a t.me link."""
        client = await self.authorized_client()
        if client is None:
            raise RuntimeError("Compte Telegram non connecté.")
        ref = ref.strip()
        if ref.lstrip("-").isdigit():
            peer_id = int(ref)
            async for dialog in client.iter_dialogs():
                if isinstance(dialog.entity, Channel) and utils.get_peer_id(dialog.entity) == peer_id:
                    return dialog.entity
            raise RuntimeError("Chaîne introuvable dans les discussions du compte.")
        ref = ref.replace("https://", "").replace("http://", "").replace("t.me/", "").lstrip("@").strip("/")
        entity = await client.get_entity(ref)
        if not isinstance(entity, Channel):
            raise RuntimeError("Ce lien ne correspond pas à une chaîne.")
        return entity

    @staticmethod
    def input_peer(peer_id: int, access_hash: Optional[int]) -> InputPeerChannel:
        real_id, _ = utils.resolve_id(peer_id)
        return InputPeerChannel(channel_id=real_id, access_hash=access_hash or 0)

    async def get_message(self, peer_id: int, access_hash: Optional[int], message_id: int, refresh: bool = False):
        key = (peer_id, message_id)
        cached = self._messages.get(key)
        if cached and not refresh and time.time() - cached[0] < MESSAGE_CACHE_SECONDS:
            return cached[1]
        client = await self.authorized_client()
        if client is None:
            raise RuntimeError("Compte Telegram non connecté.")
        message = await client.get_messages(self.input_peer(peer_id, access_hash), ids=message_id)
        if message is None or message.file is None:
            raise FileNotFoundError("Vidéo supprimée de la chaîne.")
        self._messages[key] = (time.time(), message)
        return message

    async def iter_bytes(self, message, start: int, end: int) -> AsyncIterator[bytes]:
        """Yields bytes [start, end] (inclusive) of the message's file."""
        client = await self.authorized_client()
        if client is None:
            return
        aligned = start - (start % CHUNK_SIZE)
        skip = start - aligned
        remaining = end - start + 1
        async for chunk in client.iter_download(
            message.media,
            offset=aligned,
            request_size=CHUNK_SIZE,
            file_size=message.file.size,
        ):
            if skip:
                chunk = chunk[skip:]
                skip = 0
            if len(chunk) > remaining:
                chunk = chunk[:remaining]
            if chunk:
                yield bytes(chunk)
                remaining -= len(chunk)
            if remaining <= 0:
                break


telegram_service = TelegramService()
