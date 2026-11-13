# PROPOSAL: give-back excursions for the synthetic day generator

Status: **proposal only.** `lucid_structure.py`, `flybrain/prop.py`, the frontend and `data/prop_structure/*` are not
edited. Implementation: `prop_realtape/proposals/giveback_synth.py`. Driver: `prop_realtape/proposals/run_giveback.py`.
Tests: `prop_realtape/tests/test_giveback_synth.py` (19). Outputs: `data/prop_realtape/giveback/`
(`synthetic.json`, `synthetic_gmin8.json`, `real.json`, `laws.json`, `tables.json`, logs). Strategy-free: coin-flip
direction, no entry rule, no validation window spent. The real tape is used only to validate; nothing is calibrated.

## 1. Problem
`lucid_structure.make_days` gives each trade two numbers besides its outcome: a winner's worst excursion D and a
loser's best excursion M, both from the driftless-walk conditional laws. `day_table` then draws a winner as
dip-then-run (0 → −D → T) and a loser as run-then-fall (0 → M → −S).

- For a loser this shape is exact for an intraday trail. Its maximum drawdown is M + S, because the stop is the
  path's last and lowest point.
- For a winner it is not. A winner's maximum drawdown from its running peak is set equal to its dip D (< S), so it
  can never give back gains from an intra-trade peak.
- Under the same driftless law, P(drawdown ≥ 400t | win) = 10.6% at S = T = 310. The old table gives 0.
- Real NQ 2022-26 gives 7.1% (`laws.json`).
- So plans with an intraday trail come out optimistic, while EOD-drawdown plans (which read only the day's
  minimum) do not.

## 2. The law (Brownian excursion theory; no parameters, no market data)
Excursions of a driftless walk below its running maximum m form a Poisson point process in (level m, depth g),
with intensity **dm dg / g²** (Itô/Lévy). Take a bracket with stop S below and target T above. An excursion that
starts at level m kills the trade iff g ≥ m + S.

- **Win probability:** P(win) = exp(−∫₀ᵀ dm/(m+S)) = S/(S+T). This is the usual value; `make_days` keeps its own
  p = S/(S+T+1).
- **Given a win:** the excursions on m ∈ [0, T] are the same Poisson process restricted to g < m + S.
- **Dip marginal, unchanged:** for a winner, P(D ≥ d) = T(S−d)/((T+d)S). This is exactly `make_days`' mirrored law.
- **Give-back (new):** for a winner, the non-killing excursions with g ≥ G are Poisson with mean
  I(G) = ∫_{max(0,G−S)}^{T} (1/G − 1/(m+S)) dm, so

  **P(MDD ≥ G | win) = 1 − exp(−[(T−l)/G − ln((T+S)/(l+S))]), with l = max(0, G−S).**

  For G ≤ S this equals Lehoczky's (1977) form, (1/S)∫₀ᵀ e^{−m/G}/G · (m−G+S) dm, in which the running maximum at
  the first G-drawdown is exponential with mean G. For G > S the Lehoczky product form overcounts, because the path
  could hit the stop before the drawdown reaches G. The Poisson form is the correct one there. Tests check both.
- **Losers:** M keeps the old law, P(M ≥ m | lose) = S(T−m)/((S+m)T). Before the maximum, the excursions are the
  process on [0, M] restricted to g < m + S. Then a final excursion runs from M to the stop.

### Generator (`make_days_giveback`, same signature and same returned arrays as `make_days`)
1. Run `make_days`' RNG stream unchanged: the win flags, u, the slip, pnl, D(u) and M(u). These arrays come out
   **bit-identical** (tested for k = 1, 2, 3 and `until_win`).
2. On a second stream `default_rng([seed, 0x6B1C])`, build the path:
   - **Winner, given D.** The excursion that reaches the global minimum sits at level m* with density
     ∝ 1/(m*+D)² on [0, T] (inverse CDF in closed form), and its depth is m* + D. Every other excursion is the
     Poisson process restricted to g − m < D.
   - **Loser, given M.** The Poisson process on [0, M] restricted to g < m + S.
   - **Sampling.** Both are drawn by thinning a homogeneous process: N ~ Poisson(top/g_min), m ~ U(0, top),
     g = g_min/U, and only points under the cap are kept. Excursions shallower than g_min (default 1 tick) are
     dropped.
3. Bars use `make_days`' $ convention: hi is the gross level × $/tick, and lo is net of round-trip fees.
   - Each excursion becomes one bar (hi = m, lo = m − g).
   - Each trade ends with a final bar (winner: hi T, lo pnl; loser: hi M, lo pnl).
   - Multi-trade days are chained at the running net pnl.

