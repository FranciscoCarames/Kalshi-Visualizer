"""Configuration constants for the French Open Kalshi viewer.

Everything here is read-only market-data configuration. No credentials are needed:
Kalshi's market-data endpoints (series/events/markets) are public.
"""

# Kalshi public market-data API. NOTE: the reachable host is `external-api.kalshi.com`
# (the bare `api.kalshi.com` does not resolve).
BASE_URL = "https://external-api.kalshi.com/trade-api/v2"

# Tennis match series. These are generic across ALL tournaments, so we narrow them down
# to the French Open ourselves (see data.is_french_open_event).
SERIES = {
    "ATP": "KXATPMATCH",  # men's singles matches
    "WTA": "KXWTAMATCH",  # women's singles matches
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
