"""Configuration constants for the Kalshi tennis viewer.

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

# Near-edge watchlist (trader dashboard): a CLEAN row whose firm executable gap (child bid − parent
# ask, in cents) is within this many cents BELOW zero is "close to actionable" and surfaced on the
# near-edge watchlist (e.g. -5 → gaps in [-5, 0]). Tight/OK quotes only; never a buy instruction.
NEAR_EDGE_MIN_C = -5

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
# Pagination safety cap. The full /series list is ~10.5k rows at limit=200 (~53 pages), so the
# cap must comfortably exceed that; hitting it now signals genuine truncation (surfaced as an error).
MAX_PAGES = 100

# --- Rate limiting (stay safely under Kalshi's Basic/free tier) ----------------------
# Kalshi Basic tier: read budget 200 tokens/s, a standard GET costs 10 tokens -> ~20 read req/s
# (verified from docs.kalshi.com/getting_started/rate_limits). We cap at ~25% of that.
# NOTE: this limiter is PROCESS-WIDE only — it bounds one Python process. If the app runs as several
# processes / containers / replicas, each has its own limiter and the aggregate rate is
# MAX_RPS x process_count. A large horizontal scale-out would need a shared/distributed limiter.
MAX_RPS = 5                 # max requests/second issued by this process (≈25% of the ~20/s ceiling)
CONCURRENCY = 4             # thread-pool workers for the per-series fan-out (throttle paces them)
MAX_RETRIES = 5             # attempts per request before raising
BACKOFF_BASE = 1.0          # seconds; exponential backoff base for 429/5xx/network errors
BACKOFF_MAX = 30.0          # seconds; cap on a single backoff sleep

# --- Auto-refresh cadence ------------------------------------------------------------
REFRESH_OPTIONS = [60, 120, 300]   # selectable auto-refresh intervals (seconds)
REFRESH_DEFAULT_SECONDS = 120      # conservative default (safe even for the heavier full scan)
FULL_SCAN_MIN_INTERVAL = 120       # full scan is heavy: never auto-refresh faster than this
REFRESH_TTL = 30                   # load_contracts cache TTL (≤ smallest interval -> each tick refetches)
FRESHNESS_TICK_SECONDS = 1         # data-age / stale strip re-renders every second (no refetch — cache read)

# --- Display / timezone --------------------------------------------------------------
# Timestamps are computed in UTC; the dashboard converts to the user's chosen zone for DISPLAY ONLY
# (never for the exact-cents comparison logic). Lisbon is the owner's local zone and the default.
TIMEZONE_DEFAULT = "Europe/Lisbon"
TIMEZONE_OPTIONS = [
    "Europe/Lisbon", "UTC", "Europe/London", "Europe/Paris",
    "America/New_York", "America/Chicago", "America/Los_Angeles",
]
# Data older than this many seconds is flagged stale in the main-dashboard freshness strip.
STALE_AFTER_SECONDS = 300

# --- Snapshot store (Stage 1 — opportunity history) ----------------------------------
# Standalone single-writer SQLite file persisting one snapshot of opportunities per refresh
# (store.py). A relative path (resolved against the process working dir) keeps config import-free;
# the file is gitignored. Pass an explicit path in tests.
SNAPSHOT_DB_PATH = "snapshots.db"
# Retention: drop snapshots older than this many seconds (relative to the newest stored snapshot, so
# retention is deterministic/testable). Sized above the largest planned backlog window (24h, Stage 3)
# plus margin, so the lifecycle/backlog views always have enough history.
SNAPSHOT_RETENTION_SECONDS = 30 * 60 * 60   # 30 hours
# SQLite busy-timeout (ms): how long a connection waits on a held lock before raising. With WAL mode
# (set per-connect in store._connect) this lets a reader proceed during a scan write instead of erroring.
SNAPSHOT_BUSY_TIMEOUT_MS = 5000
# Heavy-frame retention (v3 size-tier, store._apply_frame_retention): the lean opportunity history keeps
# the 30h window above, but the heavy per-sport evidence frames (contracts/checks/dutchbooks) are capped to
# the latest N snapshots under a logical-byte budget — older snapshots keep their opportunities but their
# evidence is evicted ("evidence expired"). Tune once PR 21 lets us measure real frame sizes.
SNAPSHOT_FRAME_RETENTION_N = 12                      # keep heavy frames for the latest 12 snapshots
SNAPSHOT_FRAME_DB_BUDGET_BYTES = 500 * 1024 * 1024   # hard cap on retained frame data (~500 MB)

# --- Lifecycle (Stage 3 — alerts + recently-actionable backlog) ----------------------
# Recently-actionable backlog windows (§10): label -> seconds. "This session" is a sentinel the app
# resolves to the app/process start time. 1 hour is the default.
BACKLOG_WINDOWS = {
    "15 min": 15 * 60,
    "1 hour": 60 * 60,
    "4 hours": 4 * 60 * 60,
    "24 hours": 24 * 60 * 60,
    "This session": None,
}
BACKLOG_DEFAULT = "1 hour"
# New-actionable banner persistence (§8). "Until next refresh" -> single-transition diff (window None);
# the "N minutes" modes keep a still-actionable new row in the banner for that long. (No "until
# acknowledged" yet — that needs a NiceGUI ack at Stage 5.)
ALERT_PERSISTENCE_OPTIONS = {
    "Until next refresh": None,
    "5 minutes": 5 * 60,
    "15 minutes": 15 * 60,
}

# --- FastAPI engine service (Stage 4) ------------------------------------------------
API_HOST = "127.0.0.1"
API_PORT = 8000
# POST /scan is rate-guarded against the latest STORED snapshot: a new scan is skipped (returns the
# latest result marked skipped, writes nothing) when the newest snapshot is younger than this, unless
# ?force=true. Sane after a restart because the guard reads the store, not process memory.
SCAN_MIN_INTERVAL_SECONDS = REFRESH_TTL   # 30s
# Non-blocking /scan (PR 21b): POST /scan returns 202 immediately and the scan runs in a background thread
# (process-local ScanManager singleflight). `?wait=true` joins the in-flight scan up to this bound, then
# returns 202 regardless (still non-blocking past the bound).
SCAN_WAIT_TIMEOUT_SECONDS = 60
# Scan budget: after a scan that blows ANY of these caps, the ScanManager cools down — the next
# non-forced trigger is skipped (so a pathological scan can't hammer Kalshi every tick). `?force=true`
# overrides the cooldown.
SCAN_BUDGET_MAX_SECONDS = 120
SCAN_BUDGET_MAX_REQUESTS = 2000
SCAN_BUDGET_MAX_FAILED_SERIES = 20
SCAN_BUDGET_COOLDOWN_SECONDS = 300

# --- NiceGUI dashboard (Stage 5) -----------------------------------------------------
# NiceGUI needs a storage secret to sign its per-user session cookie. There is NO auth/multi-user here,
# so this is not a real secret — the REAL value comes from the NICEGUI_STORAGE_SECRET env var (read in
# serve.py, which may import os); this is only a clearly-labeled dev-only fallback. (config stays
# import-free per the project convention, so the env read lives in serve.py, not here.)
NICEGUI_STORAGE_SECRET_FALLBACK = "dev-only-not-a-secret-set-NICEGUI_STORAGE_SECRET-in-prod"
UI_REFRESH_SECONDS = REFRESH_DEFAULT_SECONDS   # NiceGUI poll cadence for re-reading the store (120s)