### Engine table (`table(d, mode, dll)`)
- **`eod`** (no stage trails intraday): one bar per day (open 0, day max, day min, pnl). This makes the same decisions
  as `day_table`.
- **`path`** (some stage trails intraday): the bars in path order, compressed exactly for `run_stage`, which credits
  a bar's hi before its lo.
  - A bar p merges into the next bar s when p.lo ≥ s.lo **and** p.lo > −DLL.
  - This is `replay.compress`'s `merge`, made DLL-safe. A bar that crosses the DLL level is never merged into a later
    one, so a DLL freeze sees the peak of its own time, and nothing after it can matter.
  - Vectorised: a bar is kept iff it crosses the DLL, or no DLL-crossing bar follows it that day and its lo is below
    every later lo of that day.
  - Opens are set to the bar's hi. The path is continuous, so a breach or freeze fills at the level, as in the old
    table.
  - The result is about 11 bars per day at g_min = 1, and about 6 at g_min = 8.
- **Exactness:**
  - The compressed table gives the same account as the uncompressed bars: this is tested for Apex Intraday,
    LucidDaily 25K/50K and Rapid 50K, with and without a DLL.
  - Dropping every excursion under 16 ticks changes no account (tested). The reason: a breach, DLL or lock
    decision involves either the day's minimum, which is always kept, or an excursion deeper than the trail or DLL
    in ticks.
  - g_min = 8 reproduces the g_min = 1 EVs within noise (`synthetic_gmin8.json`) and is about 10× faster. Use 8 in
    production.

### What changes for `flybrain.prop.run_stage`
- No engine change is needed.
- A synthetic day stops being one or two hi/lo bars. It becomes a short list of bars in path order (records with
  rising peaks), the same layout `replay.compress_mode` produces from the 1m tape.
  - EOD plans keep one bar a day (`eod`).
  - Intraday-trail plans get the `path` compression above.
  - The `merge` vs `records` split from `state.json` is replaced by one DLL-aware merge rule, which is exact in both
    cases. The same rule could replace `replay.compress`'s `records` mode for the tape too, but this proposal does
    not touch `replay.py`.

## 3. Minimal diff sketch for `lucid_structure.py` (not applied)
```diff
+from prop_realtape.proposals.giveback_synth import excursions, table as path_table, G_MIN  # or inline them here
+PATH_SALT = 0x6B1C
@@ def make_days(n_days, risk, stop_ticks, rr, k=1, mode="fixed", edge=0.0, seed=0, comm=COMM_SIDE):
     ...                                   # existing body unchanged up to `trades = live.sum(1)`
-    return dict(pnl=pnl.sum(1), lo=day_lo, hi=day_hi, trades=trades, contracts=n, risk=n * S * TICK_USD,
-                p=p, target_ticks=T, won=win[:, 0] if k == 1 else None)
+    out = dict(pnl=pnl.sum(1), lo=day_lo, hi=day_hi, trades=trades, contracts=n, risk=n * S * TICK_USD,
+               p=p, target_ticks=T, won=win[:, 0] if k == 1 else None)
+    # path of every live trade, from a second RNG stream (the arrays above stay bit-identical)
+    out["bars"] = _trade_bars(np.random.default_rng([seed, PATH_SALT]), win.ravel(), live.ravel(), before.ravel(),
+                              pnl.ravel(), S, T, worst_winner, best_loser, TICK_USD * n, fees, k, g_min=8.0)
+    return out
@@
-def day_table(d):
+def day_table(d, plan=None):
+    if plan is not None and "intraday" in (plan.get("evalDrawdown"), plan.get("fundedDrawdown")):
+        return path_table(d, "path", plan.get("dailyLossLimit") or None)
     ...                                   # existing body (EOD: identical decisions)
@@ def attempts(d, plan, paths=4000, horizon=250, seed=1):
-    days = day_table(d)
+    days = day_table(d, plan)
```
`_trade_bars` is the bar-assembly block of `make_days_giveback` (about 20 lines). Once the diff is applied:

- **Not affected:** every EOD-drawdown headline (Topstep, LucidFlex/Pro/Direct, Alpha, MFF Builder/Rapid EOD, Apex
  EOD) is unchanged to the cent and needs no re-run.
- **Must be re-run:** the intraday-trail plans (Apex Intraday, LucidDaily, MFF Rapid). Their best risk may also move,
  because only the old headline bracket was re-scored here.
