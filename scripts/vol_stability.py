import sys, pandas as pd, numpy as np
d = pd.read_csv(sys.argv[1])
for c in ("ProfitPct","Profit","HoldDuration","entry_Volume_Spike"):
    d[c] = pd.to_numeric(d[c], errors="coerce")
d["EntryDate"] = pd.to_datetime(d.EntryDate, utc=True).dt.tz_localize(None)
d = d.dropna(subset=["Profit","entry_Volume_Spike"]).sort_values("EntryDate")
mid = d.EntryDate.quantile(0.5)

def line(g, label):
    if len(g) < 20: print(f"  {label:<22} n={len(g):<4} too few"); return
    q = pd.qcut(g.entry_Volume_Spike, 5, labels=False)
    lo, rest = g[q==0], g[q>0]
    wl, ll = lo.Profit[lo.Profit>0].sum(), -lo.Profit[lo.Profit<0].sum()
    wr, lr = rest.Profit[rest.Profit>0].sum(), -rest.Profit[rest.Profit<0].sum()
    print(f"  {label:<22} Q1 n={len(lo):<4} net {lo.Profit.sum():>7.0f} PF {wl/ll if ll else np.inf:>5.2f} | "
          f"rest n={len(rest):<4} net {rest.Profit.sum():>7.0f} PF {wr/lr if lr else np.inf:>5.2f}")

print("\n  bottom-quintile penalty, split by time")
line(d, "FULL")
line(d[d.EntryDate<mid], f"H1 (pre {mid.date()})")
line(d[d.EntryDate>=mid], f"H2 (post {mid.date()})")
print("\n  by year: Q1 mean% vs rest mean% (Q1 cut on the FULL sample)")
q = pd.qcut(d.entry_Volume_Spike, 5, labels=False)
d["q1"] = q==0
for y,g in d.groupby(d.EntryDate.dt.year):
    a,b = g[g.q1], g[~g.q1]
    if len(a)<2: continue
    print(f"    {y}  Q1 n={len(a):<3} {a.ProfitPct.mean()*100:>6.2f}%   rest n={len(b):<3} {b.ProfitPct.mean()*100:>6.2f}%"
          f"   {'Q1 worse' if a.ProfitPct.mean()<b.ProfitPct.mean() else 'Q1 better'}")
