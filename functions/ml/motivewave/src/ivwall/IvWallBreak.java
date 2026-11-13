package ivwall;

import com.motivewave.platform.sdk.common.DataSeries;
import com.motivewave.platform.sdk.common.Defaults;
import com.motivewave.platform.sdk.common.Enums$OrderAction;
import com.motivewave.platform.sdk.common.Enums$TIF;
import com.motivewave.platform.sdk.common.Instrument;
import com.motivewave.platform.sdk.common.desc.IntegerDescriptor;
import com.motivewave.platform.sdk.common.desc.SettingGroup;
import com.motivewave.platform.sdk.common.desc.SettingTab;
import com.motivewave.platform.sdk.common.desc.SettingsDescriptor;
import com.motivewave.platform.sdk.common.desc.StringDescriptor;
import com.motivewave.platform.sdk.order_mgmt.Order;
import com.motivewave.platform.sdk.order_mgmt.OrderContext;
import com.motivewave.platform.sdk.study.Study;
import com.motivewave.platform.sdk.study.StudyHeader;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.util.List;

/**
 * Executes the frozen NQ IV-wall break on an MNQ chart from the day's orders file
 * (`iv_wall_paper.py --today --export`). The levels are never computed here.
 *
 * Put it on a 1-minute MNQ chart that shows the full session, then activate it. It does nothing unless the orders
 * file is dated today (ET) and marked tradable.
 */
@StudyHeader(
    namespace = "ivwall",
    id = "IV_WALL_BREAK",
    name = "IV Wall Break",
    desc = "Stop entries at the day's IV walls from the orders file, fixed stop and 2R target, flat before the close.",
    menu = "IV Wall",
    overlay = true,
    signals = false,
    strategy = true,
    autoEntry = true,
    manualEntry = false,
    requiresBarUpdates = true,
    supportsTradeLots = false,
    supportsPositionType = false,
    supportsEnterOnActivate = false,
    supportsSessions = false,
    supportsUnrealizedPL = true,
    supportsRealizedPL = true,
    supportsTotalPL = true)
public class IvWallBreak extends Study {
  static final String PLAN_FILE = "planFile";
  static final String MAX_QTY = "maxQty";
  static final String SYMBOL = "symbolRoot";
  static final ZoneId ET = ZoneId.of("America/New_York");
  static final String DEFAULT_FILE = Path.of(System.getProperty("user.home"), ".iv_wall", "orders.properties").toString();

  // Per-day state. Everything that matters for safety is also recoverable from the chart and the position.
  private String dayKey = "";
  private IvWallPlan plan;
  private long planStamp = -1;
  private String planError = "";
  private boolean halted;
  private String haltReason = "";
  private boolean deadLong, deadShort;   // entry filled or rejected: never re-place this wall today
  private boolean exitDone;              // an exit filled; wait for the position to read flat
  private boolean closeSent;
  private boolean adopted;               // found a position with working orders we did not place
  private int lastInPosSec = -1;
  private String lastStatus = "";

  private Order longEntry, shortEntry, stopOrder, targetOrder;
  private boolean longCancel, shortCancel, stopCancel, targetCancel;

  @Override
  public void initialize(Defaults defaults) {
    SettingsDescriptor sd = createSD();
    SettingTab tab = sd.addTab("General");
    SettingGroup g = tab.addGroup("Orders");
    g.addRow(new StringDescriptor(PLAN_FILE, "Orders file", DEFAULT_FILE));
    g.addRow(new IntegerDescriptor(MAX_QTY, "Max contracts", 1, 1, 20, 1));
    g.addRow(new StringDescriptor(SYMBOL, "Symbol must contain", "MNQ"));
  }

  @Override public void onActivate(OrderContext ctx) { lastStatus = ""; sync(ctx); }
  @Override public void onBarUpdate(OrderContext ctx) { sync(ctx); }
  @Override public void onBarOpen(OrderContext ctx) { sync(ctx); }
  @Override public void onBarClose(OrderContext ctx) { sync(ctx); }
  @Override public void onPositionClosed(OrderContext ctx) { sync(ctx); }

  @Override
  public void onDeactivate(OrderContext ctx) {
    cancelEntries(ctx);
    if (ctx.getPosition() != 0) warning("IV Wall: deactivated with a position open. Its stop and target stay working, "
        + "but nothing will flatten it before the close.");
  }

  @Override
  public void onOrderFilled(OrderContext ctx, Order o) {
    if (o == longEntry) { deadLong = true; longEntry = null; info("IV Wall: long entry filled at " + o.getAvgFillPrice()); }
    else if (o == shortEntry) { deadShort = true; shortEntry = null; info("IV Wall: short entry filled at " + o.getAvgFillPrice()); }
    else if (o == stopOrder) { exitDone = true; stopOrder = null; info("IV Wall: stopped out at " + o.getAvgFillPrice()); }
    else if (o == targetOrder) { exitDone = true; targetOrder = null; info("IV Wall: target filled at " + o.getAvgFillPrice()); }
    sync(ctx);
  }