- **Fixtures:** `flybrain/fixtures/prop_parity.json` tests the account engine, not the generator, so it is untouched.

## 4. Validation

### 4a. Excursion laws: analytic vs real NQ (10 MNQ × 310t, 09:35 entry, flat 16:59; `laws.json`)
P(max drawdown from the running peak ≥ G | win):

| G (ticks) | old table | new law | real 2022-26 | real 2019-21 | real 2011-18 |
|---:|---:|---:|---:|---:|---:|
| 200 | 21.6% | 57.6% | 60.2% | 42.4% | 23.1% |
| 300 | 1.6% | 28.8% | 25.7% | 18.0% | 8.2% |
| 400 | 0 | 10.6% | 7.1% | 6.5% | 2.7% |
| 450 | 0 | 5.6% | 3.7% | 2.4% | 1.1% |

- Dips (unchanged law): P(D ≥ 200 | win) is 21.6% in the law against 18.1% / 13.9% / 6.0% on the tape.
- Loser run-ups (unchanged law): P(M ≥ 90 | lose) is 55.0% in the law against 52.9% / 42.4% / 28.0%.
- In 2022-26 (4% flat-by exits) the law matches the tape's body. Its tail is about a third heavier than the tape's
  at 400t or more.
- Older eras are lighter everywhere, because flat-by censors the long, wandering trades (34% and 91% flat-by
  exits). A regime-free law cannot follow that, and it is not meant to.

### 4b. EV per account: old synthetic → new synthetic vs real NQ 09:35 fixed (coin flip)
- **Synthetic runs:** 16 seeds × 25,000 paths at each plan's published bracket. Seeds 100+i / 200+i are the ones
  the headlines used, and the old column reproduces every stored headline to 0.1.
- **Real runs:** a 64-coin × 2,000-path block bootstrap, the same cell as `run_plan`. Apex 50K Intraday reproduces
  its stored +52.9 exactly.
- **CI columns:** the synthetic CI is ±2.13 se over seeds; the real CI is the 64-coin t-interval.

| plan (bracket) | DD / DLL | old synth | **new synth** | real 2022-26 [95% CI] | real 2019-21 | old / new inside real CI |
|---|---|---:|---:|---:|---:|:---:|
| **Apex 50K Intraday, coupon** (1550/310) | intraday, none | +80.1 | **+44.6** [42, 47] | +52.9 [40, 66] | +44.1 | no / **yes** |
| Apex 50K Intraday Rithmic, coupon | intraday, none | +80.1 | +44.6 | (= Tradovate synth; eval lock 3000 never binds) | | — |
| Apex 25K Intraday, coupon (800/320) | intraday, none | +26.3 | **+8.0** [6, 10] | +13.1 [8, 18] | +10.2 | no / **yes** (edge) |
| Apex 25K Intraday Rithmic, coupon | intraday, none | +26.3 | +8.0 | — | | — |
| LucidDaily 25K (650/325) | funded intraday, DLL 600 | −30.6 | −32.6 [−34, −32] | −29.8 [−33, −26] | −40.6 | yes / yes |
| LucidDaily 50K (2499/294) | funded intraday, DLL 1200 | −32.8 | **−49.1** [−51, −47] | −44.6 [−50, −40] | −43.8 | no / **yes** |
| LucidDaily 100K (3528/294) | funded intraday, DLL 1800 | −76.6 | **−97.4** [−100, −95] | −90.2 [−97, −83] | −91.9 | no / no (just outside) |
| LucidDaily 150K (5066/298) | funded intraday, DLL 2700 | −98.2 | −126.8 [−131, −123] | −108.3 [−119, −97] | −124.6 | yes / no (overshoots) |
| MFF Rapid 25K noDLL (976/279) | funded intraday, none | −46.2 | **−76.1** [−78, −75] | −79.2 [−85, −73] | −79.6 | no / **yes** |
| MFF Rapid 50K noDLL (1950/300) | funded intraday, none | −5.4 | **−63.1** [−66, −60] | −63.8 [−77, −50] | −69.4 | no / **yes** |
| MFF Rapid 100K noDLL (3070/307)* | funded intraday, none | −54.0 | **−140.0** [−145, −135] | −139.5 [−160, −119] | −151.7 | no / **yes** |
| MFF Rapid 150K noDLL (5400/300)* | funded intraday, none | −15.3 | **−167.5** [−176, −159] | −157.9 [−188, −128] | −184.7 | no / **yes** |
| *controls (EOD drawdown)* | | | | | | |
| Topstep Cons no-fee 50K noDLL (1550/310) | EOD, none | +153.1 | +153.1 (identical) | +148.5 [119, 178] | +138.5 | yes / yes |
| LucidFlex 50K (1050/300) | EOD, DLL 1200 | +89.2 | +89.2 (identical) | +84.7 [64, 105] | +78.2 | yes / yes |
| Alpha Standard 50K (1550/310) | EOD, DLL 1000 | +74.5 | +74.5 (identical) | +122.7 [93, 152] | +97.9 | no / no |
| MFF Builder 50K (1050/300) | EOD, DLL 1000 | +6.8 | +6.8 (identical) | +9.3 [−9, 28] | −13.1 | yes / yes |
| Apex 50K EOD, coupon (1050/300) | EOD, DLL 1000 | +95.8 | +95.8 (identical) | +102.6 [78, 127] | +88.6 | yes / yes |
| Apex 25K EOD, coupon (524/262) | EOD, DLL 500 | +13.5 | +13.5 (identical) | — | | — |

