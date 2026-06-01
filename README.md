# Kalshi Visualizer — French Open Contract Viewer

A small read-only [Streamlit](https://streamlit.io/) app that pulls live
[Kalshi](https://kalshi.com/) prediction-market data for the **French Open** tennis
tournament, then lets you pick a player and compare **all of their French Open contracts**
— match results, stage advancement (reach Semifinal/Final), the tournament-winner market,
and more — sorted by implied odds, tournament stage, volume, or match time, with a bar chart.

## How it works

Kalshi organizes contracts as **Series → Event → Market(outcome)**, and a player's French
Open contracts are spread across *many* series. The app:

1. **Discovers** all tennis series dynamically (every `KXATP*`/`KXWTA*` series plus the
   named tournament-winner tickers like `KXFOMEN`/`KXFOWOMEN`).
2. **Fetches** their open events concurrently and keeps only French Open ones (by each
   event's `product_metadata.competition`, e.g. *"French Open Women Singles"*).
3. **Classifies** each per-player market by type — match result (`KX*MATCH`), stage
   advancement (`KX*ADVANCE`), tournament winner (`KXFOMEN`/`KXFOWOMEN`), set winner,
   exact score, etc.
4. **Indexes** every contract by the player's stable `tennis_competitor` UUID, so the same
   player merges across all series and rounds regardless of name formatting.

The YES mid-price of each market is that player's implied probability for that outcome.
Head-to-head match markets also show the opponent; winner/advancement markets are
single-sided and have none. Set-winner and exact-score markets are hidden by default.

Any series that fails to load is reported in the in-app **Debug** expander — never silently
dropped. Market data is **public** — no API key or authentication is required.

## Project layout

| File | Responsibility |
| --- | --- |
| `config.py` | Base URL, series tickers, FO keywords/date window |
| `kalshi_client.py` | Read-only HTTP client: paginated GET + retry/backoff |
| `data.py` | Parsing, French Open filtering, per-player contract index (no Streamlit) |
| `app.py` | Streamlit UI: player selector, sortable table, chart, refresh |

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
