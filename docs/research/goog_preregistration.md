# Pre-registration — GOOG strategy OOS evaluation
Written 2026-09-12, BEFORE any out-of-sample data was examined.

## Holdout
OOS = 2018-01-01 .. 2026-09-11 (2,185 bars). Untouched during all search.
IS  = 2004-08-19 .. 2017-12-31 (3,366 bars).

## Benchmark (the thing to beat)
GOOGL buy-and-hold, OOS window, same cost model.
IS full:      CAGR 25.58%  Sharpe 0.77  MaxDD -65.3%  Calmar 0.39
IS 2009-2017: CAGR 23.86%  Sharpe 0.83  MaxDD -30.4%  Calmar 0.78

## Candidate A — PRE-REGISTERED BY THE LEAD (no further tuning)
Plain overnight-only: target exposure 1.0 from the close of every session,
0.0 from the open. Buy MOC, sell MOO, every session. No conditioning, no
filter, no parameters whatsoever.
  Tested at 1.0 and 2.0 bp/side. Zero fitted parameters => trials = 1 for DSR.

  IS 2004-2017 @1bp: CAGR 30.55% Sharpe 1.28 MaxDD -25.4% Calmar 1.20
  IS 2009-2017 @1bp: CAGR 21.30% Sharpe 1.06 MaxDD -10.4% Calmar 2.05
  IS 2009-2017 @2bp: CAGR 15.34% Sharpe 0.74 MaxDD -11.1% Calmar 1.38

  Stated expectation for OOS (recorded in advance): overnight drift post-2009
  is flat at ~10 bp/day (slope -0.02 bp/day/yr, p=0.969), so the 2009-2017
  numbers are the honest prior. I expect OOS Sharpe ~0.9-1.1 and MaxDD well
  below B&H at 1bp, DEGRADING materially at 3bp+. If OOS Sharpe < 0.5 the
  anomaly has decayed and the candidate is dead.

## Candidates B..E — from the Stage-1 agent, pending
To be added verbatim as received, with the agent's reported total variant
count carried into the DSR denominator. No candidate may be modified after
its OOS run.

## Acceptance gate (fixed, mutation-tested before any candidate was seen)
scripts/goog_oos_validate.py. All six must pass:
  1. beats B&H Calmar (OOS)
  2. beats B&H Sharpe (OOS)
  3. retains >= 60% of B&H CAGR
  4. Deflated Sharpe > 0.95 at the full trial count
  5. >= 30 trades
  6. paired block-bootstrap p5 of (strategy Calmar - B&H Calmar) > 0
Gate validation: perfect-foresight oracle ACCEPT 6/6; random exposure REJECT
5/6; naive 200-SMA overlay REJECT.

## Rules
- One OOS evaluation per candidate. A re-run of a tweaked variant is a NEW
  trial and must be disclosed in the DSR denominator.
- Thresholds above are frozen. Any change after seeing OOS results invalidates
  the exercise and must be reported as such.

---
# RESULT LOG (appended as runs complete)

## Candidate A — overnight-only — RUN 2026-09-12 — **REJECT**
OOS 2018-01-01..2026-09-11, trials=1.
  @1bp/side: CAGR  +0.05%  Sharpe -0.09  MaxDD -50.1%  Calmar  0.00
  @2bp/side: CAGR  -4.86%  Sharpe -0.33  MaxDD -57.0%  Calmar -0.09
  B&H:       CAGR +23.74%  Sharpe  0.71  MaxDD -44.3%  Calmar  0.54
  DSR 0.219 / 0.069. Paired boot p5 dCalmar -1.16 / -1.31. 0 of 6 gates cleared
  (bar the trivial trade-count check).

My pre-registered expectation was "OOS Sharpe ~0.9-1.1". ACTUAL -0.09. The
prediction was wrong and the candidate is dead. Recording this explicitly
because the whole point of writing the expectation down first is that it can
be scored.

Diagnosis: GOOGL overnight drift fell 10.1 -> 2.4 bp/day between the eras,
versus a 13.3 bp/day round-trip break-even. The collapse is NAME-SPECIFIC:
AAPL also fell (12.3 -> 1.3) but MSFT (+3.4), AMZN (+0.2), NVDA (+4.3),
SPY (+1.1), QQQ (+0.5) held or grew. The anomaly persists in the market; GOOGL
stopped expressing it. The 2009-2017 flat-slope finding (p=0.969) did NOT
predict the next era -- stability in-sample is not evidence of stability
out-of-sample.

