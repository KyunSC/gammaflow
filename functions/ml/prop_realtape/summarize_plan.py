"""Print a plan result (results/<id>.json): headline vs synthetic, eras, always-long, entry/rule rankings."""
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "prop_realtape" / "results"
ERAS = ("pooled", "2011-18", "2019-21", "2022-26")


def main(name):
    r = json.loads((OUT / f"{name}.json").read_text())
    f = lambda x: (f"{x['ev']:+7.1f} [{x['ev_ci'][0]:+.0f},{x['ev_ci'][1]:+.0f}] pass {x['pass_rate']:.3f} paid {x['p_paid']:.3f} "
                   f"days {x['days_used']:.1f} fee {x['fee']:.0f} EV/d {x['ev_per_day']:+.1f}")
    s = r["synthetic"]
    print(r["plan"], "risk", r["risk"], "n", r["contracts"], "cap", r["cap"], "flat", r["flat_by"], "mode", r["compress_mode"])
    print("synthetic", round(s["ev"], 1), [round(v, 1) for v in s["ev_ci"]], "pass", round(s["pass_rate"], 3), "paid",
          round(s["p_paid"], 3), "days", round(s["days_used"], 1), "fee", round(s["fee"], 1), "kabs", r["k_abs"])
    for prod in ("NQ", "ES"):
        H = r[f"headline_{prod}"]
        for e in ERAS:
            x = H[e]
            print(prod, e.ljust(7), "boot", f(x["boot"]), "| hist", f"{x['hist']['ev']:+.1f} [{x['hist']['ev_ci'][0]:+.0f},{x['hist']['ev_ci'][1]:+.0f}]",
                  "| long boot", f"{x['always_long_boot']['ev']:+.1f}", "hist", f"{x['always_long_hist']['ev']:+.1f}",
                  "sd", round(x["boot"]["ev_sd_across_coins"], 1))
        print(prod, "exits", {e: (v["stop"], v["target"], v["flat"]) for e, v in H["exits"].items()})
    G = r["grid"]
    for prod in ("NQ", "ES"):
        print(prod, "entry ranking (fixed):")
        for e in ERAS:
            rows = [g for g in G if g["product"] == prod and g["rule"] == "fixed"]
            print("  ", e, sorted([(g["entry"], round(g[e]["boot"]["ev"]), round((g[e]["boot"]["ev_ci"][1] - g[e]["boot"]["ev_ci"][0]) / 2))
                                   for g in rows], key=lambda t: -t[1]))
        print(prod, "rule ranking (mean over entries):")
        for e in ERAS:
            av = {ru: round(sum(g[e]["boot"]["ev"] for g in G if g["product"] == prod and g["rule"] == ru) / 4, 1)
                  for ru in ("fixed", "rel_atr", "rel_vix", "abs_atr", "abs_vix")}
            print("  ", e, sorted(av.items(), key=lambda t: -t[1]))
        for ru in ("abs_atr", "abs_vix"):
            g = next(g for g in G if g["product"] == prod and g["rule"] == ru and g["entry"] == "0935")
            print("  ", ru, "0935 capped/risk", {e: (round(g["exits"][e]["capped_share"], 2), round(g["exits"][e]["mean_risk"]))
                                                 for e in ERAS[1:]})


if __name__ == "__main__":
    main(sys.argv[1])
