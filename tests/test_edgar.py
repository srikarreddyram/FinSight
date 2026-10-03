import httpx
import pytest

from ingest.fetch_edgar import Edgar


class _Http:
    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), 0

    def get(self, url):
        self.calls += 1
        x = self.outcomes.pop(0)
        if isinstance(x, Exception):
            raise x
        return httpx.Response(x, request=httpx.Request("GET", url))


def _edgar(monkeypatch, *outcomes):
    monkeypatch.setattr(Edgar, "RETRY_WAITS", (0, 0, 0))
    e = Edgar("FinSight test")
    e.http = _Http(*outcomes)
    return e


def test_transient_failures_are_retried(monkeypatch):
    e = _edgar(monkeypatch, httpx.ConnectError("dropped"), 503, 429, 200)
    assert e.get("https://example.test/a").status_code == 200 and e.http.calls == 4


def test_a_missing_file_is_not_retried_and_a_dead_server_gives_up(monkeypatch):
    e = _edgar(monkeypatch, 404)
    with pytest.raises(httpx.HTTPStatusError):
        e.get("https://example.test/a")
    assert e.http.calls == 1
    e = _edgar(monkeypatch, 500, 500, 500, 500)
    with pytest.raises(httpx.HTTPStatusError):
        e.get("https://example.test/a")
    assert e.http.calls == 4