Holdout looks consumed so far: 2 (Candidate A @1bp, @2bp).

## Candidates B & C (Stage-1 agent finalists) — RUN 2026-09-12 — **REJECT**
OOS, 2bp/side, trials=456 (the agent's full registered variant count).
  C  overnight skip weekend leg: CAGR +2.48%  Sharpe  0.01  MaxDD -38.9%  Calmar  0.06
  B  overnight x min(1,0.30/RV10 lagged): CAGR -4.51%  Sharpe -0.39  MaxDD -50.2%  Calmar -0.09
  B&H:                          CAGR +23.49%  Sharpe  0.71  MaxDD -44.3%  Calmar  0.53
DSR 0.001 and 0.000. Both 1 of 6 gates (trade count only).

IN-SAMPLE reproduction matched the agent independently, confirming we ran the
same strategies: A 24.03%/Calmar 0.90 (agent 24.1%/0.90); C 24.21%/1.08
(agent 24.3%/1.08); B 22.54%/1.08 (agent 22.8%/1.12). Sharpe differs only
because this harness uses rf=4% and the agent used rf=0.

### Implementation bug found and fixed BEFORE these numbers were trusted
First run indexed the night-return by the OPEN date while applying C's Friday
flag as a CLOSE date, which excluded the Thu->Fri leg (the earnings-gap night,
the strongest one) instead of the weekend leg. Detected because the in-sample
reproduction disagreed with the agent's. Candidate A is unaffected (constant
exposure). Independent re-verification of the OOS path requested from the agent.

## Holdout budget consumed
7 looks: A@1bp, A@2bp, C(buggy), B(buggy), C(fixed), B(fixed), plus IS-only
diagnostics that touched no OOS data. Further candidates evaluated here carry
correspondingly less credibility and that must be disclosed with any result.

## Standing conclusion pending verification
0 of 3 pre-registered/agent finalists cleared the gate. Combined with the
agent's 456-variant in-sample search (0 of 353 Search-1 overlays survived the
ex-2008/09 restatement) and an independent 18-fold walk-forward (B&H Calmar
0.53 > all five families), the evidence says buy-and-hold is the best available
strategy on GOOGL.

## Candidate D — earnings-announcement premium — PRE-REGISTERED 2026-09-12
Written before any D result, in- or out-of-sample.

MECHANISM (argued in advance, not found by searching this series): the earnings
announcement premium is a documented anomaly -- stocks earn abnormally high
returns over scheduled earnings announcements, interpreted as compensation for
bearing announcement uncertainty (Beaver 1968; Barber/De George/Lehavy/Trueman
2013). It is a RISK PREMIUM with a stated economic reason, and the exposure
window is fixed by the company's reporting calendar rather than by any
parameter I chose. GOOGL reports after the close, so the premium should land in
the announcement-night gap.

Earnings dates: yfinance get_earnings_dates, 84 quarters, 2004-10-21..2025-06-06
(a real calendar, not the Jan/Apr/Jul/Oct proxy the Stage-1 agent had to use).

  D1: hold ONLY the announcement night (close of announcement day -> next open).
  D2: B&H at 1.0x always, 2.0x over announcement nights only (5%/yr financing
      on the extra 1.0x). This is the version that can clear the CAGR-retention
      gate, since D1 is in the market ~4 nights/year.
  Costs 2bp/side. ~4 round trips/year => cost drag is negligible, which is the
  main reason this family is worth testing when the overnight family died on
  cost and decay.

EXPECTATION RECORDED IN ADVANCE: I expect D1 to show a high per-night mean with
a respectable Sharpe but a tiny CAGR, and therefore to FAIL gate 3 (>=60% of B&H
CAGR) by construction while possibly passing on risk-adjusted terms. I expect D2
to be close to B&H plus a small increment, and to pass or fail on whether the
premium survives at all post-2017. Given that every other GOOGL-specific effect
we found decayed to nothing after 2017, my honest prior is that this one has
decayed too, and I would put this at no better than 1-in-3 to clear the gate.
Trials for DSR: 2 (D1, D2), mechanism-first, not selected from a search.

