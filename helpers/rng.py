"""helpers/rng.py

Deterministic per-task seed derivation for CONFIG["random_seed"] (#439).

``random_seed=None`` (default) means "unseeded": callers keep the legacy
global-RNG behaviour exactly. When set, each random consumer derives its own
seed from the base seed plus a stable label (portfolio / strategy / symbol),
so results are reproducible AND independent of which pool worker runs a task
(forked workers otherwise inherit identical global RNG state).
"""

from __future__ import annotations

import json
import zlib


def derive_seed(base_seed, *parts) -> int:
    """Return a stable 32-bit seed from *base_seed* and label *parts*.

    Uses crc32 (not ``hash()``, which is salted per process) over an unambiguous
    JSON array, so separators inside labels cannot move a component boundary.
    """
    key = json.dumps([str(base_seed), *[str(p) for p in parts]],
                     ensure_ascii=False, separators=(",", ":"))
    return zlib.crc32(key.encode("utf-8"))
