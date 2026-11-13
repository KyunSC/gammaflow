package ivwall;

import ivwall.IvWallLogic.Decision;
import ivwall.IvWallLogic.Phase;

import java.util.Properties;

/** Plain-Java checks of the plan parser and the decision table. Run by build.sh; exits non-zero on failure. */
public final class IvWallLogicTest {
  static int failed = 0, run = 0;
  static final String D = "2026-11-12";

  static Properties props(boolean tradable) {
    Properties p = new Properties();
    p.setProperty("version", "1");
    p.setProperty("date", D);
    p.setProperty("tradable", String.valueOf(tradable));
    p.setProperty("reason", tradable ? "" : "contract roll");
    p.setProperty("first_order", "09:30");
    p.setProperty("order_end", "15:35");
    p.setProperty("flat", "15:55");
    p.setProperty("rth_close", "16:00");
    if (tradable) {
      p.setProperty("long_entry", "25300.00");
      p.setProperty("long_stop", "25180.00");
      p.setProperty("long_target", "25540.00");
      p.setProperty("short_entry", "24700.00");
      p.setProperty("short_stop", "24820.00");
      p.setProperty("short_target", "24460.00");
      p.setProperty("qty", "1");
    }
    return p;
  }

  static int t(int h, int m) { return h * 3600 + m * 60; }

  static void check(String name, boolean ok) {
    run++;
    if (!ok) { failed++; System.out.println("FAIL " + name); }
  }

  static void bad(String name, Properties p) {
    try { IvWallPlan.parse(p); check(name, false); } catch (RuntimeException e) { check(name, true); }
  }

