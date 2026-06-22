---
paths:
  - "data.py"
  - "viz.py"
  - "glossary.py"
---

# Pricing model — do not regress

- **Display %** = YES midpoint when the spread is reasonable (`SPREAD_REASONABLE = 0.20`), else last
  trade, else blank. A `0.00/1.00` book is "No quote" (never a fake 50%). Surface every component (mid /
  last / bid / ask / spread) so a price is never opaque.
- **Quote quality:** Tight (≤5¢) / OK (≤15¢) / Wide (≤30¢) / Very wide / One-sided / No quote / Crossed.
- **Known limits (single-sourced in `glossary.py` "Known limits"):** every edge is **GROSS and
  TOP-OF-BOOK**. Three costs are documented, NOT modeled, until the owner opts in — **fees** (never
  netted; "gross-only" ≠ "ignore fees"), **position limits / collateral**, and **full-depth execution**.
  Treat edges as an upper bound.
- **Never `float()` a raw price field** — use `data.to_float` (None-safe; `""`→None) or `data.to_cents`
  (Decimal, exact). All comparison logic is in exact integer cents; floats are display-only.
