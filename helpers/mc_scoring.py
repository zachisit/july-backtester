# helpers/mc_scoring.py
"""Monte Carlo scoring v2 (issue #429).

Replaces the scoring in ``helpers/monte_carlo.py::analyze_mc_results`` (kept
unchanged for comparison; its output is stored as ``mc_score_legacy``).

Why v2: the legacy performance test ("historical P&L >= 5th percentile of the
bootstrap") passes ~95% of the time for ANY strategy, because the bootstrap is
centred on the historical sum. And the legacy drawdown test compared the
daily mark-to-market drawdown against a closed-trade drawdown distribution.

Score range and verdict vocabulary are unchanged (-4..+5; "Robust" when no
flags), so summary sorting/filtering and the "DD Understated" caveat keep
working.
"""
import numpy as np

from helpers.monte_carlo import _equity_and_drawdown

EDGE_P_THRESHOLD = 0.05
_MIN_BOOT = 1000


def bootstrap_mean_pvalue(trade_pnl_list, n_boot=_MIN_BOOT, rng=None,
                          sampling="iid", block_size=None):
    """One-sided bootstrap p-value for H0: mean trade P&L <= 0.

    Resamples the DEMEANED trade P&L (null distribution with mean 0) and
    returns P(resampled mean >= observed mean), with +1 smoothing so p > 0.
    Chosen over "share of paths below initial capital" because it is a proper
    significance test with a fixed, interpretable threshold (p < 0.05).
    ``sampling="block"`` uses circular blocks, matching the MC resampler and
    preserving serial dependence in the edge test as well as the risk tests.
    """
    pnl = np.asarray(trade_pnl_list, dtype=float)
    n = len(pnl)
    if n < 2:
        return 1.0
    gen = rng if rng is not None else np.random
    centered = pnl - pnl.mean()
    draw = gen.integers if hasattr(gen, "integers") else gen.randint
    # Chunked so the index matrix stays ~<=2M entries per draw: an intraday run
    # with 50k trades would otherwise allocate n_boot x n ints (~400MB) per worker.
    chunk = max(1, min(n_boot, 2_000_000 // n))
    hits, done = 0, 0
    if sampling == "block":
        size = max(1, min(n, int(block_size or max(1, int(n ** 0.5)))))
        n_blocks = int(np.ceil(n / size))
        # Prefix sums let each sampled block contribute its sum without
        # allocating a bootstrap x trades matrix of expanded block indices.
        prefix = np.concatenate(([0.0], np.cumsum(np.tile(centered, 2))))
        starts = np.arange(n)
        block_sums = prefix[starts + size] - prefix[starts]
        remainder = n - (n_blocks - 1) * size
        last_sums = prefix[starts + remainder] - prefix[starts]
    while done < n_boot:
        k = min(chunk, n_boot - done)
        if sampling == "block":
            indices = draw(0, n, size=(k, n_blocks))
            totals = block_sums[indices[:, :-1]].sum(axis=1) + last_sums[indices[:, -1]]
            boot_means = totals / n
        else:
            boot_means = centered[draw(0, n, size=(k, n))].mean(axis=1)
        hits += int(np.sum(boot_means >= pnl.mean()))
        done += k
    return float((hits + 1) / (n_boot + 1))


def closed_trade_drawdown(trade_pnl_list, initial_capital):
    """Max drawdown of the closed-trade equity path (same measure as the MC).

    ``trade_pnl_list`` must be in chronological ExitDate order.
    """
    _, dd = _equity_and_drawdown(np.asarray(trade_pnl_list, dtype=float), initial_capital)
    return float(dd)


def analyze_mc_results_v2(result, mc_results, trade_pnl_list, rng=None, n_boot=None,
                          sampling="iid", block_size=None):
    """Score a strategy against its Monte Carlo results.

    Points (same total range as legacy):
      1. Edge test: bootstrap p-value of mean P&L < 0.05 -> +2, else -1
         ("No Significant Edge").
      2. DD realism: closed-trade historical DD >= MC median DD -> +1, else -1
         ("DD Understated"). Both sides are closed-trade drawdowns.
      3. Tail risk (unchanged): MC 95th pct DD < 50% -> +2; < 80% -> -1
         ("Moderate Tail Risk"); else -2 ("High Tail Risk").

    ``rng`` is an optional numpy Generator for reproducibility.
    """
    if mc_results is None:
        return {"mc_verdict": "N/A (Low Trades)", "mc_score": 0}

    initial = result['initial_capital']
    mc_median_dd = np.percentile(mc_results['max_drawdowns'], 50)
    mc_95th_dd = np.percentile(mc_results['max_drawdowns'], 95)

    p_val = bootstrap_mean_pvalue(trade_pnl_list, n_boot or _MIN_BOOT, rng,
                                  sampling=sampling, block_size=block_size)
    hist_dd = closed_trade_drawdown(trade_pnl_list, initial)

    score = 0
    verdicts = []

    if p_val < EDGE_P_THRESHOLD:
        score += 2
    else:
        score -= 1
        verdicts.append("No Significant Edge")

    if hist_dd >= mc_median_dd:
        score += 1
    else:
        score -= 1
        verdicts.append("DD Understated")

    if mc_95th_dd < 0.50:
        score += 2
    elif mc_95th_dd < 0.80:
        score -= 1
        verdicts.append("Moderate Tail Risk")
    else:
        score -= 2
        verdicts.append("High Tail Risk")

    return {
        "mc_verdict": ", ".join(verdicts) if verdicts else "Robust",
        "mc_score": score,
        "mc_edge_pvalue": round(p_val, 4),
        "mc_closed_trade_dd": round(hist_dd, 4),
    }
