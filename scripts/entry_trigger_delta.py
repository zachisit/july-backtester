"""Per-strategy trade-count delta, entry_trigger level vs edge (#401)."""
import os, sys, warnings
sys.path.insert(0, "/tmp/wtflip")
os.environ.setdefault("MPLBACKEND", "Agg")
warnings.filterwarnings("ignore")
import pandas as pd, numpy as np
import config as C

CORPUS = "/Users/zach/Desktop/github/july-backtester/parquet_data/data"
START, END = "2018-01-01", "2026-06-30"
SYMS = ["AAPL","MSFT","NVDA","AMZN","GOOGL","META","JPM","XOM","JNJ","WMT",
        "PG","UNH","HD","CAT","BA","GE","F","T","KO","PFE",
        "CSCO","INTC","ORCL","CVX","MRK","ABBV","CRM","AMD","QCOM","TXN"]

def load(sym):
    p = os.path.join(CORPUS, f"{sym}.parquet")
    if not os.path.exists(p): return None
    df = pd.read_parquet(p); df.index = pd.to_datetime(df.index)
    if df.index.tz is None: df.index = df.index.tz_localize("UTC")
    df = df.loc[(df.index >= pd.Timestamp(START, tz="UTC")) & (df.index <= pd.Timestamp(END, tz="UTC"))]
    need = {"Open","High","Low","Close","Volume"}
    return df if need.issubset(df.columns) and len(df) > 250 else None

data = {s: d for s in SYMS if (d := load(s)) is not None}
spy = load("SPY"); vix = load("$VIX")
if vix is None: vix = load("VIX")
print(f"universe: {len(data)} symbols, {START}..{END}", flush=True)

from helpers.registry import load_strategies, get_active_strategies
load_strategies("custom_strategies")
strats = get_active_strategies()
print(f"strategies: {len(strats)}", flush=True)

from helpers import portfolio_simulations as PS

def run(mode):
    C.CONFIG["entry_trigger"] = mode
    out = {}
    for name, meta in strats.items():
        sigs = {}
        for sym, df in data.items():
            try:
                kw = dict(meta.get("params") or {})
                if "spy" in (meta.get("dependencies") or []): kw["spy_df"] = spy
                if "vix" in (meta.get("dependencies") or []): kw["vix_df"] = vix
                r = meta["logic"](df.copy(), **kw)
                s = r["Signal"] if isinstance(r, pd.DataFrame) and "Signal" in r else r
                sigs[sym] = pd.Series(s).reindex(df.index).fillna(0)
            except Exception:
                continue
        if not sigs: continue
        try:
            res = PS.run_portfolio_simulation(
                {k: data[k] for k in sigs}, sigs, 100000.0, 0.10,
                spy, vix, None, {"type": "percentage", "value": 0.05})
            tl = res[0] if isinstance(res, tuple) else res
            log = tl.get("trade_log") if isinstance(tl, dict) else tl
            out[name] = len(log) if log is not None else 0
        except Exception as e:
            out[name] = f"ERR {type(e).__name__}"
    return out

lvl = run("level"); edg = run("edge")
rows = []
for k in sorted(set(lvl) | set(edg)):
    a, b = lvl.get(k), edg.get(k)
    if isinstance(a, int) and isinstance(b, int):
        rows.append((k, a, b, b - a, (b - a) / a * 100 if a else float("nan")))
print(f"\n{'strategy':44s} {'level':>7s} {'edge':>7s} {'delta':>7s} {'pct':>8s}")
tl_, te_ = 0, 0
for k, a, b, d, p in rows:
    tl_ += a; te_ += b
    print(f"{k[:44]:44s} {a:7d} {b:7d} {d:+7d} {p:+7.1f}%")
print(f"\n{'TOTAL':44s} {tl_:7d} {te_:7d} {te_-tl_:+7d} {(te_-tl_)/tl_*100 if tl_ else 0:+7.1f}%")
print(f"strategies compared: {len(rows)}   unchanged: {sum(1 for r in rows if r[3]==0)}   "
      f"fewer: {sum(1 for r in rows if r[3]<0)}   more: {sum(1 for r in rows if r[3]>0)}")
