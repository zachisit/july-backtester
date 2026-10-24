import sys, pandas as pd, numpy as np
d = pd.read_csv(sys.argv[1])
for c in ("ProfitPct","Profit","HoldDuration","entry_Volume_Spike"):
    d[c] = pd.to_numeric(d[c], errors="coerce")
d["EntryDate"] = pd.to_datetime(d.EntryDate, utc=True).dt.tz_localize(None)
d = d.dropna(subset=["Profit","entry_Volume_Spike","HoldDuration"]).sort_values("EntryDate")
d["dead"] = (d.HoldDuration>=20) & (d.ProfitPct.abs()<0.02)
d["q"] = pd.qcut(d.entry_Volume_Spike, 5, labels=False)
def pf(g):
    w,l = g.Profit[g.Profit>0].sum(), -g.Profit[g.Profit<0].sum()
    return w/l if l else np.inf
print(f"\n  OUT-OF-SAMPLE TEST -- Donchian, n={len(d)}")
print(f"\n  {'Q':<4}{'n':>6}{'volspk':>8}{'dead%':>8}{'netP&L':>10}{'mean%':>8}{'win%':>7}{'PF':>7}")
for q,g in d.groupby("q"):
    print(f"  Q{q+1:<3}{len(g):>6}{g.entry_Volume_Spike.median():>8.2f}{g.dead.mean()*100:>7.1f}%"
          f"{g.Profit.sum():>10.0f}{g.ProfitPct.mean()*100:>7.2f}%{(g.ProfitPct>0).mean()*100:>6.0f}%{pf(g):>7.2f}")
mid = d.EntryDate.quantile(0.5)
print(f"\n  split-half (mid {mid.date()}):")
for lab, g in [("FULL", d), ("H1", d[d.EntryDate<mid]), ("H2", d[d.EntryDate>=mid])]:
    qq = pd.qcut(g.entry_Volume_Spike, 5, labels=False)
    lo, rest = g[qq==0], g[qq>0]
    print(f"    {lab:<5} Q1 n={len(lo):<4} net {lo.Profit.sum():>8.0f} PF {pf(lo):>5.2f} | "
          f"rest n={len(rest):<5} net {rest.Profit.sum():>8.0f} PF {pf(rest):>5.2f}")
print(f"\n  by year (Q1 cut on full sample):")
d["q1"] = d.q==0
worse = 0; tot = 0
for y,g in d.groupby(d.EntryDate.dt.year):
    a,b = g[g.q1], g[~g.q1]
    if len(a)<3: continue
    tot += 1; w = a.ProfitPct.mean()<b.ProfitPct.mean(); worse += w
    print(f"    {y}  Q1 n={len(a):<3} {a.ProfitPct.mean()*100:>6.2f}%   rest n={len(b):<4} {b.ProfitPct.mean()*100:>6.2f}%   {'Q1 worse' if w else 'Q1 better'}")
print(f"\n  Q1 worse in {worse} of {tot} years")
k = d[d.q>0]
print(f"\n  drop Q1: n {len(k)} net {k.Profit.sum():.0f} PF {pf(k):.2f}  vs base n {len(d)} net {d.Profit.sum():.0f} PF {pf(d):.2f}")
