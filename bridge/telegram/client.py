"""
Telegram accounts (Telethon / MTProto).

*User* accounts are required: bots cannot read a channel's history nor
download files larger than 20 MB. Accounts are linked from the admin panel
(phone number → login code → optional 2FA password); several can be connected.
Each session string is stored in the telegram_accounts table, inside the
persistent data volume.

A channel's access hash is only valid for the account that resolved it, so
every linked channel remembers its account (TelegramChannel.account_id).
"""
import asyncio
import logging
import time
from typing import AsyncIterator, Dict, List, Optional, Tuple

from telethon import TelegramClient, errors, functions, utils
from telethon.sessions import StringSession
from telethon.tl.types import Channel, InputPeerChannel

from bridge.config import settings
from bridge.database import SessionLocal
from bridge.models import AppConfig, TelegramAccount, TelegramChannel

logger = logging.getLogger("bridge.telegram")

KEY_SESSION = "tg_session"  # legacy single-account session, migrated to telegram_accounts
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


def _display_name(me) -> str:
    name = " ".join(filter(None, [me.first_name, me.last_name])) or (me.username or "")
    if me.username:
        name += f" (@{me.username})"
    return name


class AccountClient:
    """One Telegram account: connection, login flow and channel helpers."""

    def __init__(self, service: "TelegramService", account_id: Optional[int], session: str = "", name: str = ""):
        self.service = service
        self.account_id = account_id
        self.name = name
        self._session = session
        self._client: Optional[TelegramClient] = None
        self._lock = asyncio.Lock()
        self.pending_phone: Optional[str] = None
        self._pending_hash: Optional[str] = None
        self.needs_password = False

    async def client(self) -> Optional[TelegramClient]:
        """Connected client (authorized or not), or None when the API credentials are missing."""
        async with self._lock:
            if self._client is not None and self._client.is_connected():
                return self._client
            api_id, api_hash = self.service.credentials()
            if not api_id or not api_hash:
                return None
            if self._client is None:
                self._client = TelegramClient(
                    StringSession(self._session or None),
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

    async def disconnect(self) -> None:
        async with self._lock:
            if self._client is not None:
                await self._client.disconnect()
            self._client = None

    async def info(self) -> dict:
        info = {"id": self.account_id, "name": self.name, "authorized": False, "error": ""}
        try:
            client = await self.authorized_client()
            if client is not None:
                info["authorized"] = True
                if not self.name:
                    self.name = _display_name(await client.get_me())
                    self.service._save_account(self.account_id, name=self.name)
                info["name"] = self.name
        except Exception as e:  # network errors must not break the dashboard
            info["error"] = str(e)
        return info

    # -- login --------------------------------------------------------

    async def send_code(self, phone: str) -> None:
        client = await self.client()
        if client is None:
            raise RuntimeError("API ID / API hash manquants.")
        sent = await client.send_code_request(phone)
        self.pending_phone = phone
        self._pending_hash = sent.phone_code_hash
        self.needs_password = False

    async def sign_in(self, code: str = "", password: str = "") -> None:
        client = await self.client()
        if client is None:
            raise RuntimeError("API ID / API hash manquants.")
        if self.needs_password:
            await client.sign_in(password=password)
        else:
            if not self.pending_phone:
                raise RuntimeError("Demandez d'abord un code de connexion.")
            try:
                await client.sign_in(phone=self.pending_phone, code=code.strip(), phone_code_hash=self._pending_hash)
            except errors.SessionPasswordNeededError:
                self.needs_password = True
                if not password:
                    raise
                await client.sign_in(password=password)
        me = await client.get_me()
        self.name = _display_name(me)
        self._session = client.session.save()
        self.account_id = self.service._save_account(
            self.account_id, session=self._session, name=self.name, phone=self.pending_phone or ""
        )
        self.pending_phone = self._pending_hash = None
        self.needs_password = False

    async def log_out(self) -> None:
        client = await self.client()
        if client is not None:
            try:
                await client.log_out()
            except Exception:
                pass
        await self.disconnect()

    # -- channels -----------------------------------------------------

    async def _require(self) -> TelegramClient:
        client = await self.authorized_client()
        if client is None:
            raise RuntimeError(f"Compte Telegram « {self.name or self.account_id} » non connecté.")
        return client

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
                    "admin": bool(entity.creator or entity.admin_rights),
                    "account_id": self.account_id,
                    "account": self.name,
                })
        return out

    async def resolve_channel(self, ref: str) -> Channel:
        """Accepts a peer id from the dialog list, @username or a t.me link."""
        client = await self._require()
        ref = ref.strip()
        if ref.lstrip("-").isdigit():
            peer_id = int(ref)
            async for dialog in client.iter_dialogs():
                if isinstance(dialog.entity, Channel) and utils.get_peer_id(dialog.entity) == peer_id:
                    return dialog.entity
            raise RuntimeError("Chaîne introuvable dans les discussions de ce compte.")
        ref = ref.replace("https://", "").replace("http://", "").replace("t.me/", "").lstrip("@").strip("/")
        entity = await client.get_entity(ref)
        if not isinstance(entity, Channel):
            raise RuntimeError("Ce lien ne correspond pas à une chaîne.")
        return entity

    async def create_channel(self, title: str, about: str = "", username: str = "") -> Tuple[Channel, str]:
        """Creates a broadcast channel owned by this account (optionally public with @username).
        Returns (channel, warning): the channel stays private when the username is refused."""
        client = await self._require()
        result = await client(functions.channels.CreateChannelRequest(title=title, about=about, broadcast=True))
        channel = next(c for c in result.chats if isinstance(c, Channel))
        username = username.strip().lstrip("@")
        if username:
            try:
                await client(functions.channels.UpdateUsernameRequest(channel=channel, username=username))
                channel.username = username
            except Exception as e:
                logger.warning(f"Channel created but @{username} refused: {e}")
                return channel, f"Le nom public @{username} est refusé ({type(e).__name__}) : la chaîne reste privée."
        return channel, ""


