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

# --- "Beyond the strict rule" — risk-budget candidates + near-miss books (NiceGUI; integer cents only) ---
# Risk-budget candidates: containment trades that cost SLIGHTLY over 100¢ — bounded downside, CONVEX upside
# (the broader-but-not-deeper state pays an extra $1). The scanner persists candidates whose worst-case
# loss is up to RISK_BUDGET_MAX_LOSS_C cents; the NiceGUI UI filters live by max-loss + min upside:risk.
# These are NOT arbitrage — a small bounded loss bought for a large convex payoff. GROSS of fees.
RISK_BUDGET_MAX_LOSS_C = 25                 # widest worst-case loss persisted (≈ cost 1.25 vs 1.00 floor)
RISK_BUDGET_DEFAULT_MAX_LOSS_C = 5          # default UI max-loss filter (¢)
RISK_BUDGET_DEFAULT_MIN_RATIO_TENTHS = 0    # default min upside:risk × 10 (0 = off; e.g. 30 = 3.0:1)
# Probability-context filters (display outright, NOT executable; 0 = off, band-defaults-to-0 convention).
# "spread / outright" is scale-invariant so the rank mode is led by the deeper outright's magnitude; the
# min-outright floor is what actually removes longshots, the max-ratio caps relative risk.
RISK_BUDGET_DEFAULT_MIN_OUTRIGHT_C = 0       # min deeper (child) display outright ¢ (0 = off)
RISK_BUDGET_DEFAULT_MAX_SPREAD_RATIO_HUNDREDTHS = 0  # max child display_spread/outright × 100 (0 = off; 75 = 0.75)
# Near-miss dutch books: a MECE book overpriced by up to NEAR_MISS_MAX_OVER_C cents over its payout floor —
# FLAT payout, so a guaranteed gross LOSS as a bundle. Watchlist only; a small band is all that's useful.
NEAR_MISS_MAX_OVER_C = 5                     # widest overpay persisted (¢ over the payout floor)
NEAR_MISS_DEFAULT_OVER_C = 3                 # default UI max-overpay filter (¢)

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
# (verified from docs.kalshi.com/getting_started/rate_limits). We cap at ~75% of that, leaving headroom.
# A full cross-sport scan is only ~49 GETs, so the burst is brief (~3.3s at 15/s). The HARD floor against
# a ban is the 429 exponential backoff in kalshi_client._get (it honors a Retry-After header WHEN the 429
# carries one — Kalshi may omit it — otherwise it backs off exponentially).
# NOTE: this limiter is PROCESS-WIDE only — it bounds one Python process. 15/s is safe for a SINGLE
# process; do not run WEB_CONCURRENCY>1 / `uvicorn --workers N` / multiple replicas without a shared
# limiter, since each keeps its own and the aggregate rate is MAX_RPS x process_count (serve.py warns).
MAX_RPS = 15                # max requests/second issued by this process (~75% of the ~20/s Basic ceiling)
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
# Lookback for the "most volatile now" message (#12b). Actual span is bounded by frame retention above
# (the latest N snapshots' contract frames); this just widens the candidate window + labels the wording.
VOLATILITY_WINDOW_SECONDS = 15 * 60

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
# Explicitly 8s (not tied to REFRESH_TTL) so the in-process auto-scan scheduler's fastest interval (10s,
# see AUTO_SCAN_INTERVAL_OPTIONS) actually re-fetches instead of being TTL-skipped. Still bounds how often
# any non-forced trigger (scheduler / button / POST /scan) hits Kalshi.
SCAN_MIN_INTERVAL_SECONDS = 8
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
# Scan-token gate (PR 26b): when the SCAN_TOKEN env var is set, HTTP `POST /scan` requires a matching
# `X-Scan-Token` header (off by default — env read lives in api.py, keeping config import-free). These
# cap how often the HTTP /scan endpoint itself can be hit (per process), distinct from the scan TTL above.
SCAN_HTTP_MAX_PER_WINDOW = 10
SCAN_HTTP_WINDOW_SECONDS = 60

# --- NiceGUI dashboard (Stage 5) -----------------------------------------------------
# NiceGUI needs a storage secret to sign its per-user session cookie. There is NO auth/multi-user here,
# so this is not a real secret — the REAL value comes from the NICEGUI_STORAGE_SECRET env var (read in
# serve.py, which may import os); this is only a clearly-labeled dev-only fallback. (config stays
# import-free per the project convention, so the env read lives in serve.py, not here.)
NICEGUI_STORAGE_SECRET_FALLBACK = "dev-only-not-a-secret-set-NICEGUI_STORAGE_SECRET-in-prod"
UI_POLL_SECONDS = 1       # dashboard poll cadence (P2): a cheap `store.latest_snapshot_id()` probe that
                          # re-reads + re-renders ONLY when a new snapshot lands, so a completed scan
                          # surfaces to every browser within ~1s. Idle ticks do almost nothing.
UI_REFRESH_SECONDS = 10   # legacy heavy timed-rebuild cadence (pre-P2). Superseded by UI_POLL_SECONDS;
                          # kept for compatibility / any external reference.

# --- In-process auto-scan scheduler (scan_scheduler.py) -------------------------------
# A single process-wide background loop that triggers the NON-force scan on a timer, so `python serve.py`
# auto-refreshes data without an external scheduler. One loop per process regardless of viewer count; each
# tick rides the ScanManager TTL/budget/singleflight guards. The UI exposes a toggle + interval selector.
AUTO_SCAN_INTERVAL_OPTIONS = [10, 15, 30, 60, 120]   # selectable seconds (>= SCAN_MIN_INTERVAL_SECONDS)
AUTO_SCAN_DEFAULT_SECONDS = 10                        # default cadence (P3): aggressive ~10s so the P2
                                                      # 1s poll has fresh data to surface. 10 > the 8s
                                                      # SCAN_MIN_INTERVAL (no TTL-skip) and a full scan is
                                                      # ~3-4s of rate-limited GETs, so ticks never overlap;
                                                      # the budget/cooldown guards stay as the safety floor.
AUTO_SCAN_DEFAULT_ENABLED = True                      # auto-refresh on by default
# Presence gate (P4): pause the background auto-scan while NO viewer is connected, resuming on the next
# tick after someone opens the dashboard — so the app stops hitting Kalshi when nobody's watching. The
# manual "Scan now" button is NOT gated. Trade-off: a headless REST-only consumer (no browser → 0 viewers)
# gets stale data while idle; set this False to keep scanning regardless of viewers. The env override
# AUTO_SCAN_PAUSE_WHEN_IDLE=0 (read in serve.resolve_pause_when_idle) selects the headless 24/7 mode at
# deploy time without editing code.
AUTO_SCAN_PAUSE_WHEN_IDLE = True
