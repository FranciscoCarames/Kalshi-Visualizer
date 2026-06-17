"""One-off: export a representative slice of the latest real snapshot into a JS
data file the Terminal Pro FINAL mockup consumes. Calls the REAL webui.viewmodel
row-builders so the mockup shows the exact display values + columns the app would.
Not part of the app."""
import json, hashlib, store
import webui.viewmodel as vm
from collections import Counter

snap = store.latest()
opps = snap["opportunities"]
meta = snap["meta"]

SEC = {  # bucket -> (zone, section-key)
    "actionable": ("exec", "act"), "review_signal": ("exec", "rev"), "blocked": ("exec", "blk"),
    "risk_budget": ("spec", "bounded"), "near_miss": ("spec", "nearmiss"),
    "qualifier_setup": ("spec", "qual"), "no_structure": ("spec", "cheapno"),
    "data_quality": ("diag", "diag"), "display_signal": ("diag", "diag"),
    "wide_signal": ("diag", "diag"), "near_edge": ("diag", "diag"), "clean": ("diag", "diag"),
}
EMPTY = (set(), {}, set())

def clean(r):
    return {k: v for k, v in r.items() if not k.startswith("_")}

def num(x):
    try:
        return None if x is None or x == "" else round(float(x), 2)
    except Exception:
        return None

def spark(oid):
    h = hashlib.md5(oid.encode()).digest()
    base = h[0] % 30 + 10
    return [base + ((h[i] % 11) - 5) for i in range(7)]

def trim_legs(o):
    out = []
    for l in (o.get("legs") or [])[:24]:
        out.append({"side": l.get("side"), "c": l.get("contract"), "p": l.get("price_c"),
                    "sz": round(float(l.get("size") or 0), 1), "tk": l.get("ticker"), "u": l.get("url")})
    return out

def build_row(o):
    bucket = o.get("bucket")
    zone, sec = SEC.get(bucket, ("diag", "diag"))
    try:
        if bucket == "risk_budget":
            base = clean(vm.risk_budget_row(o, *EMPTY))
        elif bucket == "near_miss":
            base = clean(vm.near_miss_row(o, *EMPTY))
        elif bucket == "no_structure":
            base = clean(vm.no_structure_row(o, *EMPTY))
        elif bucket == "qualifier_setup":
            base = clean(vm.qualifier_row(o, *EMPTY))
        else:
            base = clean(vm.opp_row(o, set(), {}, set()))
    except Exception as e:
        base = {"name": o.get("name"), "sport": o.get("sport_label"), "caveat": f"(row err: {e})"}
    nf = vm.net_of_fees(o)
    parent = num(o.get("parent_yes_bid_c")); child = num(o.get("child_yes_ask_c"))
    cond = round(child / parent * 100) if (parent and child and parent > 0) else None
    base.update({
        "id": o["opportunity_id"], "bucket": bucket, "zone": zone, "section": sec,
        "scope": o.get("no_structure_scope"),
        "resolution_mode": o.get("resolution_mode"),  # vertical/calendar
        "sport": o.get("sport_label") or base.get("sport"),
        "sub": o.get("tournament") or base.get("detail") or "",
        "status": o.get("status"), "tradable": o.get("tradable_now") or base.get("tradable"),
        "rule": o.get("rule_flag"), "settlement_caveat": o.get("settlement_caveat"),
        "blk": o.get("blocked_reason"),
        "legs": trim_legs(o), "nlegs": (int(o["n_legs"]) if num(o.get("n_legs")) else len(o.get("legs") or [])),
        "url": o.get("url"), "url2": o.get("url_2"),
        "pnode": o.get("parent_node"), "cnode": o.get("child_node"), "pbid": parent, "cask": child,
        "cond": cond, "spark": spark(o["opportunity_id"]),
        # net-of-fees estimate (display-only) for every row
        "fees": nf.get("total_fees_c"), "net_edge": nf.get("net_edge_c"), "net_profit": nf.get("net_profit_dollars"),
    })
    # normalize flags list -> short string
    if isinstance(base.get("flags"), list):
        base["flags"] = " ".join(
            (f.get("label") if isinstance(f, dict) else str(f)) for f in base["flags"]) if base["flags"] else ""
    return base

def keyrank(o):
    return (-(num(o.get("exec_gap_c")) or -999), -(num(o.get("roi_pct")) or -999))

CAPS = {"actionable": 99, "review_signal": 99, "blocked": 99, "qualifier_setup": 99,
        "risk_budget": 220, "near_miss": 120, "no_structure": 220}
DIAG_CAP = 90

by_bucket = {}
for o in opps:
    by_bucket.setdefault(o.get("bucket"), []).append(o)

records, diag_taken = [], 0
for b, rows in by_bucket.items():
    rows = sorted(rows, key=keyrank)
    zone = SEC.get(b, ("diag",))[0]
    take = rows[: max(0, DIAG_CAP - diag_taken)] if zone == "diag" else rows[: CAPS.get(b, 50)]
    if zone == "diag":
        diag_taken += len(take)
    records.extend(build_row(o) for o in take)

totals = {b: len(rows) for b, rows in by_bucket.items()}
# split counts the mockup will show
res_counts = Counter((o.get("resolution_mode") or "?") for o in opps if o.get("bucket") == "risk_budget")
scope_counts = Counter((o.get("no_structure_scope") or "other") for o in opps if o.get("bucket") == "no_structure")

META = {
    "snapshot_id": snap["snapshot_id"], "fetched_at": snap["fetched_at"], "n_total": len(opps),
    "contracts": meta.get("contracts_scanned"), "checks": meta.get("checks_tested"),
    "requests": meta.get("kalshi_requests"), "scanned": meta.get("scanned"),
    "failed": meta.get("failed"), "retry": meta.get("retry_count"),
    "totals": totals, "shown": dict(Counter(r["bucket"] for r in records)),
    "sports": dict(Counter(o.get("sport_label") or o.get("sport") for o in opps)),
    "resolution_counts": dict(res_counts), "scope_counts": dict(scope_counts),
    "series_errors": meta.get("series_errors"),
}

with open("tp-final-data.js", "w", encoding="utf-8") as f:
    f.write("/* Auto-generated from REAL snapshot #%s (%s) via webui.viewmodel row-builders. Mockup data only. */\n"
            % (META["snapshot_id"], META["fetched_at"]))
    f.write("const REAL_META=" + json.dumps(META, ensure_ascii=True, default=str) + ";\n")
    f.write("const REAL_OPPS=" + json.dumps(records, ensure_ascii=True, default=str) + ";\n")

print("snapshot", META["snapshot_id"], "| rows", len(records), "| res", dict(res_counts), "| scope", dict(scope_counts))
