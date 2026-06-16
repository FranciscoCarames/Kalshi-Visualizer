"""Manual fee cross-check aid — confirm the DISPLAY-ONLY fee estimate matches Kalshi's published formula.

This is NOT a CI test (it touches the live API and its numbers are meant for eyeball comparison against
Kalshi's on-site fee tooltip, which is the source of truth and is bot-throttled). The pure formula is
unit-tested in tests/test_webui.py (test_kalshi_fee_c_matches_published_schedule_examples); this script is
the bridge from that formula to live market data.

What it prints:
  1. The formula + the worked examples (taker 0.07 / maker 0.0175 × multiplier, ceil per fill).
  2. For each sample (series, price_c, size): the computed taker & maker fee in ¢ and $.
  3. Live per-series fee_type + fee_multiplier (so you can confirm the multiplier the estimate uses).

Usage (from the repo root; live calls need the network — run with the Bash tool's sandbox OFF):
    python scripts/verify_fees.py
    python scripts/verify_fees.py KXATPMATCH:50:100 KXNBA:33:200   # custom series:price_c:size tuples
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import webui.viewmodel as vm  # noqa: E402

SAMPLES = [("KXATPMATCH", 50, 100), ("KXATPMATCH", 10, 100), ("KXNBA", 33, 200), ("KXNFLGAME", 99, 50)]


def _dollars(cents: int) -> str:
    return f"${cents / 100:.2f}"


def main(argv: list[str]) -> int:
    tuples = SAMPLES
    if argv:
        try:
            tuples = [(s, int(p), int(n)) for s, p, n in (a.split(":") for a in argv)]
        except ValueError:
            print("bad arg; expected series:price_c:size (e.g. KXATPMATCH:50:100)")
            return 2

    print(f"Formula: fee = ceil(coeff x C x P x (1-P)) per fill, in cents.  "
          f"taker base = {config.FEE_TAKER_BASE_COEFF}, maker base = {config.FEE_MAKER_BASE_COEFF}, "
          f"coeff = base x series fee_multiplier.")
    print("Worked examples (mult 1): taker @50c x100 = $1.75 | @10c/@90c x100 = $0.63 | "
          "maker @50c x100 = $0.44\n")

    # Live per-series fee metadata (fee_type drives whether maker fees apply; multiplier scales the base).
    series = sorted({s for s, _, _ in tuples})
    try:
        import kalshi_client
        meta = kalshi_client.get_series_meta(series)
    except Exception as exc:  # noqa: BLE001 - network may be blocked; fall back to the general schedule
        print(f"(live fee fetch failed: {exc} — showing general-schedule estimate)\n")
        meta = {}

    print(f"{'series':14} {'fee_type':28} {'mult':>5} {'price':>6} {'size':>6} "
          f"{'taker':>8} {'maker':>8}")
    print("-" * 92)
    for s, price_c, size in tuples:
        m = meta.get(s) or {}
        ft, mult = m.get("fee_type"), m.get("fee_multiplier")
        ec = vm.effective_coeffs(ft, mult if mult is not None else config.FEE_DEFAULT_MULTIPLIER)
        if not ec["estimable"]:
            print(f"{s:14} {str(ft or 'UNKNOWN'):28} {str(mult):>5} {price_c:>6} {size:>6} "
                  f"{'(' + ec['status'] + ')':>17}")
            continue
        tk = vm.kalshi_fee_c(size, price_c, ec["taker"])
        mk = vm.kalshi_fee_c(size, price_c, ec["maker"]) if ec["maker"] else 0
        print(f"{s:14} {str(ft or 'fallback'):28} {str(mult if mult is not None else 1.0):>5} "
              f"{price_c:>6} {size:>6} {tk:>4}c {_dollars(tk):>6} {mk:>4}c {_dollars(mk):>6}")
    print("\nCompare these against Kalshi's fee display on the live market (the 'i' / fee tooltip).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
