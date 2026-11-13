"""Step 5: cross-plan synthesis of results/*.json -> data/prop_realtape/synthesis.json (and stdout tables)."""
import json
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parent.parent / "data" / "prop_realtape"
ERAS = ("2011-18", "2019-21", "2022-26")
ENTRIES = ("0935", "1000", "1100", "1300")
RULES = ("fixed", "rel_atr", "rel_vix", "abs_atr", "abs_vix")


def main():
    st = json.loads((OUT / "state.json").read_text())
    ids = [p["id"] for p in st["plans_done"]]
    res = {i: json.loads((OUT / "results" / f"{i}.json").read_text()) for i in ids}
    res["mff_builder_50k_promo40"] = json.loads((OUT / "results" / "mff_builder_50k_promo40.json").read_text())
    rows = []
    for i, r in res.items():
        H, E = r["headline_NQ"], r["headline_ES"]
        b = lambda X, e: X[e]["boot"]
        rows.append(dict(id=i, plan=r["plan"], firm=r["firm"], provisional=r["firm"] == "apex",
                         synthetic=r["synthetic"]["ev"], synthetic_ci=r["synthetic"]["ev_ci"],
                         nq_2022_26=b(H, "2022-26")["ev"], nq_2022_26_ci=b(H, "2022-26")["ev_ci"],
                         nq_pooled=b(H, "pooled")["ev"], nq_pooled_ci=b(H, "pooled")["ev_ci"],
                         nq_2011_18=b(H, "2011-18")["ev"], nq_2019_21=b(H, "2019-21")["ev"],
                         nq_hist_pooled=H["pooled"]["hist"]["ev"], es_2022_26=b(E, "2022-26")["ev"], es_pooled=b(E, "pooled")["ev"],
                         long_nq_pooled=H["pooled"]["always_long_boot"]["ev"], long_nq_2022_26=H["2022-26"]["always_long_boot"]["ev"],
                         coin_sd_nq_pooled=b(H, "pooled")["ev_sd_across_coins"],
                         days_2011_18=b(H, "2011-18")["days_used"], days_2022_26=b(H, "2022-26")["days_used"]))
    print(f"{'plan':<34}{'synth':>8}{'NQ22-26':>9}{'CI':>14}{'NQpool':>8}{'CI':>14}{'NQ11-18':>8}{'ES22-26':>8}{'ESpool':>8}{'long':>7}")
    for x in sorted(rows, key=lambda x: -x["synthetic"]):
        ci = lambda c: f"[{c[0]:+.0f},{c[1]:+.0f}]"
        print(f"{x['id']:<34}{x['synthetic']:+8.0f}{x['nq_2022_26']:+9.0f}{ci(x['nq_2022_26_ci']):>14}{x['nq_pooled']:+8.0f}{ci(x['nq_pooled_ci']):>14}"
              f"{x['nq_2011_18']:+8.0f}{x['es_2022_26']:+8.0f}{x['es_pooled']:+8.0f}{x['long_nq_pooled']:+7.0f}")
    rk = lambda key: [x["id"] for x in sorted(rows, key=lambda x: -x[key])]
    ranking = {k: rk(k) for k in ("synthetic", "nq_2022_26", "nq_pooled", "es_2022_26")}
    for k, v in ranking.items():
        print(k, v)
    # structural choices: per plan x product, era-wise rank of each entry (fixed rule) and each rule (avg over entries)
    struct = {"entry": {}, "rule": {}}
    plans = [i for i in ids]
    for prod in ("NQ", "ES"):
        ent_first = {e: {era: 0 for era in ERAS} for e in ENTRIES}
        ent_last = {e: {era: 0 for era in ERAS} for e in ENTRIES}
        ent_delta = {e: {era: [] for era in ERAS} for e in ENTRIES}
        rule_first = {r: {era: 0 for era in ERAS} for r in RULES}
        rule_delta = {r: {era: [] for era in ERAS} for r in RULES}
        for i in plans:
            G = [g for g in res[i]["grid"] if g["product"] == prod]
            for era in ERAS:
                ev = {g["entry"]: g[era]["boot"]["ev"] for g in G if g["rule"] == "fixed"}
                order = sorted(ev, key=lambda k: -ev[k])
                ent_first[order[0]][era] += 1
                ent_last[order[-1]][era] += 1
                for e in ENTRIES:
                    ent_delta[e][era].append(ev[e] - ev["0935"])
                rv = {r: np.mean([g[era]["boot"]["ev"] for g in G if g["rule"] == r]) for r in RULES}
                rule_first[max(rv, key=rv.get)][era] += 1
                for r in RULES:
                    rule_delta[r][era].append(rv[r] - rv["fixed"])
        struct["entry"][prod] = dict(first=ent_first, last=ent_last,
                                     mean_delta_vs_0935={e: {era: float(np.mean(v)) for era, v in d.items()} for e, d in ent_delta.items()})
        struct["rule"][prod] = dict(first=rule_first,
                                    mean_delta_vs_fixed={r: {era: float(np.mean(v)) for era, v in d.items()} for r, d in rule_delta.items()})
        print(prod, "entry #1 counts", ent_first, "\n   last", ent_last)
        print(prod, "entry mean delta vs 0935", {e: {era: round(float(np.mean(v)), 1) for era, v in d.items()} for e, d in ent_delta.items()})
        print(prod, "rule #1 counts", rule_first)
        print(prod, "rule mean delta vs fixed", {r: {era: round(float(np.mean(v)), 1) for era, v in d.items()} for r, d in rule_delta.items()})
    (OUT / "synthesis.json").write_text(json.dumps(dict(rows=rows, ranking=ranking, structure=struct), indent=1, default=float))


if __name__ == "__main__":
    main()
