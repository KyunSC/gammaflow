"""E2_opex_week: trade ES 09:35 -> 15:55 by position relative to the monthly option expiration
(prereg/E2_opex_week.json). F = third Friday of today's month; W0 = F-4..F (long), W1 = F+3..F+7 (short).
window 'full_weeks': every session of W0 long, of W1 short. '3_sessions': the last 3 scheduled sessions of W0 long,
the first 3 of W1 short. Scheduled = weekday and not a published NYSE rule holiday (half days take a slot, never
traded). 1:1 bracket of k x ATR20 (mean of the last 20 hist true ranges) around the 09:30 bar close.

The sandbox has no datetime: dates are integer day numbers (days since 1970-01-01, Hinnant's civil algorithms) and
the NYSE holiday rule is a copy of research_loop_daily.eval.data.nyse_holidays (a test checks they agree)."""


def days_from_civil(y, m, d):
    y -= m <= 2
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def civil_from_days(z):
    z += 719468
    era = (z if z >= 0 else z - 146096) // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + (3 if mp < 10 else -9)
    return y + (m <= 2), m, d


def weekday(z):
    """Monday = 0 (1970-01-01 was a Thursday)."""
    return (z + 3) % 7


def nth_weekday(y, m, wd, n):
    z = days_from_civil(y, m, 1)
    return z + (wd - weekday(z)) % 7 + 7 * (n - 1)


def last_weekday(y, m, wd):
    z = days_from_civil(y + (m == 12), m % 12 + 1, 1) - 1
    return z - (weekday(z) - wd) % 7


def easter(y):
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mo = (h + l - 7 * m + 114) // 31
    return days_from_civil(y, mo, (h + l - 7 * m + 114) % 31 + 1)


def observed(z):
    w = weekday(z)
    return z - 1 if w == 5 else z + 1 if w == 6 else z


def nyse_holidays(y):
    out = {nth_weekday(y, 1, 0, 3), nth_weekday(y, 2, 0, 3), easter(y) - 2, last_weekday(y, 5, 0),
           observed(days_from_civil(y, 7, 4)), nth_weekday(y, 9, 0, 1), nth_weekday(y, 11, 3, 4),
           observed(days_from_civil(y, 12, 25))}
    ny = days_from_civil(y, 1, 1)
    if weekday(ny) != 5:
        out.add(observed(ny))
    if y >= 2022:
        out.add(observed(days_from_civil(y, 6, 19)))
    return out


def scheduled(z):
    return weekday(z) < 5 and z not in nyse_holidays(civil_from_days(z)[0])


def side_for(day_iso, window):
    """+1 / -1 / 0 for today's date string 'YYYY-MM-DD'."""
    y, m, d = int(day_iso[0:4]), int(day_iso[5:7]), int(day_iso[8:10])
    z = days_from_civil(y, m, d)
    F = nth_weekday(y, m, 4, 3)
    w0 = [F - i for i in range(4, -1, -1)]
    w1 = [F + i for i in range(3, 8)]
    if window == "full_weeks":
        return 1 if z in w0 else -1 if z in w1 else 0
    if window == "3_sessions":
        s0 = [x for x in w0 if scheduled(x)]
        s1 = [x for x in w1 if scheduled(x)]
        return 1 if z in s0[-3:] else -1 if z in s1[:3] else 0
    raise ValueError("unknown window")


def atr20(hist, atr_def):
    rows = hist[-20:]
    if len(rows) < 20:
        return None
    v = [r["tr"] if atr_def == "tr" else r["h"] - r["l"] for r in rows]
    if any(x is None for x in v):
        return None
    return sum(v) / 20.0


class Strategy:
    def __init__(self, params):
        self.p = params
        self.window = params["window"]

    def on_bar(self, bar, pos):
        if bar["slot"] != 0 or pos is not None or bar["half_day"]:
            return None
        side = side_for(bar["day"], self.window)
        if side == 0:
            return None
        atr = atr20(bar["hist"], self.p["atr_def"])
        if atr is None:
            return None
        risk = self.p["k"] * atr
        c = bar["c"]
        return {"op": "enter", "side": side, "type": "market", "stop": c - side * risk, "target": c + side * risk}
