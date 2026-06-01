# Kalshi Visualizer — French Open Contract Viewer

A small read-only [Streamlit](https://streamlit.io/) app that pulls live
[Kalshi](https://kalshi.com/) prediction-market data for the **French Open** tennis
tournament, then lets you pick a player and see **all of their French Open contracts** in one
table — match results, stage advancement (reach Semifinal/Final), and the tournament-winner
market — with a clear breakdown of every price component.

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
| `data.py` | Parsing, French Open filtering, per-player contract index (no Streamlit) |
| `app.py` | Streamlit UI: player selector, category filter, contract table, debug expander |

## Setup & run

```bash
pip install -r requirements.txt
streamlit run app.py
```

The app opens in your browser. Use the **Refresh data** button to fetch a fresh snapshot
(data is otherwise cached for 60 seconds).

## Notes

- Read-only / on-demand snapshot. No trading, no stored history.
- The French Open date window in `config.py` is year-specific — update it for future
  tournaments.
- If there are no open match contracts (e.g. a rest day between rounds), the app shows an
  informational message rather than an empty table.
