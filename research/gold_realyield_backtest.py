import yfinance as yf, pandas as pd, numpy as np
pd.options.mode.chained_assignment=None

def load(tkr):
    d = yf.download(tkr:=tkr, start="2004-01-01", interval="1d", auto_adjust=False, progress=False)
    if isinstance(d.columns, pd.MultiIndex): d.columns=d.columns.get_level_values(0)
    d = d[["Open","High","Low","Close","Volume"]].dropna()
    d.index = pd.to_datetime(d.index).tz_localize(None)
    return d

def realyield():
    r = pd.read_csv("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10")
    r.columns=["date","ry"]; r["date"]=pd.to_datetime(r["date"])
    r["ry"]=pd.to_numeric(r["ry"],errors="coerce")
    return r.set_index("date")["ry"].dropna()

def backtest(tkr, use_regime, regime_exit, N=20):
    d=load(tkr); ry=realyield().reindex(d.index).ffill()
    H=d["High"]; L=d["Low"]; C=d["Close"]; O=d["Open"]; V=d["Volume"]
    prior_high=H.rolling(N).max().shift(1)
    vmed=V.rolling(N).median().shift(1)
    buypct=((C-L)/(H-L)).replace([np.inf,-np.inf],np.nan).fillna(0.5)
    ry20=ry-ry.shift(N)                     # real-yield change over N days
    gate=(C>prior_high)&(V>vmed)&(buypct>=0.60)
    regime_ok=(ry20<0)                      # real yields falling
    entry_sig = gate & (regime_ok if use_regime else True)
    idx=d.index; trades=[]; i=1; n=len(d)
    while i < n-1:
        if bool(entry_sig.iloc[i]):
            entry_day=i+1                    # enter next open
            if entry_day>=n: break
            e_open=O.iloc[entry_day]; line=prior_high.iloc[i]
            j=entry_day
            while j < n-1:
                c=C.iloc[j]
                stop = c < line
                reg_rev = (ry20.iloc[j] > 0) if regime_exit else False
                if stop or reg_rev:
                    break
                j+=1
            x_open=O.iloc[min(j+1,n-1)]
            ret=(x_open/e_open)-1
            trades.append(dict(entry=idx[entry_day], exit=idx[min(j+1,n-1)],
                               ret=ret, ry_chg=ry.iloc[min(j+1,n-1)]-ry.iloc[entry_day]))
            i=j+1
        else:
            i+=1
    return pd.DataFrame(trades)

def stats(t, label):
    if len(t)==0: print(f"{label:38s}  NO TRADES"); return
    r=t["ret"]; wins=r[r>0]; losses=r[r<=0]
    wr=len(wins)/len(r)*100
    aw=wins.mean()*100 if len(wins) else 0; al=losses.mean()*100 if len(losses) else 0
    exp=r.mean()*100
    pf=(wins.sum()/-losses.sum()) if losses.sum()!=0 else float('inf')
    eq=(1+r).cumprod(); dd=((eq/eq.cummax())-1).min()*100
    tot=(eq.iloc[-1]-1)*100
    sharpe=(r.mean()/r.std()*np.sqrt(len(r)/((t['exit'].max()-t['entry'].min()).days/365.25))) if r.std()>0 else 0
    ry_w=t.loc[r>0,"ry_chg"].mean(); ry_l=t.loc[r<=0,"ry_chg"].mean()
    print(f"{label:38s} n={len(r):3d} win%={wr:4.0f} exp/trade={exp:+5.2f}% avgW={aw:+5.2f} avgL={al:+5.2f} PF={pf:4.2f} maxDD={dd:6.1f}% tot={tot:+7.0f}% RYΔ w/l={ry_w:+.2f}/{ry_l:+.2f}")

for tkr in ["GLD","GDX"]:
    print(f"\n===== {tkr} =====")
    for ur,re_ in [(False,False),(True,False),(True,True)]:
        tag=("gate-only" if not ur else ("gate+regime" if not re_ else "gate+regime+regime-exit"))
        t=backtest(tkr,ur,re_)
        stats(t, tag+" [ALL 2004+]")
        if len(t):
            pre=t[t["entry"]<"2022-01-01"]; post=t[t["entry"]>="2022-01-01"]
            stats(pre, tag+"   pre-2022")
            stats(post, tag+"   2022+")

print("\n===== BENCHMARK: buy & hold, and time-in-market for the tradeable (regime-exit) variant =====")
for tkr in ["GLD","GDX"]:
    d=load(tkr)
    bh=(d["Close"].iloc[-1]/d["Open"].iloc[ (d.index>=pd.Timestamp("2004-11-19")).argmax() ]-1)*100 if tkr=="GLD" else (d["Close"].iloc[-1]/d["Open"].iloc[0]-1)*100
    t=backtest(tkr,True,True)
    days_in=(t["exit"]-t["entry"]).dt.days.sum(); span=(d.index[-1]-d.index[0]).days
    print(f"{tkr}: buy&hold ~{bh:+.0f}%  |  regime-exit strat time-in-market ~{days_in/span*100:.0f}%  ({days_in}d of {span}d)")
