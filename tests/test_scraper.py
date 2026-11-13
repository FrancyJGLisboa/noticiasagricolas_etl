from __future__ import annotations

import requests
import pytest

from noticiasagricolas_etl.scraper import FetchError, Scraper


def _response(status: int, url: str = "https://example.test/quotes") -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.url = url
    response._content = b"response body"
    return response


def test_fetch_raises_fetch_error_for_http_403(monkeypatch) -> None:
    scraper = Scraper(delay=0, use_cache=False)
    monkeypatch.setattr(scraper.session, "get", lambda *args, **kwargs: _response(403))

    with pytest.raises(FetchError, match="HTTP 403"):
        scraper.fetch("https://example.test/quotes")


def test_fetch_returns_none_for_http_404(monkeypatch) -> None:
    scraper = Scraper(delay=0, use_cache=False)
    monkeypatch.setattr(scraper.session, "get", lambda *args, **kwargs: _response(404))

    assert scraper.fetch("https://example.test/quotes") is None


def test_fetch_raises_fetch_error_for_network_failure(monkeypatch) -> None:
    scraper = Scraper(delay=0, use_cache=False)

    def fail(*args, **kwargs):
        raise requests.ConnectionError("network unavailable")

    monkeypatch.setattr(scraper.session, "get", fail)

    with pytest.raises(FetchError, match="network unavailable"):
        scraper.fetch("https://example.test/quotes")
