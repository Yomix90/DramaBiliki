import asyncio
import logging
import re
import time
import urllib.parse
from typing import Dict, Tuple, Optional
import httpx
from bridge.config import settings

logger = logging.getLogger(__name__)

class StreamCacheEntry:
    def __init__(self, content: str, content_type: str, expires_at: float, final_url: str):
        self.content = content
        self.content_type = content_type
        self.expires_at = expires_at
        self.final_url = final_url

    def is_valid(self) -> bool:
        return time.time() < (self.expires_at - 15)  # 15s safety margin


class StreamResolver:
    """
    Resolves, rewrites, and caches vertical HLS streaming playlists on-the-fly.
    Applies CDN failover (cdn2 <-> cdn), relative-to-absolute URL transformation,
    and handles both HLS (.m3u8) and direct MP4 streams.
    """

    def __init__(self):
        self._cache: Dict[str, StreamCacheEntry] = {}
        self._client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers={
                    "User-Agent": settings.SOURCE_USER_AGENT,
                    "Accept": "*/*",
                    "Referer": f"{settings.SOURCE_BASE_URL}/",
                },
                timeout=12.0,
                follow_redirects=True,
                **settings.source_client_kwargs(),
            )
            # Initialize session cookie
            try:
                await self._client.get(f"{settings.SOURCE_BASE_URL}/api/config")
            except Exception as e:
                logger.warning(f"StreamResolver failed to fetch initial session cookie: {e}")
        return self._client

    def _extract_expiration_ttl(self, url: str) -> int:
        """Extracts token expiration timestamp from signed query params (pexp, Expires)."""
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)

        now = int(time.time())
        exp_timestamp = None

        if "pexp" in params:
            try:
                exp_timestamp = int(params["pexp"][0])
            except (ValueError, IndexError):
                pass
        elif "Expires" in params:
            try:
                exp_timestamp = int(params["Expires"][0])
            except (ValueError, IndexError):
                pass
        elif "expires" in params:
            try:
                exp_timestamp = int(params["expires"][0])
            except (ValueError, IndexError):
                pass

        if exp_timestamp and exp_timestamp > now:
            remaining = exp_timestamp - now - 60  # Buffer 60s
            return max(30, min(remaining, settings.STREAM_CACHE_TTL_SECONDS))

        return settings.STREAM_CACHE_TTL_SECONDS

    def rewrite_m3u8(
        self,
        raw_m3u8: str,
        base_url: str,
        proxy_segments: bool = False,
        bridge_base_url: str = "",
    ) -> str:
        """
        Rewrites M3U8 content:
        1. Transforms relative URLs into absolute URLs using base_url.
        2. Applies CDN failover replacement (cdn2.dramaflix.net <-> cdn.dramaflix.net).
        3. Optionally proxies segment URLs through the bridge.
        """
        lines = raw_m3u8.splitlines()
        rewritten_lines = []

        for line in lines:
            trimmed = line.strip()
            if not trimmed:
                rewritten_lines.append(line)
                continue

            # Process URI lines (not comments or tags)
            if not trimmed.startswith("#"):
                abs_url = urllib.parse.urljoin(base_url, trimmed)

                # CDN Failover check: if configured, use primary CDN
                if "cdn2.dramaflix.net" in abs_url and settings.SOURCE_CDN_PRIMARY != "cdn2.dramaflix.net":
                    abs_url = abs_url.replace("cdn2.dramaflix.net", settings.SOURCE_CDN_PRIMARY)

                # Segment proxy rewrite if enabled
                if proxy_segments and (abs_url.endswith(".ts") or ".ts?" in abs_url or abs_url.endswith(".mp4") or ".mp4?" in abs_url):
                    quoted = urllib.parse.quote(abs_url, safe="")
                    rewritten_lines.append(f"{bridge_base_url}/stream/seg?u={quoted}")
                else:
                    rewritten_lines.append(abs_url)
            elif trimmed.startswith("#EXT-X-MAP:URI="):
                # Init mp4 map tag for fragmented MP4: #EXT-X-MAP:URI="1_5aa...init.mp4"
                match = re.search(r'#EXT-X-MAP:URI="([^"]+)"', trimmed)
                if match:
                    rel_uri = match.group(1)
                    abs_uri = urllib.parse.urljoin(base_url, rel_uri)
                    if proxy_segments:
                        quoted = urllib.parse.quote(abs_uri, safe="")
                        rewritten_lines.append(f'#EXT-X-MAP:URI="{bridge_base_url}/stream/seg?u={quoted}"')
                    else:
                        rewritten_lines.append(f'#EXT-X-MAP:URI="{abs_uri}"')
                else:
                    rewritten_lines.append(line)
            elif trimmed.startswith("#EXT-X-MEDIA:"):
                # Subtitles or Audio URI inside tag: URI="..."
                match = re.search(r'URI="([^"]+)"', trimmed)
                if match:
                    rel_uri = match.group(1)
                    abs_uri = urllib.parse.urljoin(base_url, rel_uri)
                    replaced = trimmed.replace(f'URI="{rel_uri}"', f'URI="{abs_uri}"')
                    rewritten_lines.append(replaced)
                else:
                    rewritten_lines.append(line)
            else:
                rewritten_lines.append(line)

        return "\n".join(rewritten_lines)

    async def get_playlist(
        self,
        series_id: str,
        ep_num: int,
        bridge_base_url: str = "",
        force_refresh: bool = False,
    ) -> Tuple[str, str, int]:
        """
        Retrieves or generates fresh M3U8 content for an episode.
        Returns (content, content_type, ttl_seconds).
        """
        cache_key = f"{series_id}:{ep_num}"
        if not force_refresh and cache_key in self._cache:
            entry = self._cache[cache_key]
            if entry.is_valid():
                logger.debug(f"Serving M3U8 for {cache_key} from short memory cache")
                ttl = int(entry.expires_at - time.time())
                return entry.content, entry.content_type, ttl

        async with self._lock:
            # Double check cache
            if not force_refresh and cache_key in self._cache and self._cache[cache_key].is_valid():
                entry = self._cache[cache_key]
                return entry.content, entry.content_type, int(entry.expires_at - time.time())

            client = await self.get_client()
            hls_entry_url = f"{settings.SOURCE_BASE_URL}/hls/{series_id}/{ep_num}/playlist.m3u8"

            logger.info(f"Resolving upstream stream for series {series_id} ep {ep_num} -> {hls_entry_url}")

            try:
                response = await client.get(hls_entry_url)
                
                # If cookie expired, retry once
                if response.status_code == 412:
                    logger.warning("Session cookie expired while resolving stream. Re-fetching cookie...")
                    await client.get(f"{settings.SOURCE_BASE_URL}/api/config")
                    response = await client.get(hls_entry_url)

                if response.status_code == 404:
                    raise FileNotFoundError(f"Episode {ep_num} of series {series_id} not found on source.")

                if response.status_code not in (200, 206, 302, 307):
                    raise RuntimeError(f"Upstream stream returned HTTP {response.status_code}")

                final_url = str(response.url)
                ttl = self._extract_expiration_ttl(final_url)

                content_type = response.headers.get("content-type", "").lower()
                body_bytes = response.content

                # Check if upstream returned direct MP4 video instead of HLS
                is_mp4 = (
                    "video/mp4" in content_type
                    or final_url.split("?")[0].endswith(".mp4")
                    or body_bytes[:4] == b"\x00\x00\x00\x18"
                    or b"ftyp" in body_bytes[:32]
                )

                if is_mp4:
                    logger.info(f"Episode {ep_num} is a direct MP4. Generating HLS wrapper.")
                    # Generate single-item HLS media playlist wrapping the MP4
                    m3u8_content = (
                        "#EXTM3U\n"
                        "#EXT-X-VERSION:3\n"
                        "#EXT-X-TARGETDURATION:600\n"
                        "#EXT-X-MEDIA-SEQUENCE:0\n"
                        "#EXTINF:180.0,\n"
                        f"{final_url}\n"
                        "#EXT-X-ENDLIST\n"
                    )
                    content_type = "application/vnd.apple.mpegurl; charset=utf-8"
                else:
                    raw_text = response.text
                    m3u8_content = self.rewrite_m3u8(
                        raw_text,
                        base_url=final_url,
                        proxy_segments=settings.PROXY_SEGMENTS,
                        bridge_base_url=bridge_base_url,
                    )
                    content_type = "application/vnd.apple.mpegurl; charset=utf-8"

                expires_at = time.time() + ttl
                self._cache[cache_key] = StreamCacheEntry(
                    content=m3u8_content,
                    content_type=content_type,
                    expires_at=expires_at,
                    final_url=final_url,
                )

                return m3u8_content, content_type, ttl

            except Exception as e:
                logger.error(f"Failed to resolve stream for {series_id}/{ep_num}: {e}")
                raise

    async def get_subtitles_vtt(self, series_id: str, ep_num: int, lang: str = "en") -> str:
        """
        Retrieves subtitles from source and converts them to standard WebVTT format.
        """
        client = await self.get_client()
        sub_url = f"{settings.SOURCE_BASE_URL}/api/subtitles/{series_id}/{ep_num}?lang={lang}"

        try:
            resp = await client.get(sub_url)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and len(data) > 0:
                    # Convert json cues to WebVTT
                    vtt_lines = ["WEBVTT", ""]
                    for idx, cue in enumerate(data, start=1):
                        start_sec = float(cue.get("start", 0))
                        end_sec = float(cue.get("end", start_sec + 2.0))
                        text = cue.get("text", "").strip()

                        start_str = self._format_vtt_timestamp(start_sec)
                        end_str = self._format_vtt_timestamp(end_sec)

                        vtt_lines.append(str(idx))
                        vtt_lines.append(f"{start_str} --> {end_str}")
                        vtt_lines.append(text)
                        vtt_lines.append("")

                    return "\n".join(vtt_lines)
                elif isinstance(data, str) and data.startswith("WEBVTT"):
                    return data
        except Exception as e:
            logger.debug(f"Subtitle fetch error for {series_id}/{ep_num}: {e}")

        # Fallback empty VTT
        return "WEBVTT\n\n"

    def _format_vtt_timestamp(self, seconds: float) -> str:
        hrs = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds - int(seconds)) * 1000)
        return f"{hrs:02d}:{mins:02d}:{secs:02d}.{millis:03d}"

    async def close(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None

stream_resolver = StreamResolver()
