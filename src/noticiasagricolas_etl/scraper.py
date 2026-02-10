"""HTTP fetcher with rate limiting, retries, and caching."""

import hashlib
import logging
import time
from datetime import date
from pathlib import Path
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import (
    BASE_URL,
    CACHE_DIR,
    MAX_RETRIES,
    REQUEST_DELAY_SECONDS,
    REQUEST_TIMEOUT,
    RETRY_BACKOFF_FACTOR,
    USER_AGENT,
)

logger = logging.getLogger(__name__)


class Scraper:
    def __init__(
        self,
        delay: float = REQUEST_DELAY_SECONDS,
        use_cache: bool = True,
        cache_dir: Optional[Path] = None,
    ):
        self.delay = delay
        self.use_cache = use_cache
        self.cache_dir = cache_dir or CACHE_DIR
        self._last_request_time: float = 0

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

        retry = Retry(
            total=MAX_RETRIES,
            backoff_factor=RETRY_BACKOFF_FACTOR,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _rate_limit(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)

    def _cache_path(self, url: str) -> Path:
        h = hashlib.md5(url.encode()).hexdigest()
        return self.cache_dir / f"{h}.html"

    def fetch(self, url: str) -> Optional[str]:
        """Fetch URL content, using cache if available."""
        if self.use_cache:
            cp = self._cache_path(url)
            if cp.exists():
                logger.debug(f"Cache hit: {url}")
                return cp.read_text(encoding="utf-8")

        self._rate_limit()
        logger.info(f"Fetching: {url}")

        try:
            resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
            self._last_request_time = time.time()

            if resp.status_code == 404:
                logger.warning(f"404: {url}")
                return None
            resp.raise_for_status()

            html = resp.text
            if self.use_cache:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                self._cache_path(url).write_text(html, encoding="utf-8")

            return html
        except requests.RequestException as e:
            logger.error(f"Request failed for {url}: {e}")
            return None

    def fetch_page(self, slug: str, target_date: Optional[date] = None) -> Optional[str]:
        """Fetch a cotacoes page, optionally for a specific date."""
        # The slug already contains the commodity prefix path
        # e.g. slug="soja/soja-indicador-cepea-esalq-porto-paranagua"
        # But in catalog, slug is just the page part, commodity is separate
        # URL: /cotacoes/{commodity}/{slug}
        # This will be called with full path from pipeline
        if target_date:
            url = f"{BASE_URL}/cotacoes/{slug}/{target_date.strftime('%Y-%m-%d')}"
        else:
            url = f"{BASE_URL}/cotacoes/{slug}"
        return self.fetch(url)

    def fetch_commodity_page(
        self, commodity: str, slug: str, target_date: Optional[date] = None
    ) -> Optional[str]:
        """Fetch a specific commodity indicator page."""
        if target_date:
            url = f"{BASE_URL}/cotacoes/{commodity}/{slug}/{target_date.strftime('%Y-%m-%d')}"
        else:
            url = f"{BASE_URL}/cotacoes/{commodity}/{slug}"
        return self.fetch(url)
