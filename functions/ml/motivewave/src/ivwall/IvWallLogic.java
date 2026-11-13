package ivwall;

/**
 * What the IV-wall break wants resting right now. Pure function of the plan, the clock and the session so far, so a
 * restart mid-session reaches the same answer. Rules are the ones in frontend/lib/ivWalls.js:
 *
 *   - no trades when the 09:30 bar opens on or outside a wall;
 *   - a wall touched at any time from 09:30 is dead for the day (traded or not);
 *   - entry stops rest from the plan's first_order time (09:30 since 2026-11-12, 09:35 before) until 15:35
 *     (order_end), never while a trade is open, and come back only at the
 *     next 5-minute boundary after a trade closes (the backtest re-places its order on 5-minute closes);
 *   - an open trade keeps a stop and a 2R target, and is closed at market at 15:55 (flat).
 */
final class IvWallLogic {
  enum Phase { NO_PLAN, SKIP, PRE_OPEN, WAIT, ARMED, IN_TRADE, ENTRIES_CLOSED, FLATTEN, DONE }

  static final class Decision {
    final Phase phase;
    final boolean longEntry, shortEntry;   // entry stops that should be resting
    final boolean exits;                   // stop + target should be resting for the open position
    final boolean flatten;                 // cancel everything and close at market
    final int qty;
    final String note;

    Decision(Phase phase, boolean longEntry, boolean shortEntry, boolean exits, boolean flatten, int qty, String note) {
      this.phase = phase;
      this.longEntry = longEntry;
      this.shortEntry = shortEntry;
      this.exits = exits;
      this.flatten = flatten;
      this.qty = qty;
      this.note = note;
    }

    static Decision idle(Phase phase, String note) {
      return new Decision(phase, false, false, false, false, 0, note);
    }

    @Override public String toString() {
      return phase + (note.isEmpty() ? "" : ": " + note);
    }
  }

  private IvWallLogic() {}

  /**
   * @param today        ET date of the clock, YYYY-MM-DD
   * @param sec          ET seconds of day
   * @param pos          signed position
   * @param rthOpen      open of the 09:30 bar, NaN when unknown
   * @param sessHigh     highest price since 09:30 (NaN before the open)
   * @param sessLow      lowest price since 09:30
   * @param lastInPosSec ET second the position was last seen open today, -1 if never
   * @param maxQty       hard cap on contracts
   */
  static Decision decide(IvWallPlan p, String today, int sec, int pos, double rthOpen, double sessHigh, double sessLow,
                         int lastInPosSec, int maxQty) {
    if (p == null) return Decision.idle(Phase.NO_PLAN, "no orders file for " + today);
    if (!p.date.equals(today)) return Decision.idle(Phase.NO_PLAN, "orders file is for " + p.date + ", not " + today);
    if (sec >= p.closeSec) return Decision.idle(Phase.DONE, pos != 0 ? "POSITION STILL OPEN after the close" : "session over");
    if (sec >= p.flatSec) return new Decision(Phase.FLATTEN, false, false, false, true, 0, "flat time");
    if (pos != 0) {
      if (!p.tradable || sec < p.firstOrderSec) return Decision.idle(Phase.SKIP, "position open that this plan did not create");
      return new Decision(Phase.IN_TRADE, false, false, true, false, Math.abs(pos), pos > 0 ? "long" : "short");
    }
    if (!p.tradable) return Decision.idle(Phase.SKIP, p.reason.isEmpty() ? "no trade today" : p.reason);
    int qty = Math.min(p.qty, maxQty);
    if (qty <= 0) return Decision.idle(Phase.SKIP, "size is 0 (stop too wide for the risk budget)");
    if (sec < p.openSec) return Decision.idle(Phase.PRE_OPEN, "before the open");
    if (Double.isNaN(rthOpen) || Double.isNaN(sessHigh) || Double.isNaN(sessLow))
      return Decision.idle(Phase.SKIP, "no bar starting at the RTH open on this chart");
    if (!(rthOpen > p.shortEntry && rthOpen < p.longEntry)) return Decision.idle(Phase.SKIP, "opened outside the walls");
    boolean upLive = sessHigh < p.longEntry, dnLive = sessLow > p.shortEntry;
    if (!upLive && !dnLive) return Decision.idle(Phase.ENTRIES_CLOSED, "both walls touched");
    if (sec < p.firstOrderSec) return Decision.idle(Phase.WAIT, "orders go live at the first-order time");
    if (sec >= p.orderEndSec) return Decision.idle(Phase.ENTRIES_CLOSED, "past the last-order time");
    if (lastInPosSec >= 0 && sec < (lastInPosSec / 300 + 1) * 300)
      return Decision.idle(Phase.WAIT, "re-arming at the next 5-minute boundary");
    return new Decision(Phase.ARMED, upLive, dnLive, false, false, qty,
        (upLive ? "buy stop " + p.longEntry : "upper wall dead") + ", " + (dnLive ? "sell stop " + p.shortEntry : "lower wall dead"));
  }
}
