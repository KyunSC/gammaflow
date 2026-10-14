"""Offline checks for orderflow_backtest on synthetic prints."""
import unittest

import numpy as np

import orderflow_backtest as ob

DATE = "2026-07-07"


def day_from(rows):
    """rows: (seconds after 09:30 ET, price, size, side)."""
    a = np.array(rows, float)
    open_ns = ob.pd.Timestamp(f"{DATE} 09:30", tz=ob.ET).value
    return ob.build_day(DATE, 1, (open_ns + a[:, 0] * 1e9).astype(np.int64), a[:, 1], a[:, 2],
                        a[:, 3].astype(np.int8))


def short_setup(after):
    """Rally 19980 -> 20000 into a 20000 LVN, an 80-lot buy bubble there at 09:40, a drop
    to 19985 held through 09:42, then the `after` rows (from 09:42:01)."""
    rows = [(s, 19980 + 20 * s / 600, 1, 1) for s in range(0, 600)]
    rows += [(600, 20000.0, 50, 1), (600, 20000.5, 30, 1)]  # one aggressor order, two prices
    rows += [(601 + k, 19985.0, 1, -1) for k in range(120)]
    rows += list(after)
    return day_from(rows)


STATICS = [("lvn", 20000.0), ("pdl", 19950.0)]


class OrderflowTests(unittest.TestCase):
    def test_aggregates_one_sweep(self):
        ts = np.array([1, 1, 1, 2, 2])
        start, end, size, lo, hi, side = ob.aggregate_orders(
            ts, np.array([10, 10.25, 10.5, 10.5, 10.5]), np.array([5, 5, 5, 1, 2.0]), np.array([1, 1, 1, 1, -1]))
        self.assertEqual(list(size), [15, 1, 2])
        self.assertEqual((lo[0], hi[0], list(side)), (10, 10.5, [1, 1, -1]))

    def test_lvn_between_two_nodes(self):
        px = np.r_[np.full(1000, 100.0), np.full(20, 150.0), np.full(1000, 200.0)]
        px = px + np.random.default_rng(0).normal(0, 8, len(px))
        lv = ob.low_volume_nodes(px, np.ones(len(px)))
        self.assertTrue(any(125 < x < 175 for x in lv), lv)

    def test_short_absorption_hits_target(self):
        day = short_setup([(721 + k, 19985 - k, 1, -1) for k in range(60)])
        (tr,) = ob.run_day(day, STATICS, ob.Params())
        self.assertEqual((tr["direction"], tr["level_kind"], tr["exit_reason"]), (-1, "lvn", "target"))
        self.assertEqual(tr["entry"], 19984.75)  # first print after the 09:41 minute closes below 20000, 1 tick worse
        self.assertEqual(tr["stop"], 20001.0)  # bubble high + 2 ticks
        self.assertEqual(tr["target"], 19950.0)
        self.assertAlmostEqual(tr["r"], (34.75 - ob.COMMISSION_PTS) / 16.25)

    def test_short_stopped_out(self):
        day = short_setup([(721 + k, 19985 + k, 1, 1) for k in range(30)])
        (tr,) = ob.run_day(day, STATICS, ob.Params())
        self.assertEqual(tr["exit_reason"], "stop")
        self.assertLess(tr["r"], -1)

    def test_with_flow_control_ignores_absorption(self):
        day = short_setup([(721 + k, 19985 - k, 1, -1) for k in range(60)])
        self.assertEqual(ob.run_day(day, STATICS, ob.Params(trigger="with_flow")), [])

    def test_bubble_too_small(self):
        day = short_setup([(721 + k, 19985 - k, 1, -1) for k in range(60)])
        self.assertEqual(ob.run_day(day, STATICS, ob.Params(bubble_size=100)), [])

    def test_skip_when_target_under_1r(self):
        day = short_setup([(721 + k, 19985 - k, 1, -1) for k in range(60)])
        self.assertEqual(ob.run_day(day, [("lvn", 20000.0), ("pdl", 19980.0)], ob.Params()), [])

    def test_prior_levels_dropped_on_roll(self):
        prev = ob.Session(instrument=2, high=1.0, low=0.0, lvns=[0.5])
        self.assertEqual(ob.static_levels(prev, short_setup([])), [])


