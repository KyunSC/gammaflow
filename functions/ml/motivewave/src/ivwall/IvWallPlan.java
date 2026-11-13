package ivwall;

import java.io.IOException;
import java.io.Reader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Properties;

/**
 * One session's IV-wall break orders, as written by `iv_wall_paper.py --today --export`.
 * The file is a Java properties file; every price is already snapped to the tick grid by the Python side.
 */
final class IvWallPlan {
  static final int VERSION = 1;
  static final double TICK = 0.25;

  final String date;          // ET session date, YYYY-MM-DD
  final boolean tradable;     // false = no orders today (skip reason in `reason`)
  final String reason;
  final double longEntry, longStop, longTarget;
  final double shortEntry, shortStop, shortTarget;
  final int qty;              // MNQ contracts from the risk budget; 0 = stop too wide
  final int openSec, firstOrderSec, orderEndSec, flatSec, closeSec;   // ET seconds of day

  private IvWallPlan(Properties p) {
    int v = Integer.parseInt(req(p, "version"));
    if (v != VERSION) throw new IllegalArgumentException("orders file version " + v + ", expected " + VERSION);
    date = req(p, "date");
    if (!date.matches("\\d{4}-\\d{2}-\\d{2}")) throw new IllegalArgumentException("bad date " + date);
    tradable = Boolean.parseBoolean(req(p, "tradable"));
    reason = p.getProperty("reason", "").trim();
    openSec = hhmm(p.getProperty("rth_open", "09:30"));
    firstOrderSec = hhmm(req(p, "first_order"));
    orderEndSec = hhmm(req(p, "order_end"));
    flatSec = hhmm(req(p, "flat"));
    closeSec = hhmm(req(p, "rth_close"));
    if (!(openSec <= firstOrderSec && firstOrderSec < orderEndSec && orderEndSec <= flatSec && flatSec < closeSec))
      throw new IllegalArgumentException("session times out of order");
    if (!tradable) {
      longEntry = longStop = longTarget = shortEntry = shortStop = shortTarget = Double.NaN;
      qty = 0;
      return;
    }
    longEntry = price(p, "long_entry");
    longStop = price(p, "long_stop");
    longTarget = price(p, "long_target");
    shortEntry = price(p, "short_entry");
    shortStop = price(p, "short_stop");
    shortTarget = price(p, "short_target");
    qty = Integer.parseInt(req(p, "qty"));
    if (qty < 0) throw new IllegalArgumentException("negative qty");
    if (!(longStop < longEntry && longEntry < longTarget)) throw new IllegalArgumentException("long levels out of order");
    if (!(shortTarget < shortEntry && shortEntry < shortStop)) throw new IllegalArgumentException("short levels out of order");
    if (!(shortStop < longStop)) throw new IllegalArgumentException("walls overlap");
  }

  static IvWallPlan load(Path file) throws IOException {
    Properties p = new Properties();
    try (Reader r = Files.newBufferedReader(file, StandardCharsets.UTF_8)) {
      p.load(r);
    }
    return new IvWallPlan(p);
  }

  static IvWallPlan parse(Properties p) {
    return new IvWallPlan(p);
  }

  private static String req(Properties p, String k) {
    String v = p.getProperty(k);
    if (v == null || v.isBlank()) throw new IllegalArgumentException("orders file is missing '" + k + "'");
    return v.trim();
  }

  private static double price(Properties p, String k) {
    double v = Double.parseDouble(req(p, k));
    if (!(v > 0) || Double.isInfinite(v)) throw new IllegalArgumentException(k + " is not a price: " + v);
    double q = v / TICK;
    if (Math.abs(q - Math.rint(q)) > 1e-6) throw new IllegalArgumentException(k + " is off the tick grid: " + v);
    return v;
  }

  private static int hhmm(String s) {
    String[] a = s.trim().split(":");
    if (a.length != 2) throw new IllegalArgumentException("bad time " + s);
    int h = Integer.parseInt(a[0]), m = Integer.parseInt(a[1]);
    if (h < 0 || h > 23 || m < 0 || m > 59) throw new IllegalArgumentException("bad time " + s);
    return h * 3600 + m * 60;
  }
}