class TelegramService:
    """All connected accounts. Most calls pick the account from the channel."""

    def __init__(self):
        self._accounts: Dict[int, AccountClient] = {}
        self._pending: Optional[AccountClient] = None  # account being linked
        self._messages: Dict[Tuple[int, int], Tuple[float, object]] = {}
        self._migrated = False

    # -- API credentials (shared by every account) ----------------------

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

    # -- accounts --------------------------------------------------------

    def _migrate_legacy(self) -> None:
        """Moves the old single-account session into telegram_accounts (once)."""
        if self._migrated:
            return
        self._migrated = True
        legacy = _get_config(KEY_SESSION)
        if not legacy:
            return
        db = SessionLocal()
        try:
            if db.query(TelegramAccount).count() == 0:
                account = TelegramAccount(session=legacy)
                db.add(account)
                db.flush()
                db.query(TelegramChannel).filter(TelegramChannel.account_id.is_(None)).update(
                    {TelegramChannel.account_id: account.id}, synchronize_session=False
                )
                db.commit()
        finally:
            db.close()
        _set_config(KEY_SESSION, "")

    def _save_account(self, account_id: Optional[int], **fields) -> int:
        db = SessionLocal()
        try:
            account = db.get(TelegramAccount, account_id) if account_id else None
            if account is None and fields.get("phone"):
                # Same phone logged in again: refresh its row instead of duplicating it
                account = db.query(TelegramAccount).filter(TelegramAccount.phone == fields["phone"]).first()
            if account is None:
                account = TelegramAccount()
                db.add(account)
            for key, value in fields.items():
                setattr(account, key, value)
            db.commit()
            return account.id
        finally:
            db.close()

    def account_rows(self) -> List[TelegramAccount]:
        self._migrate_legacy()
        db = SessionLocal()
        try:
            rows = db.query(TelegramAccount).order_by(TelegramAccount.id).all()
            db.expunge_all()
            return rows
        finally:
            db.close()

    def account(self, account_id: Optional[int]) -> Optional[AccountClient]:
        """Account by id; None → the first linked account."""
        rows = self.account_rows()
        if account_id is None:
            row = rows[0] if rows else None
        else:
            row = next((r for r in rows if r.id == account_id), None)
        if row is None:
            return None
        if row.id not in self._accounts:
            self._accounts[row.id] = AccountClient(self, row.id, row.session or "", row.name or "")
        return self._accounts[row.id]

    def _account_for_peer(self, peer_id: int) -> Optional[int]:
        db = SessionLocal()
        try:
            channel = db.query(TelegramChannel).filter(TelegramChannel.peer_id == peer_id).first()
            return channel.account_id if channel else None
        finally:
            db.close()

    async def authorized_client(self, account_id: Optional[int] = None) -> Optional[TelegramClient]:
        account = self.account(account_id)
        if account is None and account_id is not None:
            account = self.account(None)  # account removed: fall back to the first one
        return await account.authorized_client() if account else None

    async def client_for_channel(self, channel: TelegramChannel) -> Optional[TelegramClient]:
        return await self.authorized_client(channel.account_id)

    async def status(self) -> dict:
        info = {
            "configured": self.configured,
            "authorized": False,
            "account": "",
            "accounts": [],
            "pending_phone": self._pending.pending_phone if self._pending else "",
            "needs_password": bool(self._pending and self._pending.needs_password),
            "error": "",
        }
        if not info["configured"]:
            return info
        for row in self.account_rows():
            acc = await self.account(row.id).info()
            acc["phone"] = row.phone or ""
            acc["channels"] = 0
            info["accounts"].append(acc)
            if acc["error"] and not info["error"]:
                info["error"] = acc["error"]
        db = SessionLocal()
        try:
            for acc in info["accounts"]:
                acc["channels"] = db.query(TelegramChannel).filter(TelegramChannel.account_id == acc["id"]).count()
        finally:
            db.close()
        names = [a["name"] for a in info["accounts"] if a["authorized"]]
        info["authorized"] = bool(names)
        info["account"] = ", ".join(names)
        return info

    # -- login of a new account -----------------------------------------

    async def send_code(self, phone: str) -> None:
        if self._pending is None or self._pending.pending_phone != phone:
            if self._pending is not None:
                await self._pending.disconnect()
            self._pending = AccountClient(self, None)
        await self._pending.send_code(phone)

    async def sign_in(self, code: str = "", password: str = "") -> int:
        if self._pending is None:
            raise RuntimeError("Demandez d'abord un code de connexion.")
        await self._pending.sign_in(code=code, password=password)
        account = self._pending
        self._pending = None
        old = self._accounts.pop(account.account_id, None)
        if old is not None and old is not account:
            await old.disconnect()
        self._accounts[account.account_id] = account
        self._migrate_legacy()
        return account.account_id

    async def cancel_login(self) -> None:
        if self._pending is not None:
            await self._pending.disconnect()
        self._pending = None

    async def log_out(self, account_id: int) -> None:
        """Logs the account out and forgets it (its channels must be moved to another account)."""
        account = self.account(account_id)
        if account is not None:
            await account.log_out()
        self._accounts.pop(account_id, None)
        db = SessionLocal()
        try:
            row = db.get(TelegramAccount, account_id)
            if row:
                db.delete(row)
            db.commit()
        finally:
            db.close()
        self._messages.clear()

    # -- channels & messages ---------------------------------------------

    async def list_channels(self) -> List[dict]:
        """Channels of every connected account (the first account seeing a channel wins)."""
        out, seen = [], set()
        for row in self.account_rows():
            for c in await self.account(row.id).list_channels():
                if c["peer_id"] not in seen:
                    seen.add(c["peer_id"])
                    out.append(c)
        return out

    async def resolve_channel(self, ref: str, account_id: Optional[int] = None) -> Tuple[Channel, int]:
        """Resolves a channel with the given account, or tries every account. Returns (entity, account id)."""
        rows = self.account_rows()
        candidates = [r.id for r in rows if account_id is None or r.id == account_id]
        if not candidates:
            raise RuntimeError("Aucun compte Telegram connecté.")
        last_error: Optional[Exception] = None
        for acc_id in candidates:
            try:
                return await self.account(acc_id).resolve_channel(ref), acc_id
            except Exception as e:
                last_error = e
        raise last_error  # type: ignore[misc]

    async def create_channel(self, account_id: int, title: str, about: str = "", username: str = "") -> Tuple[Channel, str]:
        account = self.account(account_id)
        if account is None:
            raise RuntimeError("Compte Telegram introuvable.")
        return await account.create_channel(title, about, username)

    @staticmethod
    def input_peer(peer_id: int, access_hash: Optional[int]) -> InputPeerChannel:
        real_id, _ = utils.resolve_id(peer_id)
        return InputPeerChannel(channel_id=real_id, access_hash=access_hash or 0)

    async def get_message(self, peer_id: int, access_hash: Optional[int], message_id: int, refresh: bool = False):
        key = (peer_id, message_id)
        cached = self._messages.get(key)
        if cached and not refresh and time.time() - cached[0] < MESSAGE_CACHE_SECONDS:
            return cached[1]
        client = await self.authorized_client(self._account_for_peer(peer_id))
        if client is None:
            raise RuntimeError("Compte Telegram non connecté.")
        message = await client.get_messages(self.input_peer(peer_id, access_hash), ids=message_id)
        if message is None or message.file is None:
            raise FileNotFoundError("Vidéo supprimée de la chaîne.")
        self._messages[key] = (time.time(), message)
        return message

    async def delete_messages(self, peer_id: int, access_hash: Optional[int], message_ids: List[int]) -> Tuple[int, str]:
        """Deletes messages from a channel (the account must be admin). Returns (count, error)."""
        client = await self.authorized_client(self._account_for_peer(peer_id))
        if client is None:
            return 0, "Compte Telegram non connecté"
        deleted, error = 0, ""
        peer = self.input_peer(peer_id, access_hash)
        for i in range(0, len(message_ids), 100):
            batch = [int(m) for m in message_ids[i:i + 100]]
            try:
                result = await client.delete_messages(peer, batch, revoke=True)
                deleted += sum(getattr(r, "pts_count", 0) or 0 for r in result) or len(batch)
            except errors.ChatAdminRequiredError:
                return deleted, "Le compte n'est pas administrateur de la chaîne : suppression impossible sur Telegram"
            except errors.MessageDeleteForbiddenError:
                return deleted, "Telegram refuse la suppression de ces messages"
            except Exception as e:  # network, flood wait...
                error = f"{type(e).__name__}: {e}"
                break
            for mid in batch:
                self._messages.pop((peer_id, mid), None)
        return deleted, error

    async def iter_bytes(self, message, start: int, end: int) -> AsyncIterator[bytes]:
        """Yields bytes [start, end] (inclusive) of the message's file."""
        # A message keeps the client (account) that fetched it
        client = getattr(message, "_client", None) or await self.authorized_client()
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

    async def reset(self) -> None:
        """Drops every client (e.g. after changing the API credentials)."""
        for account in list(self._accounts.values()):
            await account.disconnect()
        self._accounts.clear()
        await self.cancel_login()
        self._messages.clear()

    async def close(self) -> None:
        await self.reset()


telegram_service = TelegramService()