## Candidate D — earnings premium — RUN 2026-09-12 — **REJECT (both)**
                     IS CAGR/Sharpe/DD/Calmar        OOS CAGR/Sharpe/DD/Calmar
  B&H            24.87% / 0.75 / -65.3% / 0.38   23.49% / 0.71 / -44.3% / 0.53
  D1 earn-night   9.50% / 0.44 / -13.1% / 0.72    1.87% / -0.14 / -17.2% / 0.11
  D2 B&H+2x      37.37% / 0.99 / -61.2% / 0.61   25.87% / 0.75 / -47.8% / 0.54

D1: REJECT, 1/6 gates. Failed gate 3 by construction exactly as predicted.
D2: REJECT, **5 of 6 gates PASSED** — beat B&H on CAGR, Sharpe and Calmar, and
cleared DSR at 0.954. It failed only the paired block-bootstrap:
  dCalmar p5/50/95 = -0.25 / **-0.02** / +0.23   (median difference NEGATIVE)
The +2.4pp CAGR is inside the noise of 31 announcement nights. On a naive
"beats B&H on Calmar and Sharpe" test D2 would have been promoted. The paired
bootstrap is the only gate that caught it — this is the single strongest
argument for having built the gate before looking at any candidate.

Underlying effect decayed like every other GOOGL-specific effect found:
  announcement-night mean  IS +255.0 bp (t=2.78, p=0.0075, n=53)
                          OOS  +72.5 bp (t=0.67, p=0.51,   n=31)

Pre-registered expectation scored: I predicted D1 would fail gate 3 (CORRECT),
that D2 would be "close to B&H plus a small increment" (UNDERSTATED in-sample --
it was +12.5pp CAGR -- but CORRECT out-of-sample at +2.4pp inside noise), and
gave D no better than 1-in-3 to clear the gate (it did not clear).

## FINAL TALLY
Candidates evaluated on the holdout: A(2 cost levels), B, C, D1, D2 = 6 distinct
strategies, 0 accepted. Stage-1 agent searched 456 variants in-sample; an
independent 18-fold walk-forward tested 5 families over 702 fits. Nothing beats
buy-and-hold on GOOGL.

## Independent verification (Stage-1 agent, second engine, no shared code)
CAGR and MaxDD reproduce to 2dp on every finalist; Sharpe differs by ~0.2
exactly as rf=4%/vol=19% predicts. No second bug. The agent deliberately
re-created my alignment bug and got -3.14%/-47.8%, confirming the corrected C
(+2.48%/-38.9%) is right. OOS drift +2.87 bp/day (its window) vs +2.4 (mine) --
same picture; Welch t vs IS 2009-17 = -2.09, so the step-down is significant,
not sampling noise. Trimming top/bottom 1% of nights moves the mean only
+2.87 -> +2.46 bp: broad-based, not tail-driven.

## VENDOR-OPEN FINDING — the overnight backtest was never executable
The agent settled its own flagged risk with a sub-penny test. Exchange auction
crosses print at penny increments; off-exchange midpoint prints do not.
Over 2021-09..2026-06:
  sub-penny CLOSES: 0.1-0.3% of days (closing cross is what vendors record)
  sub-penny OPENS:  GOOGL 12.2% of days (GOOG 14.9, AAPL 15.8, MSFT 15.8,
                    NVDA 10.2, AMZN 12.6; SPY/QQQ ~1.9), rising 6% (2021) ->
                    20% (2025) -> 28% (2026)
On those days the recorded Open is provably an off-exchange print that beat the
NASDAQ opening cross to the tape, i.e. NOT a price a MOO order can receive. And
the bias has a direction: GOOGL overnight return is +7.86 bp on sub-penny-open
days vs +1.45 bp on penny-open days (n=146 vs 1,049).

Consequence: "buy at close, sell at open" on daily bars is not an executable
MOC/MOO strategy. The in-sample overnight edge was overstated by an unknown but
non-zero amount BEFORE decay and costs were even considered. Norgate, Polygon
daily aggregates and Polygon's open/close endpoint all agree to 0.00 bp, and
Polygon's daily open equals its own 9:30 one-minute bar open on 24/24 sampled
days -- so every vendor is recording the first regular-session trade, not the
cross. Agreement across vendors was never evidence of correctness; they share
the same convention.

## FINAL: buy-and-hold is the strategy that pays on GOOGL.
