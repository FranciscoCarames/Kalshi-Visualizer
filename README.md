# Kalshi Visualizer — French Open Contract Viewer

A small read-only [Streamlit](https://streamlit.io/) app that pulls live
[Kalshi](https://kalshi.com/) prediction-market data for the **French Open** tennis
tournament. It surfaces **layer-consistency issues** (a deeper outcome must not price above a
prerequisite — e.g. *Win Tournament ≤ Reach Final ≤ Reach Semifinal*) and lets you drill into
any player's full set of contracts with a clear breakdown of every price component.

## Layer Consistency Checker

The main table compares contracts that have a provable logical **containment** relationship and
flags **executable inconsistencies** (a firm bid/ask cross with order size behind it). It is
deliberately conservative:

- **Executable test** uses firm YES bid/ask **and positive order sizes**, compared in exact
  integer cents. A child YES bid above the parent YES ask is `EXECUTABLE_VIOLATION` (the only
  *Broken* status).
- **Display test** compares the display %; a breach is `DISPLAY_VIOLATION` (a *Warning*, since it
  may not be tradable).
- Wide/empty books, missing sizes, missing layers, and unprovable relationships are surfaced as
  `WIDE_QUOTE` / `MISSING_QUOTE` / `QUOTE_SIZE_MISSING` / `MISSING_LAYER` / `UNKNOWN_RELATIONSHIP`
  — **never** mislabelled as violations.
- **Match-alignment** rows (winning your current match ⇔ reaching the next stage) are included
  only when the round maps confidently, and always carry a `RULE_CHECK_REQUIRED` /
  `RULE_MISMATCH` flag: findings are called *executable inconsistencies*, **not arbitrage**,
  because the two markets' settlement rules are not auto-verified.

## How it works

Kalshi organizes contracts as **Series → Event → Market(outcome)**, and a player's French
Open contracts are spread across *several* series. The app:

1. **Fetches** a default set of core French Open series (`KXATPMATCH`, `KXWTAMATCH`,
   `KXATPADVANCE`, `KXWTAADVANCE`, `KXFOMEN`, `KXFOWOMEN`). An optional **"Scan all tennis
   series"** checkbox dynamically discovers every `KXATP*`/`KXWTA*` series for extra contract
   types (set winner, exact score, …).
2. Keeps only French Open events (by each event's `product_metadata.competition`,
   e.g. *"French Open Women Singles"*) and **classifies** each market by type.
3. **Indexes** every contract by the player's stable `tennis_competitor` UUID, so the same
   player merges across all series and rounds regardless of name formatting.

### Pricing columns
Rather than a single "implied %", each row breaks out the price:

- **Display %** — the YES midpoint if the bid/ask spread is reasonable, otherwise the last
  trade, otherwise blank.
- **YES mid % / Last % / YES bid % / YES ask % / Spread ¢** — the raw components.
- **Quote** — quality flag (Tight / OK / Wide / Very wide / No quote) so an unreliable price
  is obvious.

Head-to-head match markets show the opponent and a real **Match time**; winner/advancement
markets are single-sided (no opponent) and show their **Close time** instead. Each row links
to the contract's Kalshi series page. Set-winner and exact-score markets are hidden by default.

Any series that fails to load is reported in the in-app **Debug** expander (alongside the raw
market fields) — never silently dropped. Market data is **public** — no API key required.

## Project layout

| File | Responsibility |
| --- | --- |
| `config.py` | Base URL, series tickers, FO keywords/date window |
| `kalshi_client.py` | Read-only HTTP client: paginated GET + retry/backoff |
| `data.py` | Parsing, French Open filtering, per-player contract index, cent-exact prices/sizes (no Streamlit) |
| `consistency.py` | Layer-consistency chains + classifier (no Streamlit) |
| `app.py` | Streamlit UI: main consistency table + player detail; right-hand controls/filters |

## Setup & run

```bash
pip install -r requirements.txt
streamlit run app.py
```

The app opens in your browser. Use the **Refresh data** button to fetch a fresh snapshot
(data is otherwise cached for 60 seconds).

## Tests

Pure logic in `data.py` and `consistency.py` is covered by unit tests (no network):

```bash
pip install -r requirements-dev.txt
pytest -q
```

## Mapping audit

Each contract carries a `mapping_confidence` (high when keyed to the stable Kalshi
`tennis_competitor` UUID; low for a name-only fallback) and a reason. The per-player detail view
shows an explicit **expected-vs-found** progression ladder (so a missing layer is obvious, not
implied), and offers a **per-player export** (JSON snapshot + CSV) of the contracts and their
consistency comparisons for offline mapping review.

Directly beneath the progression ladder, the detail view also shows **raw stage-ladder spreads** —
the percentage-point and cents gaps between adjacent layers (`Reach Semifinal → Reach Final → Win
Tournament`). These are raw price differences only (not a probability model); an inverted spread is
the same inconsistency the consistency table flags.

## Notes

- Read-only / on-demand snapshot. No trading, no stored history.
- The French Open date window in `config.py` is year-specific — update it for future
  tournaments.
- If there are no open match contracts (e.g. a rest day between rounds), the app shows an
  informational message rather than an empty table.
