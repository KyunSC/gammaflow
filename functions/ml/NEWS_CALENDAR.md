# Scheduled news calendar

Backtests can now see when scheduled US economic news lands and how much it tends to matter,
in the spirit of ForexFactory's folders: **high = red, medium = orange, low = yellow**.

One generated calendar feeds both sides:

- `functions/ml/econ_calendar.py` holds the seed lists, the impact tiers and the query helpers.
- `functions/ml/econ_calendar_us.csv` and `frontend/lib/backtest/newsCalendar.js` are generated
  from it (`python econ_calendar.py --write`); a test fails if either is stale.

## Using it

**JS backtester**

- *Exits → Flat for news*: off / high / medium+ / any, with minutes before and after. The engine
  closes at the close of the bar before the window, places no order that would be held into it,
  and lets the strategy re-enter after it. Trades it closes show exit reason `news`.
  In code: `risk.newsBlackout = { impact: 'high', beforeMin: 5, afterMin: 15 }`.
- *Rule builder → News*: a 0/1 "inside a news window" flag and minutes to next / since last event,
  e.g. `High-impact news window = 0` to keep a rule out of releases. Series keys:
  `news:high:5:15`, `newsNext:high`, `newsPrev:medium`.
- Prop mode: LucidDaily now applies its funded-account rule (flat 1 minute either side of
  high-impact USD news, per a third-party summary; Lucid's eval rule is unstated, so it is applied to
  the whole run). A blackout you set yourself wins over the firm's.

**Python studies**

```python
import econ_calendar as ec
ec.news_days("high")                                  # set of ET dates with high-impact news
ec.news_window(bars.index, 300, "high", 5, 15)        # bool per 5m bar: overlaps [event-5m, event+15m)
ec.minutes_to_next(bars.index, "medium")              # minutes to the next medium+ event
ec.events("high", sources=("official", "vintage"))    # only dates checked against a publisher list
```

## What's in it

| Tier | Events |
|---|---|
| high | CPI, nonfarm payrolls, FOMC decision (14:00) and press conference (14:30), FOMC minutes, PPI, retail sales, personal income & outlays (core PCE), GDP advance, ISM manufacturing, ISM services |
| medium | jobless claims, ADP, JOLTS, GDP second estimate, UMich sentiment preliminary |
| low | GDP third estimate, UMich final |

The tiers are ours, set to match FF's current USD tiers as closely as we know them; FF's own labels
have changed over the years, so this is not a replay of what FF showed on each day. Edit
`EVENTS` in `econ_calendar.py` to re-tier and regenerate.

Coverage starts 2022-01-01 and runs to `THROUGH[event]` (mostly 2026-10-16; CPI and FOMC extend to
their published 2027 schedules; ADP and UMich lag because ALFRED gets them late). Past coverage the
JS series are NaN and the Python helpers raise, so a run on newer bars never reads as "no news".

## Where the dates come from, and how sure we are

| source | events | check |
|---|---|---|
| official | CPI, NFP, PPI, JOLTS (bls.gov release archives), FOMC decisions and minutes (federalreserve.gov) | copied from the publisher |
| vintage | retail sales, PCE, GDP, ADP, UMich final (ALFRED release-date vintages) | revision-only dates removed by hand; CPI/NFP/PPI/JOLTS vintages agree with BLS |
| rule | jobless claims (Thursday, Wednesday on a holiday, none during the Oct 2025 shutdown) | matches every ALFRED claims date 2022-11 to 2026-10 |
| rule | ISM manufacturing (1st business day), ISM services (3rd) | **not verified**; ISM's calendar is behind a login |
| derived | UMich preliminary = the Friday two weeks before the final's week (so holiday-shifted finals keep a Friday preliminary) | **not verified** |

Times are each publisher's standard ET release time, except two BEA shutdown releases at 10:00
(bea.gov schedule notices). Why not ForexFactory itself: it has no API, its terms don't allow automated scraping as far as we can tell,
and its history mixes today's tiers with past relabelling.

Not included: Fed speeches and testimony, Jackson Hole, Conference Board confidence, durable goods,
Empire/Philly Fed, S&P flash PMIs, housing, EIA inventories, Treasury auctions, and anything
unscheduled. A clean "no news" bar means "nothing on this list", not "a quiet day".

## Caveats for research

- Using the schedule is not look-ahead: release dates are published months ahead. The exception is
  the 2025–26 shutdown, when catch-up dates were announced only weeks ahead.
- Filtering trades by news is one more knob. If you try blackout on/off, high vs medium, and several
  window widths on the same data, count each as a trial (deflated Sharpe, Bonferroni), exactly as
  for any other parameter, and pick the setting before touching held-out sessions.
- On RTH-only datasets (09:30–16:00) the 08:30 releases fall before the first bar; a blackout only
  bites on 10:00 and 14:00 events there. Futures/Globex data sees all of them.