  @Override
  public void onOrderCancelled(OrderContext ctx, Order o) {
    forget(o);
  }

  @Override
  public void onOrderRejected(OrderContext ctx, Order o) {
    boolean mine = o == longEntry || o == shortEntry || o == stopOrder || o == targetOrder;
    forget(o);
    if (mine) halt("an order was rejected");
    sync(ctx);
  }

  private void forget(Order o) {
    if (o == longEntry) { longEntry = null; longCancel = false; }
    if (o == shortEntry) { shortEntry = null; shortCancel = false; }
    if (o == stopOrder) { stopOrder = null; stopCancel = false; }
    if (o == targetOrder) { targetOrder = null; targetCancel = false; }
  }

  private void halt(String why) {
    if (!halted) error("IV Wall: HALTED for today (" + why + "). Cancelling orders and closing any position.");
    halted = true;
    haltReason = why;
  }

  private void resetDay(String today) {
    dayKey = today;
    plan = null;
    planStamp = -1;
    planError = "";
    halted = false;
    haltReason = "";
    deadLong = deadShort = exitDone = closeSent = adopted = false;
    lastInPosSec = -1;
    longEntry = shortEntry = stopOrder = targetOrder = null;
    longCancel = shortCancel = stopCancel = targetCancel = false;
  }

  /** Reload the orders file when it changes; keep today's plan if the new file is for another day or broken. */
  private void loadPlan(String today) {
    Path f = Path.of(getSettings().getString(PLAN_FILE, DEFAULT_FILE));
    long stamp;
    try {
      stamp = Files.getLastModifiedTime(f).toMillis();
    } catch (Exception e) {
      if (plan == null) planError = "cannot read " + f;
      return;
    }
    if (stamp == planStamp) return;
    planStamp = stamp;
    try {
      IvWallPlan p = IvWallPlan.load(f);
      if (p.date.equals(today)) {
        boolean changed = plan == null || p.longEntry != plan.longEntry || p.shortEntry != plan.shortEntry
            || p.tradable != plan.tradable;
        plan = p;
        planError = "";
        if (changed) info("IV Wall: plan for " + p.date + (p.tradable
            ? ": buy stop " + p.longEntry + " (stop " + p.longStop + ", target " + p.longTarget + "), sell stop "
              + p.shortEntry + " (stop " + p.shortStop + ", target " + p.shortTarget + "), " + p.qty + " contract(s)"
            : ": NO TRADE (" + p.reason + ")"));
      } else if (plan == null) {
        planError = "orders file is for " + p.date + ", not " + today;
      }
    } catch (Exception e) {
      if (plan == null) planError = "bad orders file: " + e.getMessage();
      else warning("IV Wall: ignoring a bad orders file, keeping today's plan: " + e.getMessage());
    }
  }

  private static boolean live(Order o) {
    return o != null && !o.isFilled() && !o.isCancelled();
  }

  private void sync(OrderContext ctx) {
    try {
      syncInner(ctx);
    } catch (RuntimeException e) {
      error("IV Wall: " + e);
    }
  }

