import pandas as pd

CSV = r"output\runs\2026-08-06_10-35-14\raw_trades\Nasdaq_100_PIT\Nasdaq_100_PIT_Donchian_Trend_Breakout_trade_log.csv"
INITIAL = 100000.0

df = pd.read_csv(CSV)
df["EntryDate"] = pd.to_datetime(df["EntryDate"])
df["ExitDate"] = pd.to_datetime(df["ExitDate"], errors="coerce")
df["Profit"] = pd.to_numeric(df["Profit"], errors="coerce")
df["Notional"] = df["Shares"] * df["EntryPrice"]

ev = []
for _, r in df.iterrows():
    ev.append((r["EntryDate"], 1))
    if pd.notna(r["ExitDate"]):
        ev.append((r["ExitDate"], -1))

e = pd.DataFrame(ev, columns=["date", "d"]).sort_values(["date", "d"], kind="mergesort")
e["c"] = e["d"].cumsum()
peak = e.loc[e["c"].idxmax()]
peak_date = peak["date"]
print("peak concurrency :", int(peak["c"]), "on", peak_date.date())

still_open = df["ExitDate"].isna() | (df["ExitDate"] > peak_date)
op = df[(df["EntryDate"] <= peak_date) & still_open]
notional = op["Notional"].sum()
realized = df.loc[df["ExitDate"] <= peak_date, "Profit"].sum()
floor = INITIAL + realized

print("open positions   :", len(op))
print("entry notional   : $%s" % format(round(notional), ","))
print("realized to date : $%s" % format(round(realized), ","))
print("equity floor     : $%s" % format(round(floor), ","))
print("gross exposure   : %.1f%% of equity floor" % (notional / floor * 100))
print("VERDICT          :", "no leverage" if notional <= floor else "EXCEEDS EQUITY - investigate")