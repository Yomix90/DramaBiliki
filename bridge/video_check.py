"""
Detects video files that no player can open, from their first bytes.

Typical case: HLS fMP4 segments ("moof"/"mdat" boxes) concatenated into a
".ts" file without the initialization segment ("ftyp"/"moov") that carries the
codec configuration. Such files must be downloaded again with their init
segment (EXT-X-MAP) — they cannot be repaired.
"""
from typing import Optional

HEADER_BYTES = 4096

MISSING_INIT = (
    "Vidéo illisible : fragments HLS (fMP4) sans segment d'initialisation — "
    "retéléchargez l'épisode complet (avec le fichier init/EXT-X-MAP et l'audio)."
)


def check_header(head: bytes) -> Optional[str]:
    """Returns why the file cannot be played, or None when it looks playable."""
    if len(head) < 12:
        return "Fichier vide ou tronqué."
    if head[0] == 0x47 and (len(head) < 189 or head[188] == 0x47):
        return None  # MPEG-TS (sync byte every 188 bytes)
    box = head[4:8]
    if box in (b"ftyp", b"moov", b"free", b"wide", b"skip", b"mdat"):
        return None  # regular MP4 / MOV
    if box in (b"moof", b"styp", b"sidx", b"emsg"):
        return MISSING_INIT
    if head[:4] == b"\x1aE\xdf\xa3":
        return None  # Matroska / WebM
    if head[:4] == b"RIFF" or head[:3] == b"FLV":
        return None
    return None  # unknown: let the player try