  private void syncInner(OrderContext ctx) {
    ZonedDateTime now = Instant.ofEpochMilli(ctx.getCurrentTime()).atZone(ET);
    String today = now.toLocalDate().toString();
    int sec = now.toLocalTime().toSecondOfDay();
    if (!today.equals(dayKey)) resetDay(today);
    loadPlan(today);

    // Drop references to orders that are finished.
    if (longEntry != null && !live(longEntry)) { longEntry = null; longCancel = false; }
    if (shortEntry != null && !live(shortEntry)) { shortEntry = null; shortCancel = false; }
    if (stopOrder != null && !live(stopOrder)) { stopOrder = null; stopCancel = false; }
    if (targetOrder != null && !live(targetOrder)) { targetOrder = null; targetCancel = false; }

    Instrument ins = ctx.getInstrument();
    int pos = ctx.getPosition();
    if (pos != 0) lastInPosSec = sec;
    else { exitDone = false; closeSent = false; adopted = false; }

    String root = getSettings().getString(SYMBOL, "MNQ").trim();
    String sym = ins == null || ins.getSymbol() == null ? "" : ins.getSymbol();
    if (!root.isEmpty() && !sym.toUpperCase().contains(root.toUpperCase())) {
      cancelEntries(ctx);
      status("wrong instrument: chart is " + sym + ", expected " + root);
      return;
    }

    double rthOpen = Double.NaN, hi = Double.NaN, lo = Double.NaN;
    if (plan != null && sec >= plan.openSec) {
      long openMs = ZonedDateTime.of(LocalDate.parse(today), LocalTime.ofSecondOfDay(plan.openSec), ET).toInstant().toEpochMilli();
      DataSeries s = ctx.getDataContext().getDataSeries();
      for (int i = s.size() - 1; i >= 0; i--) {
        long t = s.getStartTime(i);
        if (t < openMs) break;
        float h = s.getHigh(i), l = s.getLow(i);
        if (Double.isNaN(hi) || h > hi) hi = h;
        if (Double.isNaN(lo) || l < lo) lo = l;
        rthOpen = t == openMs ? s.getOpen(i) : Double.NaN;
      }
    }

    int maxQty = getSettings().getInteger(MAX_QTY, 1);
    IvWallLogic.Decision d = IvWallLogic.decide(plan, today, sec, pos, rthOpen, hi, lo, lastInPosSec, maxQty);
    if (plan == null && !planError.isEmpty()) d = IvWallLogic.Decision.idle(IvWallLogic.Phase.NO_PLAN, planError);

    // Sanity: today's levels must be near the market, or the file is for another instrument or stale.
    float last = ins.getLastPrice();
    if (plan != null && plan.tradable && plan.date.equals(today) && last > 0
        && (plan.longEntry > last * 1.15 || plan.shortEntry < last * 0.85)) halt("walls are more than 15% from the market");
    if (pos != 0 && d.phase == IvWallLogic.Phase.SKIP) {
      cancelEntries(ctx);
      status(d.toString() + " (left alone)");
      return;
    }
    if (halted) {
      cancelEntries(ctx);
      cancelExits(ctx);
      closeOnce(ctx, pos);
      status("HALTED: " + haltReason);
      return;
    }

    if (d.flatten) {
      cancelEntries(ctx);
      cancelExits(ctx);
      closeOnce(ctx, pos);
    } else if (d.exits) {
      cancelEntries(ctx);
      placeExits(ctx, pos, last);
    } else {
      cancelExits(ctx);
      if (d.longEntry && !deadLong) {
        if (longEntry == null) {
          longEntry = ctx.createStopOrder(Enums$OrderAction.BUY, Enums$TIF.DAY, d.qty, (float) plan.longEntry);
          ctx.submitOrders(longEntry);
        }
      } else cancelLong(ctx);
      if (d.shortEntry && !deadShort) {
        if (shortEntry == null) {
          shortEntry = ctx.createStopOrder(Enums$OrderAction.SELL, Enums$TIF.DAY, d.qty, (float) plan.shortEntry);
          ctx.submitOrders(shortEntry);
        }
      } else cancelShort(ctx);
    }
    status(d.toString());
  }

  private void placeExits(OrderContext ctx, int pos, float last) {
    if (exitDone) { cancelExits(ctx); return; }   // one exit filled: pull its sibling, never re-place
    if (closeSent) return;
    boolean isLong = pos > 0;
    int qty = Math.abs(pos);
    double stop = isLong ? plan.longStop : plan.shortStop;
    double target = isLong ? plan.longTarget : plan.shortTarget;
    if (stopOrder == null && targetOrder == null && !adopted) {
      // A position we hold no exits for. After a restart they may still be working at the broker.
      List<?> active = ctx.getActiveOrders();
      if (active != null && !active.isEmpty()) {
        adopted = true;
        warning("IV Wall: position open with " + active.size() + " working order(s) this run did not place. Leaving "
            + "them as the exits; check the stop and target by hand. The flat-time close still applies.");
        return;
      }
    }
    if (adopted) return;
    // Already through the stop (gap on the fill): close now instead of resting an order on the wrong side.
    if (last > 0 && (isLong ? last <= stop : last >= stop)) {
      warning("IV Wall: price is through the stop, closing at market");
      cancelExits(ctx);
      closeOnce(ctx, pos);
      return;
    }
    Enums$OrderAction out = isLong ? Enums$OrderAction.SELL : Enums$OrderAction.BUY;
    if (stopOrder == null) {
      stopOrder = ctx.createStopOrder(out, Enums$TIF.DAY, qty, (float) stop);
      ctx.submitOrders(stopOrder);
    }
    if (targetOrder == null) {
      targetOrder = ctx.createLimitOrder(out, Enums$TIF.DAY, qty, (float) target);
      ctx.submitOrders(targetOrder);
    }
  }

  private void closeOnce(OrderContext ctx, int pos) {
    if (pos == 0 || closeSent) return;
    closeSent = true;
    info("IV Wall: closing position at market");
    ctx.closeAtMarket();
  }

  private void cancelLong(OrderContext ctx) {
    if (live(longEntry) && !longCancel) { longCancel = true; ctx.cancelOrders(longEntry); }
  }

  private void cancelShort(OrderContext ctx) {
    if (live(shortEntry) && !shortCancel) { shortCancel = true; ctx.cancelOrders(shortEntry); }
  }

  private void cancelEntries(OrderContext ctx) {
    cancelLong(ctx);
    cancelShort(ctx);
  }

  private void cancelExits(OrderContext ctx) {
    if (live(stopOrder) && !stopCancel) { stopCancel = true; ctx.cancelOrders(stopOrder); }
    if (live(targetOrder) && !targetCancel) { targetCancel = true; ctx.cancelOrders(targetOrder); }
  }

  private void status(String s) {
    if (s.equals(lastStatus)) return;
    lastStatus = s;
    info("IV Wall [" + dayKey + "]: " + s);
  }
}
