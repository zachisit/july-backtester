"""Shipped config.py safety defaults."""

from __future__ import annotations

import config


def test_shipped_price_adjustment_defaults_to_total_return() -> None:
    # Reads the already-imported module rather than reloading it. Deleting
    # config from sys.modules and re-importing swaps in a fresh module object
    # mid-session, which desyncs modules that did `from config import CONFIG`
    # and breaks later tests that patch config.CONFIG (see #220 CI failure).
    assert config.CONFIG["price_adjustment"] == "total_return"
