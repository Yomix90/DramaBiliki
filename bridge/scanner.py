import asyncio
import logging
import random
import time
from typing import Dict, Any, List, Optional
import httpx
from bridge.config import settings
from bridge.source_session import apply_session

logger = logging.getLogger(__name__)

class SourceScanner:
    """
    Polite and resilient scanner for dramadunyam.com.
    Manages session cookies (dd_bilet), concurrency semaphore (max 2),
    exponential backoff retries, and multilingual metadata extraction.
    """

    def __init__(self):
        self.base_url = settings.SOURCE_BASE_URL.rstrip("/")
        self.semaphore = asyncio.Semaphore(settings.SCANNER_MAX_CONCURRENT_REQUESTS)
        self.client: Optional[httpx.AsyncClient] = None
        self._cookie_timestamp: float = 0
        self._languages = ["en", "tr", "fr", "ar", "es", "de", "pt"]

    async def get_client(self) -> httpx.AsyncClient:
        """Retrieves or initializes the persistent httpx client with fresh cookies."""
        now = time.time()
        # Refresh client/session every 6 hours
        if self.client is None or (now - self._cookie_timestamp > 21600):
            if self.client is not None:
                await self.client.aclose()

            self.client = httpx.AsyncClient(
                headers={
                    "User-Agent": settings.SOURCE_USER_AGENT,
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "en-US,en;q=0.9,fr;q=0.8,ar;q=0.7",
                    "Referer": f"{self.base_url}/",
                },
                timeout=settings.SCANNER_TIMEOUT_SECONDS,
                follow_redirects=True,
                **settings.source_client_kwargs(),
            )
            apply_session(self.client)

            # Initialize dd_bilet cookie by requesting /api/config
            try:
                resp = await self.client.get(f"{self.base_url}/api/config")
                self._cookie_timestamp = now
                logger.info("Scanner session initialized with fresh dd_bilet cookie.")
            except Exception as e:
                logger.warning(f"Failed to initialize dd_bilet cookie via /api/config: {e}")

        return self.client

    async def _polite_request(self, url: str, params: Optional[Dict[str, Any]] = None) -> Optional[httpx.Response]:
        """Performs an HTTP GET request with semaphore concurrency, random jitter, and retries."""
        async with self.semaphore:
            # Jitter delay
            delay = random.uniform(settings.SCANNER_REQUEST_DELAY_MIN, settings.SCANNER_REQUEST_DELAY_MAX)
            await asyncio.sleep(delay)

            client = await self.get_client()
            retries = settings.SCANNER_MAX_RETRIES
            backoff = 1.0

            for attempt in range(1, retries + 1):
                try:
                    response = await client.get(url, params=params)
                    
                    # If cookie expired (412 Precondition Failed), re-authenticate once
                    if response.status_code == 412:
                        logger.warning("Received HTTP 412 (dd_bilet expired). Re-authenticating...")
                        await client.get(f"{self.base_url}/api/config")
                        response = await client.get(url, params=params)

                    if response.status_code == 200:
                        return response
                    elif response.status_code == 403:
                        logger.warning(
                            f"HTTP 403 for {url}: the source (Cloudflare) is blocking this server's IP. "
                            "Set SOURCE_PROXY to route source requests through another IP."
                        )
                        return None
                    elif response.status_code == 404:
                        logger.debug(f"Source returned 404 for {url}")
                        return None
                    else:
                        logger.warning(f"HTTP {response.status_code} for {url} (attempt {attempt}/{retries})")

                except (httpx.RequestError, httpx.TimeoutException) as exc:
                    logger.warning(f"Request error for {url} (attempt {attempt}/{retries}): {exc}")

                if attempt < retries:
                    await asyncio.sleep(backoff)
                    backoff *= 2.0

            logger.error(f"Failed to fetch {url} after {retries} attempts.")
            return None

    async def fetch_catalog_page(self, page: int = 1, limit: int = 48, lang: str = "en") -> Optional[Dict[str, Any]]:
        """Fetches a single paginated page of series from the catalog API."""
        url = f"{self.base_url}/api/series"
        params = {
            "type": "tumu",
            "page": page,
            "limit": limit,
            "lang": lang,
        }
        resp = await self._polite_request(url, params=params)
        if resp and resp.status_code == 200:
            try:
                return resp.json()
            except Exception as e:
                logger.error(f"JSON decode error for catalog page {page}: {e}")
        return None

    async def fetch_series_detail(self, slug: str, lang: str = "en") -> Optional[Dict[str, Any]]:
        """Fetches metadata for a single series in a given language."""
        url = f"{self.base_url}/api/series/{slug}"
        resp = await self._polite_request(url, params={"lang": lang})
        if resp and resp.status_code == 200:
            try:
                return resp.json()
            except Exception as e:
                logger.error(f"JSON decode error for series {slug}: {e}")
        return None

    async def fetch_series_multilingual(self, slug: str) -> Dict[str, Any]:
        """
        Fetches series metadata across supported languages (en, tr, fr, ar, es, de).
        Returns aggregated data with multilingual titles and descriptions.
        """
        primary_data = await self.fetch_series_detail(slug, lang="en")
        if not primary_data:
            # Fallback to default
            primary_data = await self.fetch_series_detail(slug, lang="tr")
        if not primary_data:
            return {}

        titles: Dict[str, str] = {}
        descriptions: Dict[str, str] = {}

        if primary_data.get("title"):
            titles["en"] = primary_data.get("title", "")
        if primary_data.get("description"):
            descriptions["en"] = primary_data.get("description", "")

        # Fetch other key languages (fr, ar, tr) concurrently
        other_langs = ["fr", "ar", "tr"]
        for l in other_langs:
            try:
                l_data = await self.fetch_series_detail(slug, lang=l)
                if l_data:
                    if l_data.get("title"):
                        titles[l] = l_data.get("title")
                    if l_data.get("description"):
                        descriptions[l] = l_data.get("description")
            except Exception as e:
                logger.debug(f"Could not fetch lang {l} for {slug}: {e}")

        primary_data["multilingual_titles"] = titles
        primary_data["multilingual_descriptions"] = descriptions
        return primary_data

    async def close(self):
        """Closes the underlying HTTP client session."""
        if self.client is not None:
            await self.client.aclose()
            self.client = None