\* No bracket under the max loss in MFF's confirm run. These rows use the best confirm bracket, re-scored on the
headline seeds.

- **(1) Apex 50K Intraday moves from +80 to +45; the real figure is +53 [40, 66].** It moves past the real point by
  about $8, but stays inside its CI.
  - The mechanism matches the tape: pass rate goes 26.3% → 20.9% (real 21.4%) and P(paid) goes 3.5% → 2.4%
    (real 2.7%).
  - Across the 10 intraday-trail plans with a real run, the old synthetic is inside the real 2022-26 CI for 2.
    The new one is inside for 8, and LucidDaily 100K misses by about $0.5.
  - The MFF Rapid family was the worst miss under the old law (−5 vs −64 at 50K; −15 vs −158 at 150K). Its risk is
    at or above the max loss, so any give-back breaches the trail. The new law matches it almost exactly, P(paid)
    included (4.44% vs 4.41% at 50K).
- **(2) EOD plans stay where they are: identical to the cent**, by construction and by test. The dip marginal, the
  day's minimum and every EOD decision are unchanged.
- **(3) The DLL-inside-stop effect (Alpha Standard: real +123 vs synthetic +75) is not addressed.**
  - That gap comes from the dip marginal: real 2022-26 winners dip ≥ 200t 18.1% of the time, against 21.6% in the
    law. The new law keeps the dip marginal exactly, on purpose, so the EOD headlines stay put.
  - The same residual shows up where a DLL sits well inside the stop *and* the trail is intraday. LucidDaily 150K
    (DLL $2,700 vs $5,066 risk) is overshot by the new law (−127 vs −108), and LucidDaily 100K is just outside its
    CI.
  - Closing this would need a market-dependent dip law, calibrated on 2022-26 and validated on 2019-21. It would
    break the regime-free design and move every EOD+DLL headline, so it is not proposed here.
  - The new law does touch the loser side of DLL plans. A loser's DLL crossing can now happen before its peak, which
    is kinder than the old run-then-fall. That effect is small: LucidDaily 25K moves only −2.

## 5. Caveats
- **The law is regime-free, and its give-back tail is heavier than the 2022-26 tape's (10.6% vs 7.1% at 400t).**
  So intraday-trail EVs may now be slightly pessimistic. Apex 50K lands at −8 against the real point estimate, and
  25K at −5. Real excursions are thinner than Brownian ones, plausibly because flat-by censoring and the 1m bars
  hide intra-bar paths. The analytic law is a better central estimate than the old one, but not an upper bound.
- **The real comparison is one cell:** NQ, 09:35, fixed bracket, coin flip. 2019-21 and 2011-18 are a different
  trade (34% and 91% flat-by exits), so the EV match is only claimed for 2022-26. Nothing was calibrated, so no
  window was spent.
- **Brackets were not re-optimised.** The intraday plans' best risk will likely move down under the new law, since
  a smaller stop leaves more room under the trail. Re-run `firm_study` / `apex_study` after applying the diff.
- **$ convention kept from `make_days`.** Bar highs are gross and lows are net of round-trip fees, so a modelled
  drawdown is about $12 larger than the tape's at 10 MNQ. This is negligible and kept for exact reduction.
- **The target level is T in the excursion law and T+1 in the win probability** (`make_days`' existing mix). The
  difference is under 0.3% at 310t.
- **Multi-trade days (k > 1)** are now ordered paths rather than one pessimistic bar. EOD plans are still identical;
  intraday plans with k > 1 were not studied.
- **Runtime:** g_min = 1 costs about 2–3 s per 40,000-day table; g_min = 8 about 0.25 s with the same EVs.
