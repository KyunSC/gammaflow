"""US economic news calendar for backtests: when scheduled releases land, and how much they matter.

ForexFactory's folders are the reference point: red = high impact, orange = medium, yellow = low.
ForexFactory has no API, its terms don't appear to allow scraping, and its historical impact
labels have moved over the years, so this calendar is built from the publishers' own schedules
instead and the tiers below are ours, chosen to match FF's current USD tiers as closely as we know
them. Edit EVENTS to re-tier an event; `python econ_calendar.py --write` regenerates both outputs.

Every event carries a `source`:
  official  copied from the publisher's release archive or published schedule (BLS, Fed, BEA)
  vintage   ALFRED release-date vintages (alfred.stlouisfed.org/release/downloaddates?rid=N),
            filtered to drop revision-only dates (annual benchmarks, seasonal-factor updates)
  rule      generated from the publisher's stated rule (claims every Thursday, ISM on the first and
            third business day); verified against ALFRED for claims, not verified for ISM
  derived   inferred from a related date (UMich preliminary = final - 14 days)
Studies that want only checked dates can pass `sources=("official", "vintage")`.

Times are the publisher's standard release time in ET. The 2025 shutdown catch-up releases kept
their standard times except where BEA said otherwise (TIME_OVERRIDES).

Coverage: each event type is complete through THROUGH[event]. Past that date the calendar does not
know whether news happened, so the queries below return "unknown" (NaN / raise) rather than
"no news". Re-collect the lists and bump THROUGH to extend it.

Knowing a release is scheduled is not look-ahead: these schedules are published months ahead.
The exception is the 2025-26 shutdown, when new dates were announced only weeks in advance.
Not covered at all: Fed speeches and testimony, Conference Board confidence, durable goods, Empire
and Philly Fed surveys, S&P flash PMIs, housing, EIA inventories, Treasury auctions, and anything
unscheduled (tariff headlines, geopolitics).

    python econ_calendar.py --list 2026-09        # print one month
    python econ_calendar.py --write               # regenerate the CSV and the frontend module
    python econ_calendar.py --check               # fail if the outputs are stale
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

ET = ZoneInfo("America/New_York")
HERE = Path(__file__).resolve().parent
CSV_PATH = HERE / "econ_calendar_us.csv"
JS_PATH = HERE.parent.parent / "frontend" / "lib" / "backtest" / "newsCalendar.js"
START = date(2022, 1, 1)
RETRIEVED = "2026-10-17"

IMPACT_RANK = {"low": 1, "medium": 2, "high": 3}

# event id -> (label, impact, standard ET time)
EVENTS = {
    "cpi":            ("CPI", "high", "08:30"),
    "nfp":            ("Nonfarm payrolls / unemployment rate", "high", "08:30"),
    "fomc":           ("FOMC statement / rate decision", "high", "14:00"),
    "fomc_presser":   ("FOMC press conference", "high", "14:30"),
    "fomc_minutes":   ("FOMC minutes", "high", "14:00"),
    "ppi":            ("PPI", "high", "08:30"),
    "retail_sales":   ("Retail sales", "high", "08:30"),
    "pce":            ("Personal income & outlays (core PCE)", "high", "08:30"),
    "gdp_advance":    ("GDP advance estimate", "high", "08:30"),
    "ism_mfg":        ("ISM manufacturing PMI", "high", "10:00"),
    "ism_services":   ("ISM services PMI", "high", "10:00"),
    "gdp_second":     ("GDP second estimate", "medium", "08:30"),
    "jolts":          ("JOLTS job openings", "medium", "10:00"),
    "adp":            ("ADP employment", "medium", "08:15"),
    "claims":         ("Initial jobless claims", "medium", "08:30"),
    "umich_prelim":   ("UMich sentiment (preliminary)", "medium", "10:00"),
    "gdp_third":      ("GDP third estimate", "low", "08:30"),
    "umich_final":    ("UMich sentiment (final)", "low", "10:00"),
}
IMPACT = {k: v[1] for k, v in EVENTS.items()}

# Last date each list is known complete. Lists were collected on RETRIEVED; ALFRED lags a few
# weeks for ADP and UMich. CPI and FOMC extend to their published future schedules.
THROUGH = {
    "cpi": "2027-12-31", "fomc": "2027-12-31", "fomc_presser": "2027-12-31",
    "nfp": "2026-10-16", "ppi": "2026-10-16", "jolts": "2026-10-16", "fomc_minutes": "2026-10-16",
    "retail_sales": "2026-10-16", "pce": "2026-10-16", "gdp_advance": "2026-10-16",
    "gdp_second": "2026-10-16", "gdp_third": "2026-10-16", "claims": "2026-10-16",
    "ism_mfg": "2026-10-16", "ism_services": "2026-10-16",
    "adp": "2026-09-29", "umich_prelim": "2026-08-28", "umich_final": "2026-08-28",
}

TIME_OVERRIDES = {  # BEA shutdown notices (bea.gov/news/blog?tid=1136)
    ("pce", "2025-12-05"): "10:00",
    ("pce", "2026-01-22"): "10:00",
}

# ---------------------------------------------------------------- seed lists


def _days(s: str) -> list[str]:
    return s.split()


# bls.gov/bls/news-release/cpi.htm and bls.gov/schedule/news_release/cpi.htm (future), plus
# 2022-01-12 (Dec 2021) from ALFRED rid=10.
CPI = _days("""
2022-01-12 2022-02-10 2022-03-10 2022-04-12 2022-05-11 2022-06-10 2022-07-13 2022-08-10 2022-09-13
2022-10-13 2022-11-10 2022-12-13 2023-01-12 2023-02-14 2023-03-14 2023-04-12 2023-05-10 2023-06-13
2023-07-12 2023-08-10 2023-09-13 2023-10-12 2023-11-14 2023-12-12 2024-01-11 2024-02-13 2024-03-12
2024-04-10 2024-05-15 2024-06-12 2024-07-11 2024-08-14 2024-09-11 2024-10-10 2024-11-13 2024-12-11
2025-01-15 2025-02-12 2025-03-12 2025-04-10 2025-05-13 2025-06-11 2025-07-15 2025-08-12 2025-09-11
2025-10-24 2025-12-18 2026-01-13 2026-02-13 2026-03-11 2026-04-10 2026-05-12 2026-06-10 2026-07-14
2026-08-12 2026-09-11 2026-10-14 2026-11-10 2026-12-10 2027-01-13 2027-02-11 2027-03-10 2027-04-13
2027-05-12 2027-06-10 2027-07-14 2027-08-11 2027-09-14 2027-10-14 2027-11-10 2027-12-10
""")

# bls.gov/bls/news-release/empsit.htm, plus 2022-01-07 (Dec 2021) from ALFRED rid=50.
NFP = _days("""
2022-01-07 2022-02-04 2022-03-04 2022-04-01 2022-05-06 2022-06-03 2022-07-08 2022-08-05 2022-09-02
2022-10-07 2022-11-04 2022-12-02 2023-01-06 2023-02-03 2023-03-10 2023-04-07 2023-05-05 2023-06-02
2023-07-07 2023-08-04 2023-09-01 2023-10-06 2023-11-03 2023-12-08 2024-01-05 2024-02-02 2024-03-08
2024-04-05 2024-05-03 2024-06-07 2024-07-05 2024-08-02 2024-09-06 2024-10-04 2024-11-01 2024-12-06
2025-01-10 2025-02-07 2025-03-07 2025-04-04 2025-05-02 2025-06-06 2025-07-03 2025-08-01 2025-09-05
2025-11-20 2025-12-16 2026-01-09 2026-02-11 2026-03-06 2026-04-03 2026-05-08 2026-06-05 2026-07-02
2026-08-07 2026-09-04 2026-10-02
""")

# bls.gov/bls/news-release/ppi.htm, plus 2022-01-13 (Dec 2021) from ALFRED rid=46.
PPI = _days("""
2022-01-13 2022-02-15 2022-03-15 2022-04-13 2022-05-12 2022-06-14 2022-07-14 2022-08-11 2022-09-14
2022-10-12 2022-11-15 2022-12-09 2023-01-18 2023-02-16 2023-03-15 2023-04-13 2023-05-11 2023-06-14
2023-07-13 2023-08-11 2023-09-14 2023-10-11 2023-11-15 2023-12-13 2024-01-12 2024-02-16 2024-03-14
2024-04-11 2024-05-14 2024-06-13 2024-07-12 2024-08-13 2024-09-12 2024-10-11 2024-11-14 2024-12-12
2025-01-14 2025-02-13 2025-03-13 2025-04-11 2025-05-15 2025-06-12 2025-07-16 2025-08-14 2025-09-10
2025-11-25 2026-01-14 2026-01-30 2026-02-27 2026-03-18 2026-04-14 2026-05-13 2026-06-11 2026-07-15
2026-08-13 2026-09-10 2026-10-15
""")

# bls.gov/bls/news-release/jolts.htm, plus 2022-01-04 and 2022-02-01 from ALFRED rid=192.
JOLTS = _days("""
2022-01-04 2022-02-01 2022-03-09 2022-03-29 2022-05-03 2022-06-01 2022-07-06 2022-08-02 2022-08-30
2022-10-04 2022-11-01 2022-11-30 2023-01-04 2023-02-01 2023-03-08 2023-04-04 2023-05-02 2023-05-31
2023-07-06 2023-08-01 2023-08-29 2023-10-03 2023-11-01 2023-12-05 2024-01-03 2024-01-30 2024-03-06
2024-04-02 2024-05-01 2024-06-04 2024-07-02 2024-07-30 2024-09-04 2024-10-01 2024-10-29 2024-12-03
2025-01-07 2025-02-04 2025-03-11 2025-04-01 2025-04-29 2025-06-03 2025-07-01 2025-07-29 2025-09-03
2025-09-30 2025-12-09 2026-01-07 2026-02-05 2026-03-13 2026-03-31 2026-05-05 2026-06-02 2026-06-30
2026-08-04 2026-09-01 2026-09-29
""")

# federalreserve.gov/monetarypolicy/fomccalendars.htm: decision day (the meeting's last day) and
# minutes release day. Every meeting since 2019 has a 14:30 press conference.
FOMC = _days("""
2022-01-26 2022-03-16 2022-05-04 2022-06-15 2022-07-27 2022-09-21 2022-11-02 2022-12-14
2023-02-01 2023-03-22 2023-05-03 2023-06-14 2023-07-26 2023-09-20 2023-11-01 2023-12-13
2024-01-31 2024-03-20 2024-05-01 2024-06-12 2024-07-31 2024-09-18 2024-11-07 2024-12-18
2025-01-29 2025-03-19 2025-05-07 2025-06-18 2025-07-30 2025-09-17 2025-10-29 2025-12-10
2026-01-28 2026-03-18 2026-04-29 2026-06-17 2026-07-29 2026-09-16 2026-10-28 2026-12-09
2027-01-27 2027-03-17 2027-04-28 2027-06-09 2027-07-28 2027-09-15 2027-10-27 2027-12-08
""")
FOMC_MINUTES = _days("""
2022-01-05 2022-02-16 2022-04-06 2022-05-25 2022-07-06 2022-08-17 2022-10-12 2022-11-23
2023-01-04 2023-02-22 2023-04-12 2023-05-24 2023-07-05 2023-08-16 2023-10-11 2023-11-21
2024-01-03 2024-02-21 2024-04-10 2024-05-22 2024-07-03 2024-08-21 2024-10-09 2024-11-26
2025-01-08 2025-02-19 2025-04-09 2025-05-28 2025-07-09 2025-08-20 2025-10-08 2025-11-19
2025-12-30 2026-02-18 2026-04-08 2026-05-20 2026-07-08 2026-08-19 2026-10-07
""")

# ALFRED rid=9, dropping the annual-revision dates (2022-04-25, 2023-04-24, 2024-04-23,
# 2025-04-25, 2026-09-28; census.gov/retail/mrts/historic_releases.html).
RETAIL = _days("""
2022-01-14 2022-02-16 2022-03-16 2022-04-14 2022-05-17 2022-06-15 2022-07-15 2022-08-17 2022-09-15
2022-10-14 2022-11-16 2022-12-15 2023-01-18 2023-02-15 2023-03-15 2023-04-14 2023-05-16 2023-06-15
2023-07-18 2023-08-15 2023-09-14 2023-10-17 2023-11-15 2023-12-14 2024-01-17 2024-02-15 2024-03-14
2024-04-15 2024-05-15 2024-06-18 2024-07-16 2024-08-15 2024-09-17 2024-10-17 2024-11-15 2024-12-17
2025-01-16 2025-02-14 2025-03-17 2025-04-16 2025-05-15 2025-06-17 2025-07-17 2025-08-15 2025-09-16
2025-11-25 2025-12-16 2026-01-14 2026-02-10 2026-03-06 2026-04-01 2026-04-21 2026-05-14 2026-06-17
2026-07-16 2026-08-14 2026-09-16 2026-10-15
""")

# ALFRED rid=54. From 2026 BEA publishes it with GDP ("Same Time as GDP", BEA blog Feb 2026).
PCE = _days("""
2022-01-28 2022-02-25 2022-03-31 2022-04-29 2022-05-27 2022-06-30 2022-07-29 2022-08-26 2022-09-30
2022-10-28 2022-12-01 2022-12-23 2023-01-27 2023-02-24 2023-03-31 2023-04-28 2023-05-26 2023-06-30
2023-07-28 2023-08-31 2023-09-29 2023-10-27 2023-11-30 2023-12-22 2024-01-26 2024-02-29 2024-03-29
2024-04-26 2024-05-31 2024-06-28 2024-07-26 2024-08-30 2024-09-27 2024-10-31 2024-11-27 2024-12-20
2025-01-31 2025-02-28 2025-03-28 2025-04-30 2025-05-30 2025-06-27 2025-07-31 2025-08-29 2025-09-26
2025-12-05 2025-12-23 2026-01-22 2026-02-20 2026-03-13 2026-04-09 2026-04-30 2026-05-28 2026-06-25
2026-07-30 2026-08-26 2026-09-30
""")

# ALFRED rid=53 with the estimate each date carried (A advance, S second, T third), dropping
# 2022-10-06, 2023-11-17 and 2024-10-02, which are not headline GDP releases. The Q3 2025
# advance was cancelled; its Dec 23 "initial" estimate counts as the advance and the Jan 22
# "updated" estimate as the second.
GDP = """
2022-01-27 A 2022-02-24 S 2022-03-30 T 2022-04-28 A 2022-05-26 S 2022-06-29 T 2022-07-28 A 2022-08-25 S
2022-09-29 T 2022-10-27 A 2022-11-30 S 2022-12-22 T 2023-01-26 A 2023-02-23 S 2023-03-30 T 2023-04-27 A
2023-05-25 S 2023-06-29 T 2023-07-27 A 2023-08-30 S 2023-09-28 T 2023-10-26 A 2023-11-29 S 2023-12-21 T
2024-01-25 A 2024-02-28 S 2024-03-28 T 2024-04-25 A 2024-05-30 S 2024-06-27 T 2024-07-25 A 2024-08-29 S
2024-09-26 T 2024-10-30 A 2024-11-27 S 2024-12-19 T 2025-01-30 A 2025-02-27 S 2025-03-27 T 2025-04-30 A
2025-05-29 S 2025-06-26 T 2025-07-30 A 2025-08-28 S 2025-09-25 T 2025-12-23 A 2026-01-22 S 2026-02-20 A
2026-03-13 S 2026-04-09 T 2026-04-30 A 2026-05-28 S 2026-06-25 T 2026-07-30 A 2026-08-26 S 2026-09-30 T
""".split()
GDP_STAGE = {"A": "gdp_advance", "S": "gdp_second", "T": "gdp_third"}

# ALFRED rid=194. ADP skipped June-August 2022 while it rebuilt its methodology.
ADP = _days("""
2022-01-05 2022-02-02 2022-03-02 2022-03-30 2022-05-04 2022-06-02 2022-08-31 2022-10-05 2022-11-02
2022-11-30 2023-01-05 2023-02-01 2023-03-08 2023-04-05 2023-05-03 2023-06-01 2023-07-06 2023-08-02
2023-08-30 2023-10-04 2023-11-01 2023-12-06 2024-01-04 2024-01-31 2024-03-06 2024-04-03 2024-05-01
2024-06-05 2024-07-03 2024-07-31 2024-09-05 2024-10-02 2024-10-30 2024-12-04 2025-01-08 2025-02-05
2025-03-05 2025-04-02 2025-04-30 2025-06-04 2025-07-02 2025-07-30 2025-09-04 2025-10-01 2025-11-05
2025-12-03 2026-01-07 2026-02-04 2026-03-04 2026-04-01 2026-05-06 2026-06-03 2026-07-01 2026-08-05
2026-09-02
""")

# ALFRED rid=91 lists the final reading only (FRED receives UMich data late).
UMICH_FINAL = _days("""
2022-01-28 2022-02-25 2022-03-25 2022-04-29 2022-05-27 2022-06-24 2022-07-29 2022-08-26 2022-09-30
2022-10-28 2022-11-23 2022-12-23 2023-01-27 2023-02-24 2023-03-31 2023-04-28 2023-05-26 2023-06-30
2023-07-28 2023-08-25 2023-09-29 2023-10-27 2023-11-22 2023-12-22 2024-02-02 2024-03-01 2024-03-28
2024-04-26 2024-05-24 2024-06-28 2024-07-26 2024-08-30 2024-09-27 2024-10-25 2024-11-22 2024-12-20
2025-01-24 2025-02-21 2025-03-28 2025-04-25 2025-05-30 2025-06-27 2025-08-01 2025-08-29 2025-09-26
2025-10-24 2025-11-21 2025-12-19 2026-01-23 2026-02-20 2026-03-27 2026-04-24 2026-05-22 2026-06-26
2026-07-31 2026-08-28
""")

# DOL skipped the national claims report during the Oct 1 - Nov 12 2025 shutdown (absent from
# ALFRED rid=180), and moved it to Wednesday for the Jan 9 2025 national day of mourning.
CLAIMS_SKIPPED = (date(2025, 10, 2), date(2025, 11, 13))
CLAIMS_MOVED = {date(2025, 1, 9): date(2025, 1, 8)}


# ---------------------------------------------------------------- holiday + business-day rules


def _nth_weekday(y: int, m: int, weekday: int, n: int) -> date:
    d = date(y, m, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(y: int, m: int, weekday: int) -> date:
    d = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: date) -> date:
    return d - timedelta(days=1) if d.weekday() == 5 else d + timedelta(days=1) if d.weekday() == 6 else d


def federal_holidays(y: int) -> dict[date, date]:
    """Actual date -> observed date for each US federal holiday in year y."""
    fixed = [date(y, 1, 1), date(y, 6, 19), date(y, 7, 4), date(y, 11, 11), date(y, 12, 25)]
    floating = [_nth_weekday(y, 1, 0, 3), _nth_weekday(y, 2, 0, 3), _last_weekday(y, 5, 0),
                _nth_weekday(y, 9, 0, 1), _nth_weekday(y, 10, 0, 2), _nth_weekday(y, 11, 3, 4)]
    return {d: _observed(d) for d in fixed} | {d: d for d in floating}


def _observed_set(years) -> set[date]:
    return {o for y in years for o in federal_holidays(y).values()}


def business_days(y: int, m: int, holidays: set[date]) -> list[date]:
    d, out = date(y, m, 1), []
    while d.month == m:
        if d.weekday() < 5 and d not in holidays:
            out.append(d)
        d += timedelta(days=1)
    return out


def claims_days(start: date, end: date) -> list[date]:
    """Thursdays, or the Wednesday before when Thursday is a federal holiday."""
    hol = {d for y in range(start.year - 1, end.year + 2) for d in federal_holidays(y)}
    d = start + timedelta(days=(3 - start.weekday()) % 7)
    out = []
    while d <= end:
        if not (CLAIMS_SKIPPED[0] <= d <= CLAIMS_SKIPPED[1]):
            out.append(CLAIMS_MOVED.get(d, d - timedelta(days=1) if d in hol else d))
        d += timedelta(weeks=1)
    return out


# ---------------------------------------------------------------- build


@dataclass(frozen=True)
class Event:
    day: date
    time_et: str
    event: str
    source: str

    @property
    def impact(self) -> str:
        return IMPACT[self.event]

    @property
    def ts(self) -> int:
        h, m = map(int, self.time_et.split(":"))
        return int(datetime(self.day.year, self.day.month, self.day.day, h, m, tzinfo=ET).timestamp())


def _through(event: str) -> date:
    return date.fromisoformat(THROUGH[event])


def _cover_end(event: str) -> int:
    """Epoch seconds of midnight ET after THROUGH[event]: times from here on are not covered."""
    d = _through(event) + timedelta(days=1)
    return int(datetime(d.year, d.month, d.day, tzinfo=ET).timestamp())


def build_events() -> list[Event]:
    rows: list[tuple[str, str, str]] = []
    official = [("cpi", CPI), ("nfp", NFP), ("ppi", PPI), ("jolts", JOLTS), ("fomc", FOMC),
                ("fomc_presser", FOMC), ("fomc_minutes", FOMC_MINUTES)]
    vintage = [("retail_sales", RETAIL), ("pce", PCE), ("adp", ADP), ("umich_final", UMICH_FINAL)]
    rows += [(d, ev, "official") for ev, days in official for d in days]
    rows += [(d, ev, "vintage") for ev, days in vintage for d in days]
    rows += [(GDP[i], GDP_STAGE[GDP[i + 1]], "vintage") for i in range(0, len(GDP), 2)]
    rows += [((date.fromisoformat(d) - timedelta(days=14)).isoformat(), "umich_prelim", "derived")
             for d in UMICH_FINAL]

    end = max(_through(e) for e in ("claims", "ism_mfg", "ism_services"))
    rows += [(d.isoformat(), "claims", "rule") for d in claims_days(START, _through("claims"))]
    years = range(START.year, end.year + 1)
    hol = _observed_set(years)
    for y in years:
        for m in range(1, 13):
            bd = business_days(y, m, hol)
            for ev, k in (("ism_mfg", 0), ("ism_services", 2)):
                if bd[k] <= _through(ev):
                    rows.append((bd[k].isoformat(), ev, "rule"))

    out = []
    for d, ev, src in rows:
        day = date.fromisoformat(d)
        if day < START or day > _through(ev):
            continue
        out.append(Event(day, TIME_OVERRIDES.get((ev, d), EVENTS[ev][2]), ev, src))
    return sorted(out, key=lambda e: (e.ts, -IMPACT_RANK[e.impact], e.event))


def to_csv(events: list[Event]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["date", "time_et", "ts_utc", "event", "label", "impact", "source"])
    for e in events:
        w.writerow([e.day.isoformat(), e.time_et, e.ts, e.event, EVENTS[e.event][0], e.impact, e.source])
    return buf.getvalue()


def to_js(events: list[Event]) -> str:
    meta = {k: {"label": v[0], "impact": v[1], "time": v[2], "through": THROUGH[k], "coverEnd": _cover_end(k)}
            for k, v in EVENTS.items()}
    rows = ",\n".join(f"  [{e.ts}, {json.dumps(e.event)}, {json.dumps(e.source)}]" for e in events)
    return (
        "// Generated by functions/ml/econ_calendar.py --write. Do not edit by hand: edit the\n"
        "// seed lists or tiers there and regenerate, so the Python studies and the JS backtester\n"
        "// read the same calendar.\n\n"
        f"export const RETRIEVED = {json.dumps(RETRIEVED)}\n\n"
        f"export const EVENT_TYPES = {json.dumps(meta, indent=2)}\n\n"
        "/** [epoch seconds UTC, event type, source], sorted by time. */\n"
        f"export const EVENTS = [\n{rows},\n]\n"
    )


# ---------------------------------------------------------------- queries

_CACHE: list[Event] | None = None


def events(min_impact: str = "medium", sources=None, types=None) -> list[Event]:
    """Events at or above `min_impact`, optionally restricted to some sources or event types."""
    global _CACHE
    if _CACHE is None:
        _CACHE = build_events()
    rank = IMPACT_RANK[min_impact]
    return [e for e in _CACHE if IMPACT_RANK[e.impact] >= rank
            and (sources is None or e.source in sources) and (types is None or e.event in types)]


def covered_through(min_impact: str = "medium", types=None) -> date:
    """Last date on which every selected event type is known complete."""
    rank = IMPACT_RANK[min_impact]
    sel = [k for k in EVENTS if IMPACT_RANK[IMPACT[k]] >= rank and (types is None or k in types)]
    return min(_through(k) for k in sel)


def news_days(min_impact: str = "high", **kw) -> set[date]:
    """ET dates with at least one selected event."""
    return {e.day for e in events(min_impact, **kw)}


def _epoch(times) -> np.ndarray:
    """Epoch seconds from pandas timestamps, datetimes or numbers."""
    arr = np.asarray(times)
    if np.issubdtype(arr.dtype, np.datetime64):
        return arr.astype("datetime64[s]").astype(np.int64)
    if arr.dtype == object:
        return np.array([int(t.timestamp()) for t in arr], dtype=np.int64)
    return arr.astype(np.int64)


def _check_coverage(t: np.ndarray, min_impact: str, types, allow_uncovered: bool) -> np.ndarray:
    rank = IMPACT_RANK[min_impact]
    end = min(_cover_end(k) for k in EVENTS if IMPACT_RANK[IMPACT[k]] >= rank and (types is None or k in types))
    beyond = t >= end
    if beyond.any() and not allow_uncovered:
        raise ValueError(f"{int(beyond.sum())} bars fall after the calendar's coverage "
                         f"({covered_through(min_impact, types)}); extend the seed lists or pass allow_uncovered=True")
    return beyond


def news_window(bar_start, bar_seconds: int, min_impact: str = "high", before_min: float = 5,
                after_min: float = 15, allow_uncovered: bool = False, **kw) -> np.ndarray:
    """True for bars whose span [start, start + bar_seconds) overlaps any selected event's window
    [event - before_min, event + after_min). Bars past coverage are False when allowed."""
    t = _epoch(bar_start)
    beyond = _check_coverage(t, min_impact, kw.get("types"), allow_uncovered)
    ev = np.array(sorted(e.ts for e in events(min_impact, **kw)), dtype=np.int64)
    lo, hi = ev - int(before_min * 60), ev + max(int(after_min * 60), 1)   # 0/0 = the bar it prints in
    # first window ending after the bar starts; it overlaps if it also starts before the bar ends
    j = np.searchsorted(hi, t, side="right")
    ok = j < len(ev)
    out = np.zeros(len(t), dtype=bool)
    out[ok] = lo[j[ok]] < t[ok] + bar_seconds
    return out & ~beyond


def minutes_to_next(at, min_impact: str = "high", allow_uncovered: bool = False, **kw) -> np.ndarray:
    """Minutes from each time to the next selected event strictly after it (NaN if none known)."""
    t = _epoch(at)
    beyond = _check_coverage(t, min_impact, kw.get("types"), allow_uncovered)
    ev = np.array(sorted(e.ts for e in events(min_impact, **kw)), dtype=np.int64)
    j = np.searchsorted(ev, t, side="right")
    out = np.full(len(t), np.nan)
    ok = j < len(ev)
    out[ok] = (ev[j[ok]] - t[ok]) / 60
    out[beyond] = np.nan
    return out


def minutes_since(at, min_impact: str = "high", allow_uncovered: bool = False, **kw) -> np.ndarray:
    """Minutes since the latest selected event at or before each time (NaN if none)."""
    t = _epoch(at)
    beyond = _check_coverage(t, min_impact, kw.get("types"), allow_uncovered)
    ev = np.array(sorted(e.ts for e in events(min_impact, **kw)), dtype=np.int64)
    j = np.searchsorted(ev, t, side="right") - 1
    out = np.full(len(t), np.nan)
    ok = j >= 0
    out[ok] = (t[ok] - ev[j[ok]]) / 60
    out[beyond] = np.nan
    return out


# ---------------------------------------------------------------- CLI


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true", help="regenerate the CSV and the frontend module")
    ap.add_argument("--check", action="store_true", help="exit 1 if the generated files are stale")
    ap.add_argument("--list", metavar="YYYY-MM", help="print one month of events")
    a = ap.parse_args(argv)
    evs = build_events()
    outputs = {CSV_PATH: to_csv(evs), JS_PATH: to_js(evs)}
    if a.write:
        for p, text in outputs.items():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
            print(f"wrote {p.relative_to(HERE.parent.parent)}")
    if a.check:
        stale = [p for p, text in outputs.items() if not p.exists() or p.read_text() != text]
        for p in stale:
            print(f"stale: {p}; run python econ_calendar.py --write", file=sys.stderr)
        if stale:
            return 1
    if a.list:
        for e in evs:
            if e.day.isoformat().startswith(a.list):
                print(f"{e.day} {e.time_et}  {e.impact:<6} {EVENTS[e.event][0]}  [{e.source}]")
    if not (a.write or a.check or a.list):
        by = {k: sum(e.impact == k for e in evs) for k in IMPACT_RANK}
        print(f"{len(evs)} events {evs[0].day} -> {evs[-1].day}: {by}; high-impact coverage through "
              f"{covered_through('high')}, medium through {covered_through('medium')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
