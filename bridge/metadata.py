"""
Series information files uploaded with the episodes ("info.txt" / "info.json").

Text format (one field per line, the synopsis may span several lines):

    Titre: Harem Wars - System vs. Queen
    Genres: Romance, Historique, Vengeance
    Note: 4.8
    Année: 2024
    Synopsis:
    Une jeune concubine découvre un mystérieux « système »...

JSON format: {"title": "...", "synopsis": "...", "genres": ["Romance", "Historique"]}

Field names are matched without accents or case, in French, English or Arabic.
"""
import json
import re
import unicodedata
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from bridge.models import Genre, Series

METADATA_EXTENSIONS = {".txt", ".json", ".nfo", ".md"}

# canonical field -> accepted names (normalized: lowercase, no accents, spaces collapsed)
_ALIASES: Dict[str, List[str]] = {
    "title": ["titre", "title", "nom", "name", "serie", "series", "titre en", "title en", "العنوان", "الاسم"],
    "title_fr": ["titre fr", "title fr", "titre francais", "french title"],
    "title_ar": ["titre ar", "title ar", "titre arabe", "arabic title", "العنوان بالعربية"],
    "description": ["synopsis", "description", "resume", "histoire", "story", "plot", "synopsis en", "description en", "القصة", "الوصف"],
    "description_fr": ["synopsis fr", "description fr", "resume fr", "synopsis francais"],
    "description_ar": ["synopsis ar", "description ar", "resume ar", "synopsis arabe", "القصة بالعربية"],
    "genres": ["genres", "genre", "categories", "categorie", "category", "tags", "التصنيفات", "التصنيف", "النوع"],
    "rating": ["note", "rating", "score", "التقييم"],
    "release_year": ["annee", "year", "release year", "date", "سنة", "السنة"],
    "platform": ["plateforme", "platform", "studio", "source", "chaine", "المنصة"],
    "cover_url": ["couverture", "cover", "affiche", "poster", "image", "thumbnail", "cover url", "url couverture", "الغلاف", "الصورة"],
}
_MULTILINE = {"description", "description_fr", "description_ar"}


def _normalize(key: str) -> str:
    key = unicodedata.normalize("NFKD", key).encode("ascii", "ignore").decode() or key
    key = re.sub(r"[_\-]+", " ", key.strip().lower())
    return re.sub(r"\s+", " ", key).strip(" :")


_LOOKUP = {}
for _field, _names in _ALIASES.items():
    for _name in _names:
        _LOOKUP[_normalize(_name)] = _field
        _LOOKUP[_name.strip().lower()] = _field  # Arabic names (no ASCII form)


def _field_for(key: str) -> Optional[str]:
    return _LOOKUP.get(_normalize(key)) or _LOOKUP.get(key.strip().lower())


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            text = data.decode(encoding)
            if encoding != "utf-16" or text.startswith("﻿") or "\x00" not in data[:2]:
                return text.lstrip("﻿")
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def _split_genres(value) -> List[str]:
    if isinstance(value, list):
        items = [str(v) for v in value]
    else:
        items = re.split(r"[,;/|•\n،؛]+", str(value or ""))
    out, seen = [], set()
    for item in items:
        name = item.strip().strip("#").strip()
        if name and name.casefold() not in seen:
            seen.add(name.casefold())
            out.append(name[:64])
    return out[:8]


def _clean(meta: Dict[str, object]) -> Dict[str, object]:
    out: Dict[str, object] = {}
    for field in ("title", "title_fr", "title_ar", "platform"):
        value = str(meta.get(field) or "").strip()
        if value:
            out[field] = value[:200]
    cover = str(meta.get("cover_url") or "").strip()
    if re.match(r"^https?://\S+$", cover):
        out["cover_url"] = cover[:500]
    for field in _MULTILINE:
        value = str(meta.get(field) or "").strip()
        if value:
            out[field] = value[:5000]
    genres = _split_genres(meta.get("genres"))
    if genres:
        out["genres"] = genres
    try:
        rating = float(str(meta.get("rating", "")).replace(",", ".").split("/")[0])
        if 0 <= rating <= 10:
            out["rating"] = round(rating / 2 if rating > 5 else rating, 1)  # accepts /10 ratings
    except ValueError:
        pass
    year = re.search(r"(19|20)\d{2}", str(meta.get("release_year") or ""))
    if year:
        out["release_year"] = int(year.group(0))
    return out


