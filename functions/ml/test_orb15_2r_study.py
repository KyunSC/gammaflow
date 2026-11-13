from datetime import date

import numpy as np

import orb15_2r_study as s


def make_day(path_after, orh=110.0, orl=100.0):
    """15 range bars inside [orl, orh], then 1m bars with the given (o, h, l, c) from 09:45."""
    rng = [(105, orh, orl, 105)] + [(105, 106, 104, 105)] * 14
    bars = rng + list(path_after)
    m = np.arange(570, 570 + len(bars))
    a = np.array(bars, float)
    return s.Day(date(2024, 1, 2), m, a[:, 0], a[:, 1], a[:, 2], a[:, 3], orh, orl)


def flat(px, n):
    return [(px, px + 0.5, px - 0.5, px)] * n


def test_long_hits_2r_target():
    # 5m candle 09:45-09:49 closes 111 > 110 -> entry at 09:50 open 111 + tick; R = 11.25, target 133.75
    day = make_day(flat(111, 5) + [(111, 112, 110.5, 111.5)] + [(120, 134.5, 119, 134)] + flat(134, 10))
    t = s.run_day(day, 5, "none", [])
    assert t["dir"] == 1 and t["why"] == "target" and t["entry_m"] == 590
    assert abs(t["R"] - 11.25) < 1e-9 and abs(t["pts"] - 22.5) < 1e-9


def test_stop_at_range_low_with_slip():
    day = make_day(flat(111, 5) + [(111, 111.5, 105, 106), (106, 106, 99, 99.5)] + flat(99, 5))
    t = s.run_day(day, 5, "none", [])
    assert t["why"] == "stop" and abs(t["pts"] - (100 - 0.25 - 111.25)) < 1e-9


def test_short_mirror():
    day = make_day(flat(99, 5) + flat(99, 3) + [(95, 96, 76, 77)] + flat(77, 5))
    t = s.run_day(day, 5, "none", [])
    assert t["dir"] == -1 and t["why"] == "target"


def test_blackout_skips_candle_and_flattens_before_news():
    # event at 10:00: entries 09:30-10:15 blocked, so the 09:50 entry is skipped; a later entry is taken
    path = flat(111, 50) + flat(112, 200)
    day = make_day(path)
    t = s.run_day(day, 5, "blackout", [600])
    assert t["entry_m"] > 615
    t2 = s.run_day(day, 5, "blackout", [14 * 60])  # 14:00 FOMC after entry -> flat at the 13:54 close
    assert t2["entry_m"] == 590 and t2["why"] == "news" and t2["held"] == 13 * 60 + 54 - 590 + 1


def test_skip_day_and_no_signal():
    day = make_day(flat(105, 100))
    assert s.run_day(day, 5, "none", []) is None
    day = make_day(flat(111, 30))
    assert s.run_day(day, 5, "skip_day", [510]) is None


def test_pre2022_calendar_times():
    ev = s.pre2022_rth_events()
    assert ev[date(2011, 4, 27)] == [750, 855]          # 12:30 statement, 14:15 presser
    assert ev[date(2011, 3, 15)] == [855]                # 14:15, no presser
    assert ev[date(2015, 3, 18)] == [840, 870]           # 14:00, 14:30
    assert ev[date(2020, 3, 3)] == [600, 660]
    assert 840 in ev[date(2020, 4, 8)]                   # minutes of the unscheduled 2020-03-15 meeting
    assert ev[date(2019, 7, 1)] == [600]                 # ISM manufacturing, 1st business day