PREV = ob.Session(instrument=1, high=20100.0, low=19900.0, lvns=[], vol_per_min=100.0)
ABSORB = ob.Params("absorb_vol", window_s=30, absorb_mult=1.0, leak=1)  # needs 50 lots in 30 s


def absorbed_setup(lots=10):
    """Rally 19980 -> 20000 into the 20000 LVN, then 09:40-09:41 buyers lift `lots` a second
    at 20000 without moving it, then sellers take it to 19985 and on down to 19940."""
    rows = [(s, 19980 + 20 * s / 600, 1, 1) for s in range(0, 600)]
    rows += [(600 + k, 20000.0, lots, 1) for k in range(60)]
    rows += [(660 + k, 19985.0, 1, -1) for k in range(120)]
    rows += [(780 + k, 19985 - k, 1, -1) for k in range(60)]
    return day_from(rows)


class AbsorptionTests(unittest.TestCase):
    def test_absorbed_buying_shorts(self):
        (tr,) = ob.run_day(absorbed_setup(), STATICS, ABSORB, PREV)
        self.assertEqual((tr["direction"], tr["level_kind"], tr["exit_reason"]), (-1, "lvn", "target"))
        # Not 09:40:05 (50 lots by then): the high must first hold within a tick of the
        # previous 30 s high, which the rally only reaches by 09:39:53.
        self.assertEqual(tr["trigger_time"], "09:40:24")
        self.assertEqual(tr["entry"], 19984.75)  # first print after 09:41 closes below 19999.75
        self.assertEqual(tr["stop"], 20000.5)  # window high + 2 ticks
        self.assertEqual(tr["target"], 19950.0)

    def test_effort_below_threshold(self):
        self.assertEqual(ob.run_day(absorbed_setup(lots=1), STATICS, ABSORB, PREV), [])

    def test_buying_that_moves_price_is_push_not_absorption(self):
        rows = [(s, 19980 + 10 * s / 600, 1, 1) for s in range(0, 600)]  # rally to 19990
        rows += [(600 + k, 19995 + 0.5 * k, 60, 1) for k in range(30)]  # 60 lots/s, 2 ticks/s up
        rows += [(630 + k, 19985.0, 1, -1) for k in range(150)]
        rows += [(780 + k, 19985 - k, 1, -1) for k in range(60)]
        day = day_from(rows)
        self.assertEqual(ob.run_day(day, STATICS, ABSORB, PREV), [])
        (tr,) = ob.run_day(day, STATICS, ob.replace(ABSORB, trigger="push"), PREV)
        # 09:40:04 prints 60 lots at 19997, within the 3-pt tolerance of 20000.
        self.assertEqual((tr["direction"], tr["level"], tr["trigger_time"]), (-1, 20000.0, "09:40:05"))
        self.assertEqual(tr["stop"], 20010.0)  # the push's high + 2 ticks

    def test_range_units_scale_points(self):
        prev = ob.replace(PREV, high=19900 + 2 * ob.REF_RANGE)
        p, k = ob.scale(ob.Params(units="range", level_tol=3.0, min_stop=4.0, max_stop=30.0),
                        prev, absorbed_setup())
        self.assertEqual((k, p.level_tol, p.min_stop, p.max_stop), (2.0, 6.0, 8.0, 60.0))
        self.assertEqual(p.name, "absorb/b60/tol6/nofp")  # run_day keeps the unscaled name
        self.assertEqual(ob.run_day(absorbed_setup(), STATICS, ob.replace(ABSORB, units="range")), [])


def gex_day(net, day=None):
    """absorbed_setup with one QQQ snapshot at 09:30: NQ 19980 / QQQ 499.5 = 40x, so the 500
    call wall is NQ 20000 and the 490 put wall NQ 19600; zero gamma missing."""
    day = day or absorbed_setup()
    snaps = ob.pd.DataFrame(dict(computed_at=[ob.pd.Timestamp(f"{DATE} 09:30", tz=ob.ET).tz_convert("UTC")],
                                 spot=[499.5], call_wall=[500.0], put_wall=[490.0], zero_gamma=[np.nan],
                                 net_gex=[net], date=[DATE]))
    ob.attach_gex(day, snaps)
    return day