def _parse_json(text: str) -> Dict[str, object]:
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Le JSON doit être un objet { ... }")
    meta: Dict[str, object] = {}
    for key, value in data.items():
        if isinstance(value, dict) and _field_for(key) in ("title", "description"):
            # {"title": {"en": "...", "fr": "...", "ar": "..."}}
            base = _field_for(key)
            for lang, text_value in value.items():
                suffix = "" if lang.lower() in ("en", "default") else f"_{lang.lower()}"
                if f"{base}{suffix}" in _ALIASES:
                    meta[f"{base}{suffix}"] = text_value
            continue
        field = _field_for(key)
        if field:
            meta[field] = value
    return meta


def _parse_text(text: str) -> Dict[str, object]:
    meta: Dict[str, object] = {}
    current: Optional[str] = None
    buffer: List[str] = []

    def flush():
        if current and buffer:
            meta[current] = "\n".join(buffer).strip()

    for raw in text.splitlines():
        if raw.strip().startswith("#"):
            continue  # comment
        line = raw.strip().lstrip("-*").strip()
        match = re.match(r"^([^:：=]{1,40})\s*[:：=]\s*(.*)$", line)
        field = _field_for(match.group(1)) if match else None
        if field:
            flush()
            current, buffer = field, []
            value = match.group(2).strip()
            if value:
                buffer.append(value)
            if field not in _MULTILINE:
                flush()
                current, buffer = None, []
        elif current in _MULTILINE:
            buffer.append(raw.rstrip())
    flush()
    return meta


def parse_metadata(filename: str, data: bytes) -> Dict[str, object]:
    """Returns the recognized fields; raises ValueError when nothing usable is found."""
    if len(data) > 512 * 1024:
        raise ValueError("Fichier d'informations trop volumineux (512 Ko maximum)")
    text = _decode(data)
    stripped = text.lstrip()
    if filename.lower().endswith(".json") or stripped.startswith("{"):
        try:
            meta = _clean(_parse_json(text))
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON invalide (ligne {e.lineno}) : {e.msg}")
    else:
        meta = _clean(_parse_text(text))
    if not meta:
        raise ValueError("Aucune information reconnue (attendu : Titre:, Synopsis:, Genres:…)")
    return meta


def genres_from_names(db: Session, names: List[str]) -> List[Genre]:
    genres = []
    for name in names[:8]:
        slug = re.sub(r"[^\w]+", "-", name.lower(), flags=re.UNICODE).strip("-")[:60]
        if not slug:
            continue
        genre = db.query(Genre).filter_by(slug=slug).first()
        if genre is None:
            genre = Genre(slug=slug, name=name[:64], names_json={"en": name[:64]})
            db.add(genre)
            db.flush()
        genres.append(genre)
    return genres


def apply_metadata(db: Session, series: Series, meta: Dict[str, object]) -> None:
    """Fills the series with the information file (fields absent from the file are kept)."""
    titles = dict(series.titles_json or {})
    if meta.get("title"):
        series.title = str(meta["title"])
        titles["en"] = series.title
    for lang in ("fr", "ar"):
        if meta.get(f"title_{lang}"):
            titles[lang] = str(meta[f"title_{lang}"])
    series.titles_json = titles

    descriptions = dict(series.descriptions_json or {})
    if meta.get("description"):
        series.description = str(meta["description"])
        descriptions["en"] = series.description
    for lang in ("fr", "ar"):
        if meta.get(f"description_{lang}"):
            descriptions[lang] = str(meta[f"description_{lang}"])
    series.descriptions_json = descriptions

    if meta.get("genres"):
        series.genres = genres_from_names(db, list(meta["genres"]))
    if meta.get("rating") is not None:
        series.rating = float(meta["rating"])
    if meta.get("release_year"):
        series.release_year = int(meta["release_year"])
    if meta.get("platform"):
        series.platform = str(meta["platform"])[:64]
    if meta.get("cover_url") and not series.local_cover:
        # Fallback when the image could not be downloaded: the app loads it from its URL
        series.cover_url = str(meta["cover_url"])


MAX_COVER_DOWNLOAD = 8 * 1024 * 1024
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


async def download_cover(url: str) -> Optional[bytes]:
    """Fetches the poster given by 'Couverture:' like a browser would; None on failure."""
    import httpx
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    headers = {
        "User-Agent": _BROWSER_UA,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Referer": f"{parsed.scheme}://{parsed.hostname}/",
    }
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=headers) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code != 200 or not resp.headers.get("content-type", "").startswith("image/"):
                    return None
                data = bytearray()
                async for chunk in resp.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_COVER_DOWNLOAD:
                        return None
                return bytes(data)
    except httpx.HTTPError:
        return None
