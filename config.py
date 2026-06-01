"""Configuration constants for the French Open Kalshi viewer.

Everything here is read-only market-data configuration. No credentials are needed:
Kalshi's market-data endpoints (series/events/markets) are public.
"""

# Kalshi public market-data API. NOTE: the reachable host is `external-api.kalshi.com`
# (the bare `api.kalshi.com` does not resolve).
BASE_URL = "https://external-api.kalshi.com/trade-api/v2"

# French Open per-player contracts are spread across many tennis series (match winner,
# stage advancement, tournament winner, set winner, exact score, ...). Rather than hardcode
# them, we DISCOVER tennis series dynamically (kalshi_client.discover_tennis_series) and then
# narrow to French Open events ourselves (data.is_french_open_event). These constants bound
# the discovery scan to the tennis universe.
TENNIS_SERIES_PREFIXES = ("KXATP", "KXWTA")

# Default fast scan: only these French Open per-player series are fetched unless the user
# opts into a full dynamic scan of every tennis series.
DEFAULT_SERIES = [
    "KXATPMATCH",
    "KXWTAMATCH",
    "KXATPADVANCE",
    "KXWTAADVANCE",
    "KXFOMEN",
    "KXFOWOMEN",
]

# A YES bid/ask spread at or below this (in dollars, i.e. 0.20 = 20c) is "reasonable" enough
# to trust the midpoint as the display price; wider books fall back to the last trade.
SPREAD_REASONABLE = 0.20

# Layer-consistency: ignore display-price gaps smaller than this many cents (noise).
DISPLAY_TOL_C = 1

# Kalshi web frontend base for per-series market pages.
KALSHI_WEB_BASE = "https://kalshi.com/markets"

# Tournament-winner series have non-prefixed tickers, so list them explicitly.
FO_WINNER_TICKERS = {
    "KXFOMEN",
    "KXFOWOMEN",
    "KXFOMENSINGLES",
    "KXFOWOMENSINGLES",
    "KXFOPENMENSINGLE",
    "KXFOPENWMENSINGLE",
}

# A market belongs to the French Open if its competition / title / rules mention any of
# these (case-insensitive). `product_metadata.competition` (e.g. "French Open Men Singles")
# is the primary, most reliable signal.
FO_KEYWORDS = ["french open", "roland garros", "roland-garros"]

# Fallback date window (UTC, padded) used ONLY when no keyword signal is present.
# Year-specific — update for future tournaments.
FO_WINDOW = ("2026-05-18", "2026-06-09")

# Optional display-name overrides keyed by Kalshi competitor UUID. Usually unnecessary
# since players are keyed by their stable competitor UUID, not by name.
NAME_ALIASES = {}

# HTTP behaviour.
USER_AGENT = "KalshiVisualizer/0.1 (read-only market data)"
REQUEST_TIMEOUT = 15  # seconds
MAX_PAGES = 50  # pagination safety cap