GEX_ABSORB = ob.replace(ABSORB, gex_levels=True, regime="neg")


class GexTests(unittest.TestCase):
    def test_conversion_lag_and_staleness(self):
        day = gex_day(-1.0)
        comp = day.gex["comp"][0]
        lv, net = ob.gex_at(day, [comp + 30 * ob.SEC_NS, comp + 61 * ob.SEC_NS, comp + 21 * ob.MIN_NS])
        self.assertTrue(np.isnan(lv[0]).all() and np.isnan(net[0]))  # not usable for a minute
        self.assertEqual(list(lv[1][:2]), [20000.0, 19600.0])
        self.assertTrue(np.isnan(lv[1][2]))  # missing zero gamma stays missing
        self.assertTrue(np.isnan(net[2]))  # more than 20 min old

    def test_absorption_at_gex_call_wall(self):
        statics = [("pdl", 19950.0)]  # no static level at 20000: only the call wall is there
        self.assertEqual(ob.run_day(gex_day(-1.0), statics, ob.replace(ABSORB), PREV), [])
        (tr,) = ob.run_day(gex_day(-1.0), statics, GEX_ABSORB, PREV)
        self.assertEqual((tr["direction"], tr["level_kind"], tr["level"]), (-1, "call_wall", 20000.0))
        self.assertEqual(tr["target"], 19950.0)
        self.assertTrue(tr["cell"].endswith("/gexL/neg"))

    def test_regime_filter(self):
        statics = [("pdl", 19950.0)]
        self.assertEqual(ob.run_day(gex_day(+1.0), statics, GEX_ABSORB, PREV), [])
        self.assertEqual(len(ob.run_day(gex_day(+1.0), statics, ob.replace(GEX_ABSORB, regime="pos"), PREV)), 1)
        day = absorbed_setup()  # no snapshots at all: no regime, no trade
        self.assertEqual(ob.run_day(day, STATICS, ob.replace(ABSORB, regime="neg"), PREV), [])


class PreregistrationTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.dir = ob.Path(tempfile.mkdtemp())
        self.nq = self.dir / "absorb_NQ" / "report.json"
        self.nq.parent.mkdir()
        self.es = self.dir / "absorb_ES"

    def write_nq(self, sha):
        self.nq.write_text(ob.json.dumps(dict(selected=ABSORB.name, code_sha=sha,
                                              selected_params=ob.asdict(ABSORB))))

    def test_refuses_changed_code(self):
        self.write_nq("0" * 64)
        self.assertEqual(ob.absorb_verify([], self.es, self.nq, 50.0), 1)
        self.assertFalse((self.es / "preregistered.json").exists())

    def test_refuses_second_look(self):
        self.write_nq(ob.code_sha())
        self.es.mkdir()
        (self.es / "preregistered.json").write_text("{}")
        self.assertEqual(ob.absorb_verify([], self.es, self.nq, 50.0), 1)

    def gex_args(self, **kw):
        import argparse
        (self.dir / "data").mkdir(exist_ok=True)
        return argparse.Namespace(**dict(dict(smoke=False, freeze=False, data=self.dir / "data"), **kw))

    def test_gex_freeze_refused_once_test_data_exists(self):
        args = self.gex_args(freeze=True)
        (args.data / f"{ob.TEST_START}_2025-10-25.request.json").write_text("{}")
        self.assertEqual(ob.gex_main(args, self.dir / "gex_NQ"), 1)
        self.assertFalse((self.dir / "gex_NQ" / "freeze.json").exists())

    def test_gex_run_needs_freeze_and_reads_once(self):
        out = self.dir / "gex_NQ"
        self.assertEqual(ob.gex_main(self.gex_args(), out), 1)  # no freeze record
        self.assertEqual(ob.gex_main(self.gex_args(freeze=True), out), 0)
        (out / "preregistered.json").write_text("{}")
        (self.dir / "data" / f"{ob.TEST_START}_2025-10-25.parquet").write_text("")
        self.assertEqual(ob.gex_main(self.gex_args(), out), 1)  # already read once


if __name__ == "__main__":
    unittest.main()