  public static void main(String[] a) {
    IvWallPlan p = IvWallPlan.parse(props(true));
    Decision d;

    // Plan parsing
    check("times", p.openSec == t(9, 30) && p.firstOrderSec == t(9, 30) && p.orderEndSec == t(15, 35) && p.flatSec == t(15, 55) && p.closeSec == t(16, 0));
    Properties x = props(true); x.setProperty("long_entry", "25300.10"); bad("off tick", x);
    x = props(true); x.setProperty("long_stop", "25400.00"); bad("stop above entry", x);
    x = props(true); x.remove("short_target"); bad("missing key", x);
    x = props(true); x.setProperty("version", "2"); bad("version", x);
    x = props(true); x.setProperty("short_stop", "25200.00"); bad("walls overlap", x);
    x = props(true); x.setProperty("first_order", "09:25"); bad("first order before the open", x);
    check("skip plan parses", !IvWallPlan.parse(props(false)).tradable);

    // No plan / wrong date
    check("null plan", IvWallLogic.decide(null, D, t(10, 0), 0, 25000, 25010, 24990, -1, 1).phase == Phase.NO_PLAN);
    d = IvWallLogic.decide(p, "2026-11-13", t(10, 0), 0, 25000, 25010, 24990, -1, 1);
    check("stale plan places nothing", d.phase == Phase.NO_PLAN && !d.longEntry && !d.shortEntry && !d.flatten);

    // Before the open
    check("pre-open", IvWallLogic.decide(p, D, t(9, 0), 0, Double.NaN, Double.NaN, Double.NaN, -1, 1).phase == Phase.PRE_OPEN);
    d = IvWallLogic.decide(p, D, t(9, 29) + 59, 0, Double.NaN, Double.NaN, Double.NaN, -1, 1);
    check("nothing rests at 09:29:59", d.phase == Phase.PRE_OPEN && !d.longEntry && !d.shortEntry);
    d = IvWallLogic.decide(p, D, t(9, 30), 0, Double.NaN, Double.NaN, Double.NaN, -1, 1);
    check("no orders until the 09:30 bar exists", !d.longEntry && !d.shortEntry);

    // Armed on both walls from the open
    d = IvWallLogic.decide(p, D, t(9, 30), 0, 25000, 25010, 24990, -1, 1);
    check("armed at 09:30", d.phase == Phase.ARMED && d.longEntry && d.shortEntry && d.qty == 1);
    d = IvWallLogic.decide(p, D, t(9, 30) + 5, 0, 25000, 25300, 24990, -1, 1);
    check("wall touched before the order rested is dead", d.phase == Phase.ARMED && !d.longEntry && d.shortEntry);

    // A plan that still says 09:35 waits until then
    x = props(true); x.setProperty("first_order", "09:35");
    d = IvWallLogic.decide(IvWallPlan.parse(x), D, t(9, 32), 0, 25000, 25010, 24990, -1, 1);
    check("09:35 plan waits", d.phase == Phase.WAIT && !d.longEntry && !d.shortEntry);
    check("qty capped", IvWallLogic.decide(p, D, t(9, 35), 0, 25000, 25010, 24990, -1, 0).phase == Phase.SKIP);

    // A wall touched in the first five minutes is dead, the other still rests
    d = IvWallLogic.decide(p, D, t(9, 40), 0, 25000, 25300, 24990, -1, 1);
    check("upper touched early", d.phase == Phase.ARMED && !d.longEntry && d.shortEntry);
    d = IvWallLogic.decide(p, D, t(9, 40), 0, 25000, 25299.75, 24700, -1, 1);
    check("lower touched early", d.phase == Phase.ARMED && d.longEntry && !d.shortEntry);
    check("both touched", IvWallLogic.decide(p, D, t(11, 0), 0, 25000, 25310, 24690, -1, 1).phase == Phase.ENTRIES_CLOSED);

    // Opened on or outside a wall
    check("opened above", IvWallLogic.decide(p, D, t(9, 40), 0, 25350, 25360, 25340, -1, 1).phase == Phase.SKIP);
    check("opened on the wall", IvWallLogic.decide(p, D, t(9, 40), 0, 24700, 24710, 24700, -1, 1).phase == Phase.SKIP);
    check("no 09:30 bar", IvWallLogic.decide(p, D, t(9, 40), 0, Double.NaN, 25010, 24990, -1, 1).phase == Phase.SKIP);

    // In a trade
    d = IvWallLogic.decide(p, D, t(10, 12), 1, 25000, 25320, 24990, t(10, 12), 1);
    check("in trade: exits only", d.phase == Phase.IN_TRADE && d.exits && !d.longEntry && !d.shortEntry && d.qty == 1);
    check("position before the open is not ours", IvWallLogic.decide(p, D, t(9, 29), 1, Double.NaN, Double.NaN, Double.NaN, t(9, 29), 1).phase == Phase.SKIP);
    d = IvWallLogic.decide(p, D, t(9, 31), 1, 25000, 25305, 24990, t(9, 31), 1);
    check("fill in the first five minutes gets exits", d.phase == Phase.IN_TRADE && d.exits);

    // After the trade: wait for the next 5-minute boundary, then only the untouched wall
    d = IvWallLogic.decide(p, D, t(10, 13) + 20, 0, 25000, 25320, 24990, t(10, 13), 1);
    check("no re-arm inside the exit bar", d.phase == Phase.WAIT && !d.shortEntry);
    d = IvWallLogic.decide(p, D, t(10, 15), 0, 25000, 25320, 24990, t(10, 13), 1);
    check("re-arm other wall", d.phase == Phase.ARMED && !d.longEntry && d.shortEntry);

    // Last-order and flat times
    d = IvWallLogic.decide(p, D, t(15, 34) + 59, 0, 25000, 25010, 24990, -1, 1);
    check("still armed at 15:34:59", d.phase == Phase.ARMED);
    d = IvWallLogic.decide(p, D, t(15, 35), 0, 25000, 25010, 24990, -1, 1);
    check("entries pulled at 15:35", d.phase == Phase.ENTRIES_CLOSED && !d.longEntry && !d.shortEntry);
    d = IvWallLogic.decide(p, D, t(15, 54) + 59, -1, 25000, 25010, 24690, t(15, 54), 1);
    check("holding at 15:54:59", d.phase == Phase.IN_TRADE && d.exits && !d.flatten);
    d = IvWallLogic.decide(p, D, t(15, 55), -1, 25000, 25010, 24690, t(15, 54), 1);
    check("flatten at 15:55", d.phase == Phase.FLATTEN && d.flatten && !d.exits);
    d = IvWallLogic.decide(p, D, t(16, 0), 0, 25000, 25010, 24990, -1, 1);
    check("done after close", d.phase == Phase.DONE && !d.flatten);
    check("evening Globex untouched", !IvWallLogic.decide(p, D, t(19, 0), 2, 25000, 25010, 24990, -1, 1).flatten);

    // No-trade plan
    d = IvWallLogic.decide(IvWallPlan.parse(props(false)), D, t(10, 0), 0, 25000, 25010, 24990, -1, 1);
    check("skip day", d.phase == Phase.SKIP && !d.longEntry && !d.shortEntry);

    // Half day
    x = props(true); x.setProperty("order_end", "12:55"); x.setProperty("flat", "12:55"); x.setProperty("rth_close", "13:00");
    IvWallPlan h = IvWallPlan.parse(x);
    check("half day flatten", IvWallLogic.decide(h, D, t(12, 55), 1, 25000, 25320, 24990, t(12, 54), 1).flatten);
    check("half day armed", IvWallLogic.decide(h, D, t(12, 30), 0, 25000, 25010, 24990, -1, 1).phase == Phase.ARMED);

    System.out.println((run - failed) + "/" + run + " checks passed");
    if (failed > 0) System.exit(1);
  }
}
