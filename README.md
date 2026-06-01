# Kalshi Visualizer — French Open Contract Viewer

A small read-only [Streamlit](https://streamlit.io/) app that pulls live
[Kalshi](https://kalshi.com/) prediction-market data for the **French Open** tennis
tournament, then lets you pick a player and compare **all of their contracts across the
different matches (events)** they appear in — sorted by implied odds, match time, or
volume, with a quick bar chart.

## How it works

Kalshi organizes contracts as **Series → Event → Market(outcome)**:

- **Series** — `KXATPMATCH` (men's matches) and `KXWTAMATCH` (women's matches). These are
  generic across all tournaments, so the app filters them down to the French Open using
  each event's `product_metadata.competition` (e.g. *"French Open Men Singles"*), with
  title/rules keywords and a tournament date window as fallbacks.
- **Event** — one match, e.g. *"Mensik vs Fonseca"*.
- **Market** — one *"Will &lt;player&gt; win?"* binary per player. The YES mid-price is that
  player's implied win probability. Players are keyed by their stable Kalshi
  `tennis_competitor` UUID so the same player links across rounds regardless of name
  formatting.

Market data is **public** — no API key or authentication is required.

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
