# Final Approval Report — Unified Norgate + Polygon Dataset
_Generated 2026-06-05 23:32 · anchor 2026-04-22 · Option A (total-return)._

## Universe
- Common to both feeds: **11,853**
- Norgate delisted eq/ETF kept: **22,402**
- Norgate-only review (no patch): **698**
- Norgate-only excluded (non-tradeable): **1,615**
- Polygon-only new listings added: **356**
- Polygon-only coverage gaps excluded: **95**
- Polygon-only excluded (non-tradeable): **457**

## Merge & patch
- Symbols materialized in merged/: **35,310**
- Patched dates (Polygon window): **31**
- Symbols receiving a Polygon patch: **11,853**
- Failed/flagged symbols: **1,167**

## Audit
- Per-row violations in patch + merge integrity (blocking): **0**
- Norgate-history OHLC anomalies (informational, pre-existing master): **784**
- Completeness-gate failed days: **0**
- Extreme seam cliffs (>50%, unexplained): **7**
- Delisted-during-patch (clean ends): **225**
- Insufficient-history new listings: **365**

## Verdict: ✅ APPROVED for backtesting & forward testing