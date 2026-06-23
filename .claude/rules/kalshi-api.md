---
paths:
  - "kalshi_client.py"
  - "data.py"
  - "fetch.py"
---

# Kalshi API (verified live, 2026) — do not regress

- **Base URL:** `https://external-api.kalshi.com/trade-api/v2`. ⚠️ `api.kalshi.com` does **not** resolve.
- **No auth** for market data (`/series`, `/events`, `/markets`). Keys only matter for trading (out of scope).
- **Hierarchy:** Series → Event → Market(outcome). Paginate via `cursor` until empty.
- **Prices are fixed-point dollar STRINGS** (since Mar 2026): `yes_bid_dollars`, `yes_ask_dollars`,
  `last_price_dollars` (e.g. `"0.6500"`); sizes `*_size_fp`; volume `volume_fp`, `open_interest_fp`. An
  **empty book is `0.00/1.00`** — never a real 50%.
- **NO-side prices** (`no_bid_dollars`, `no_ask_dollars`) read directly (the "Buy NO" price); `no_ask ==
  1 − yes_bid` on the unified book. There are **no NO-side size fields** — a Buy-NO leg's tradable size
  is `yes_bid_size`; fallback Buy-NO cents = `100 − yes_bid_c` when `no_ask_c` is absent.
- **Market `status`** (`active`/`finalized`/`settled`/…): only `active` is tradable → drives `tradable_now`.
- **Web URL (verified):** `https://kalshi.com/markets/<series_lower>/<slug>/<event_lower>`,
  `slug = data._slugify(series.title)`; titles from `/series/<ticker>`
  (`kalshi_client.get_series_titles`), falling back to the series page when missing.
- **Identity:** the stable `custom_strike.*` UUID is the per-sport join key; `yes_sub_title` is the display name.

## Relevant tennis series
| Series | Meaning | kind | category |
|---|---|---|---|
| `KXATPMATCH`/`KXWTAMATCH` | match winner (head-to-head) | `match` | Match result |
| `KXITFMATCH`/`KXITFWMATCH` | ITF lower-tour match winner (exact-owned) | `match` | Match result |
| `KXATPADVANCE`/`KXWTAADVANCE` | reach a stage | `advance` | Stage advancement |
| `KXFOMEN`/`KXFOWOMEN` | win the tournament | `winner` | Tournament winner |
| `KXATPEXACTMATCH` | exact match score | `exact_score` | Exact score |
| `KXATPSETWINNER`/`KXWTASETWINNER` | set winner | `set_winner` | Set winner |

Match events are head-to-head (2 markets, `mutually_exclusive`); winner/advance/set/score are
single-sided. NBA/WNBA/MLB/NHL/golf/soccer/motorsport series are fully configured in `sports.py`.

## Rate limiting (free tier, do not regress)

Kalshi Basic read ≈ 20 req/s. `kalshi_client._throttle` caps issuance at `config.MAX_RPS` (15, ~75%);
`_get` backs off on 429 (honoring `Retry-After` when present) via `MAX_RETRIES`/`BACKOFF_*`; fan-out
`CONCURRENCY` (4). **The throttle is PROCESS-WIDE ONLY** — safe for ONE process; N processes each have
their own limiter (aggregate = `MAX_RPS × N`). Always loop the `cursor`; `get_paginated` raises if
`MAX_PAGES` (100) is hit with a cursor pending — **no silent truncation**.
