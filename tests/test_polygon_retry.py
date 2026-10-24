# tests/test_polygon_retry.py
"""
#437: Polygon retry on 429/5xx and no caching of partial paginated data.

Retry lives in the urllib3 adapter, so mocking SESSION.get would bypass it.
These tests run a scripted HTTP server on 127.0.0.1 (no external network) and
point polygon_service._BASE_URL at it, so the real adapter retries are counted.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

import pytest

from services import polygon_service as ps

BAR = {"t": 1700000000000, "o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "v": 100}
CONFIG = {"timeframe": "D", "timeframe_multiplier": 1, "price_adjustment": "none",
          "polygon_max_retries": 5}


class _Server:
    """Replays a scripted list of (status, body_dict, headers) per request."""
    def __init__(self, script):
        self.script = list(script)
        self.paths = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.paths.append(self.path)
                status, body, headers = outer.script.pop(0) if outer.script else (200, {"status": "OK"}, {})
                raw = json.dumps(body).encode()
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *a):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def serve(monkeypatch):
    monkeypatch.setenv("POLYGON_API_KEY", "SECRETKEY")
    monkeypatch.setattr(ps, "_BACKOFF_FACTOR", 0)
    monkeypatch.setattr(ps, "_mounted_retries", None)   # force remount with patched backoff
    servers = []

    def make(script):
        srv = _Server(script)
        servers.append(srv)
        monkeypatch.setattr(ps, "_BASE_URL", srv.url)
        return srv

    with patch("services.polygon_service.get_cached_data", return_value=None), \
         patch("services.polygon_service.set_cached_data") as set_cache:
        make.set_cache = set_cache
        yield make
    for s in servers:
        s.close()
    ps._mounted_retries = None
    ps._mount_retry_adapter()


def test_429_then_200_succeeds(serve):
    srv = serve([(429, {}, {}), (200, {"status": "OK", "results": [BAR]}, {})])
    df = ps.get_price_data("AAA", "2023-01-01", "2023-12-31", CONFIG)
    assert df is not None and len(df) == 1
    assert len(srv.paths) == 2          # retry actually fired
    serve.set_cache.assert_called_once()


def test_retry_after_header_honoured(serve):
    srv = serve([(503, {}, {"Retry-After": "0"}), (200, {"status": "OK", "results": [BAR]}, {})])
    assert ps.get_price_data("AAA", "2023-01-01", "2023-12-31", CONFIG) is not None
    assert len(srv.paths) == 2


def test_persistent_429_returns_none_uncached(serve, caplog):
    srv = serve([(429, {}, {})] * 20)
    with caplog.at_level("ERROR"):
        assert ps.get_price_data("AAA", "2023-01-01", "2023-12-31", CONFIG) is None
    assert len(srv.paths) == 6          # 1 try + 5 retries
    serve.set_cache.assert_not_called()
    assert "SECRETKEY" not in caplog.text


def test_max_retries_is_configurable(serve):
    srv = serve([(500, {}, {})] * 20)
    cfg = dict(CONFIG, polygon_max_retries=2)
    assert ps.get_price_data("AAA", "2023-01-01", "2023-12-31", cfg) is None
    assert len(srv.paths) == 3


def test_zero_retries_disables_retry(serve):
    srv = serve([(429, {}, {})] * 5)
    assert ps.get_price_data("AAA", "2023-01-01", "2023-12-31", dict(CONFIG, polygon_max_retries=0)) is None
    assert len(srv.paths) == 1


def test_404_not_retried(serve):
    srv = serve([(404, {}, {})] * 5)
    assert ps.get_price_data("AAA", "2023-01-01", "2023-12-31", CONFIG) is None
    assert len(srv.paths) == 1


def test_mid_pagination_error_returns_data_but_not_cached(serve):
    srv = serve([])
    srv.script = [
        (200, {"status": "OK", "results": [BAR], "next_url": srv.url + "/page2"}, {}),
        (200, {"status": "ERROR", "error": "boom"}, {}),
    ]
    df = ps.get_price_data("AAA", "2023-01-01", "2023-12-31", CONFIG)
    assert df is not None and len(df) == 1
    serve.set_cache.assert_not_called()


def test_http_failure_mid_pagination_not_cached(serve):
    srv = serve([])
    srv.script = [(200, {"status": "OK", "results": [BAR], "next_url": srv.url + "/page2"}, {})] + [(500, {}, {})] * 10
    assert ps.get_price_data("AAA", "2023-01-01", "2023-12-31", CONFIG) is None
    serve.set_cache.assert_not_called()


def test_normal_two_page_fetch_is_cached(serve):
    srv = serve([])
    bar2 = dict(BAR, t=BAR["t"] + 86400000)
    srv.script = [
        (200, {"status": "OK", "results": [BAR], "next_url": srv.url + "/page2"}, {}),
        (200, {"status": "OK", "results": [bar2]}, {}),
    ]
    df = ps.get_price_data("AAA", "2023-01-01", "2023-12-31", CONFIG)
    assert len(df) == 2
    serve.set_cache.assert_called_once()


def test_redact_masks_api_key():
    assert "SECRET" not in ps._redact("429 for url: https://x/y?apiKey=SECRET&adjusted=true")


def test_config_key_registered():
    from helpers.config_validator import KNOWN_KEYS
    from config import CONFIG as C
    assert "polygon_max_retries" in KNOWN_KEYS and C["polygon_max_retries"] == 5
