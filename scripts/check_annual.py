import json

with open(r"output\runs\2026-08-06_10-35-14\llm_verdict.json") as f:
    v = json.load(f)

s = v["strategies"][0]
ar = s["annual_returns"]
ec = s["equity_curve"]

totals = {"strategy": s["strategy_return_pct"],
          "SPY": v["benchmarks"]["SPY"],
          "QQQ": v["benchmarks"]["QQQ"]}
keys = {"strategy": "strategy_pct", "SPY": "SPY_pct", "QQQ": "QQQ_pct"}

print("series      annual_compounded   equity_curve   reported_total")
for name, key in keys.items():
    comp = 1.0
    for row in ar:
        comp *= (1.0 + row[key] / 100.0)
    comp = (comp - 1.0) * 100
    curve = (ec[name][-1] / ec[name][0] - 1) * 100
    print("%-10s %17.4f %14.4f %16.4f" % (name, comp, curve, totals[name]))

print("\nper-year strategy: reported vs equity-curve-derived")
dates = ec["dates"]
eq = ec["strategy"]
print("year   reported   derived     diff")
for row in ar:
    yr = row["year"]
    idx = [i for i, d in enumerate(dates) if d.startswith(str(yr))]
    start = eq[idx[0] - 1] if idx[0] > 0 else eq[0]
    derived = (eq[idx[-1]] / start - 1) * 100
    print("%d %9.2f %9.2f %8.2f" % (yr, row["strategy_pct"], derived, row["strategy_pct"] - derived))