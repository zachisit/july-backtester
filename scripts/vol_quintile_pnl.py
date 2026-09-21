import sys, pandas as pd, numpy as np
d = pd.read_csv(sys.argv[1])
for c in ("ProfitPct","Profit","HoldDuration","entry_Volume_Spike"):
    d[c] = pd.to_numeric(d[c], errors="coerce")
d = d.dropna(subset=["ProfitPct","Profit","HoldDuration","entry_Volume_Spike"])
d["dead"] = (d.HoldDuration>=20) & (d.ProfitPct.abs()<0.02)
d["q"] = pd.qcut(d.entry_Volume_Spike, 5, labels=False)
print(f"{'Q':<4}{'n':>5}{'dead%':>8}{'netP&L':>10}{'mean%':>8}{'win%':>7}{'PF':>7}{'cap-days':>10}")
for q,g in d.groupby("q"):
    w,l = g.Profit[g.Profit>0].sum(), -g.Profit[g.Profit<0].sum()
    print(f"Q{q+1:<3}{len(g):>5}{g.dead.mean()*100:>7.1f}%{g.Profit.sum():>10.0f}"
          f"{g.ProfitPct.mean()*100:>7.2f}%{(g.ProfitPct>0).mean()*100:>6.0f}%"
          f"{w/l if l else np.inf:>7.2f}{g.HoldDuration.sum():>10.0f}")
print()
for drop in ([0],[0,1]):
    k = d[~d.q.isin(drop)]
    w,l = k.Profit[k.Profit>0].sum(), -k.Profit[k.Profit<0].sum()
    print(f"drop Q{[x+1 for x in drop]}: n {len(k)} ({len(k)/len(d)*100:.0f}%)  "
          f"net {k.Profit.sum():.0f} ({k.Profit.sum()/d.Profit.sum()*100:.0f}% of base)  "
          f"PF {w/l:.2f}  cap-days {k.HoldDuration.sum():.0f} "
          f"({k.HoldDuration.sum()/d.HoldDuration.sum()*100:.0f}%)")
print(f"base:      n {len(d)}  net {d.Profit.sum():.0f}  cap-days {d.HoldDuration.sum():.0f}")
