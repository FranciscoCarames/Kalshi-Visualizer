"""Configuration constants for the Kalshi tennis viewer.

Everything here is read-only market-data configuration. No credentials are needed:
Kalshi's market-data endpoints (series/events/markets) are public.

These are DEFAULT constants only — config.py stays import-free by convention; env-var overrides for the
footprint knobs (retention, cadence, vacuum/checkpoint flags) are read at the boundaries that consume them
(store.py for the store tier; the scan scheduler for cadence), not here.
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

# NO-anchored structures ("Cheap bounded-loss NO fades") — a SPECULATIVE, opt-in, never-actionable section.
# Two tiers, both cheap convex fades (NOT edge, NOT arbitrage; gross, top-of-book, uncalibrated):
#   - BAND   : Buy NO on the deeper (child) rung + Buy YES on the broader (parent) rung that contains it —
#              a defined-risk band paying an extra $1 in the "reaches broader, not deeper" window. Emitted
#              only when cost ≥ 100¢ (cost < 100 is a STRICT executable cross owned by the consistency
#              checker) and the bounded max-loss (cost − 100) ≤ NO_STRUCTURE_BAND_MAX_LOSS_C — so storage
#              and the table stay focused on genuinely CHEAP bounded bets.
#   - OUTRIGHT: a single Buy NO (directional fade watchlist), emitted only when the Buy-NO cost ≤
#              NO_STRUCTURE_OUTRIGHT_MAX_C, so all-sport cheap NOs don't flood the store.
# The detector caps emission; the NiceGUI UI filters live (max-loss / max Buy-NO / quote / size).
NO_STRUCTURE_BAND_MAX_LOSS_C = 40           # widest band max-loss persisted (¢; cost ≤ 140¢)
NO_STRUCTURE_OUTRIGHT_MAX_C = 25            # dearest Buy-NO persisted for the outright watchlist (¢)
NO_STRUCTURE_DEFAULT_MAX_LOSS_C = 15        # default UI band max-loss filter (¢)
NO_STRUCTURE_DEFAULT_MAX_BUY_NO_C = 15      # default UI max Buy-NO cost filter (¢, outright + band child leg)

# Peer-relative cheapness flags (Phase 2 F) — a DISPLAY-ONLY badge, NOT a ranker and NEVER executable. Among
# SAME-SPORT bounded-loss bets within PEER_BAND_TOLERANCE_C ¢ of the same implied-payoff band (parent−child
# display gap), a bet is flagged "cheap" when its overpay (or its spread÷outright) sits at least
# PEER_CHEAP_MAD_K robust z-scores (median/MAD) BELOW the peer median. Needs ≥ PEER_MIN_COUNT same-sport
# peers, else it's left unflagged (insufficient peers). Gross, top-of-book, uncalibrated.
PEER_BAND_TOLERANCE_C = 5                    # ± band window (¢) defining "similar implied chance" peers
PEER_MIN_COUNT = 4                           # min same-sport in-band peers required to judge cheapness
PEER_CHEAP_MAD_K = 1.5                       # robust z-score (below peer median) to flag cheap

# World Cup game-support signal (#5): an ASK-IMPLIED support score (3·win_ask + draw_ask, summed over a
# team's 3 group games) — NOT expected points / not a probability (vig-biased upward). A team is FLAGGED
# (diagnostic-only) when its score is strong AND its qualify YES sits in a "moderately priced" band — i.e.
# the games look strong but the market hasn't fully priced qualification. Raw top-of-book cents; no de-vig.
WC_SUPPORT_SCORE_STRONG_C = 400              # min summed 3-game ask-support score to flag (¢)
WC_QUALIFIER_BAND_C = (35, 80)              # qualify YES ask in [lo, hi] ¢ (excludes longshots + near-locks)

# Exact-order top-two bundle — promotion from the Diagnostic tier to the review-only Speculative
# relative-value tier (a 12-leg Buy-YES "finish top two" bundle vs the direct qualifier YES comparator).
# A bundle is promoted ONLY when it is genuinely attractive: cheaper than the qualifier by at least
# MIN_SPECULATIVE_DISCOUNT_C, with cost < 100¢, no wide legs/comparator, and a real top-of-book size of
# at least MIN_SPECULATIVE_TOP2_UNITS. Otherwise it stays a Diagnostic reference row. NEVER arbitrage.
MIN_SPECULATIVE_DISCOUNT_C = 5               # min (qualifier YES ask − bundle cost) to promote (¢)
MIN_SPECULATIVE_TOP2_UNITS = 5              # min top-of-book size across the 12 bundle legs to promote

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
# Per-SPORT fetch fan-out (scanner.run_scan): how many sports fetch concurrently. Each sport's fetch
# already fans out across its series at CONCURRENCY, and the process-wide MAX_RPS throttle still caps
# total issuance — this only fills the idle gaps between sports (no extra Kalshi requests). Kept
# conservative (3) so nested fan-out stays under the HTTP connection pool; raise to 4 only after a
# benchmark. SPORT_FETCH_CONCURRENCY=1 reproduces the original serial scan exactly.
SPORT_FETCH_CONCURRENCY = 3
MAX_RETRIES = 5             # attempts per request before raising
BACKOFF_BASE = 1.0          # seconds; exponential backoff base for 429/5xx/network errors
BACKOFF_MAX = 30.0          # seconds; cap on a single backoff sleep

# --- Fee estimation (DISPLAY-ONLY) ---------------------------------------------------
# Kalshi's published general fee schedule: taker = ceil(0.07 x C x P x (1-P)),
# maker = ceil(0.0175 x C x P x (1-P)); the per-series/event `fee_multiplier` scales the base
# (most markets = 1). These base coefficients are configurable and confirmed in live smoke. Fees are an
# ESTIMATE and NEVER feed ranking/bucketing/actionability (see webui.viewmodel.net_of_fees).
FEE_TAKER_BASE_COEFF = 0.07        # general taker base (x effective multiplier)
FEE_MAKER_BASE_COEFF = 0.0175      # general maker base (x multiplier; maker-fee markets only)
FEE_DEFAULT_MULTIPLIER = 1.0       # labeled fallback when a known-quadratic series lacks a multiplier
FEE_METADATA_FETCH_ENABLED = True  # read fee_type/fee_multiplier from the series object (rides the title GET)
FEE_EVENT_OVERRIDE_FETCH_ENABLED = True   # sweep /events/fee_changes for event-level overrides
FEE_EVENT_OVERRIDE_MAX_PAGES = 10  # bound the override sweep; past it -> fail-closed to series-level
FEE_METADATA_TTL_SECONDS = 24 * 3600      # fee meta caches with the same TTL as series titles

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
# Server-safe default: 6h (was 30h). A left-running server at the old 30h x ~10s cadence steady-stated to
# ~28 GB and overheated the host (snapshot_count = retention / cadence; rows = 2,224/snapshot). 6h keeps a
# full day of lifecycle in the durable backlog table while bounding the heavy store. store.py reads the env
# override SNAPSHOT_RETENTION_SECONDS for rollback without a code change.
SNAPSHOT_RETENTION_SECONDS = 6 * 60 * 60   # 6 hours
# Lean opportunity tiering: keep FULL opportunity JSON for the latest N snapshots; for OLDER snapshots drop
# the heavy SPECULATIVE/diagnostic buckets' row JSON (counts preserved in snapshots.meta) so history stays
# bounded without touching store.latest() (the live feed). Mirrors the frame-retention tier. store.py reads
# env overrides (SNAPSHOT_OPP_FULL_RETENTION_N / SNAPSHOT_OPP_TIER_ENABLED) for rollback.
SNAPSHOT_OPP_FULL_RETENTION_N = 6
SNAPSHOT_OPP_TIER_ENABLED = True
SNAPSHOT_OPP_TIER_BUCKETS = ("no_structure", "data_quality", "near_miss")   # the heavy speculative tier
# Page reclamation: PRAGMA auto_vacuum=INCREMENTAL at init (fresh DBs) + a throttled incremental_vacuum and
# WAL checkpoint(TRUNCATE) in post-commit housekeeping so a long-running server's file actually shrinks after
# retention deletes. store.py reads env overrides (SNAPSHOT_INCREMENTAL_VACUUM_ENABLED /
# SNAPSHOT_WAL_TRUNCATE_ENABLED) for rollback. Housekeeping runs every Nth snapshot to avoid per-write churn.
SNAPSHOT_INCREMENTAL_VACUUM_ENABLED = True
SNAPSHOT_WAL_TRUNCATE_ENABLED = True
SNAPSHOT_HOUSEKEEPING_EVERY_N = 5
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

# --- Durable interval backlog (7-day opportunity history) -----------------------------
# A SECOND, lean backlog tier independent of the snapshot store above: store.write_snapshot maintains a
# `backlog_intervals` table recording each opportunity's open/closed lifecycle in a tracked CATEGORY, kept
# for this many seconds after it closes. This is the durable 7-day backlog (survives restarts, served by
# GET /backlog/events). The HEAVY snapshot store deliberately stays at SNAPSHOT_RETENTION_SECONDS (30h) —
# extending that to 7 days would be ~60k full snapshots; the interval table is one tiny row per lifecycle.
BACKLOG_RETENTION_SECONDS = 7 * 24 * 60 * 60   # 7 days
# Which dashboard `bucket` maps to which durable backlog category (store-side routing, derived from the
# already-promoted `bucket` so nothing is added to the public unified schema). Buckets not listed are NOT
# tracked. "statistical_arbitrage" is a RESERVED slot: when a detector lands it routes its bucket here with
# no schema migration (and no UI until then). risk_budget + near_miss are the bounded-loss opt-in candidates.
BACKLOG_CATEGORY_BY_BUCKET = {
    "actionable": "actionable",
    "risk_budget": "bounded_loss",
    "near_miss": "bounded_loss",
    # future: "<stat-arb bucket>": "statistical_arbitrage",
}
# UI-facing category labels (Stage 5). Statistical arbitrage is intentionally absent until a detector
# exists — the table accepts the string, but no tab is rendered for it.
BACKLOG_CATEGORY_LABELS = {
    "actionable": "Actionable",
    "bounded_loss": "Bounded-loss",
}

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

# Live order-book fetch for the Terminal SPA depth ladder (GET /api/terminal/orderbook). Read-only public
# market data; the endpoint serves a short per-ticker TTL cache and is sliding-window rate-limited so the
# ~5s frontend poll across tabs can never overwhelm the process-wide Kalshi throttle. Process-local.
ORDERBOOK_HTTP_MAX_PER_WINDOW = 30          # max live order-book fetches per window (per process)
ORDERBOOK_HTTP_WINDOW_SECONDS = 10

# --- Per-user authentication (auth_store.py / auth.py) --------------------------------
# Auth is a SEPARATE concern from the snapshot store: users live in their OWN SQLite file (AUTH_DB_PATH,
# env-overridable in serve.py/manage_users.py) so a snapshot-store reset (store._reset_to_fresh DROPs its
# tables on a bad migration) can NEVER touch credentials. config stays import-free — every env read lives
# at a boundary (serve.py / api.py / auth.py / manage_users.py). All durations are seconds.
AUTH_DB_PATH = "auth.db"                       # default; SNAPSHOT_DB_PATH-distinct (env override at boundary)
AUTH_SESSION_IDLE_SECONDS = 2 * 60 * 60        # re-login after this much INACTIVITY (sliding, re-set each
                                               #   request); strictly < the absolute cap so sliding is real
AUTH_SESSION_ABSOLUTE_SECONDS = 12 * 60 * 60   # hard cap on a session's life regardless of activity
AUTH_LOGIN_MAX_PER_WINDOW = 5                  # login attempts per (ip, username) before 429
AUTH_LOGIN_WINDOW_SECONDS = 60
AUTH_LOGIN_LIMITER_MAX = 4096                  # cap on the per-(ip,username) login-limiter map; stale
                                               #   entries are evicted at the cap so it can't grow unbounded
AUTH_LOCKOUT_THRESHOLD = 10                    # consecutive failures before a temporary account lockout
AUTH_LOCKOUT_SECONDS = 15 * 60                 # lockout duration (temporary — CLI `unlock` clears early)
AUTH_COOKIE_NAME = "kss_session"               # signed session cookie (itsdangerous, NOT NiceGUI's cookie)
AUTH_REMEMBER_COOKIE_NAME = "kss_remember"     # opt-in "stay signed in on this device" rotating token
AUTH_REMEMBER_MAX_AGE = 30 * 24 * 60 * 60      # remember-me token lifetime (30 days)
AUTH_MAX_CRED_LEN = 256                        # reject username/password longer than this BEFORE hashing
# Argon2id parameters (OWASP Password Storage minimums, 2024). Pinned so a deployment is reproducible and
# `needs_rehash` can upgrade old hashes when these change. time=2, 19 MiB, 1 lane.
AUTH_ARGON2_TIME_COST = 2
AUTH_ARGON2_MEMORY_COST = 19456                # KiB (= 19 MiB)
AUTH_ARGON2_PARALLELISM = 1

# Per-user preferences (auth_store `preferences` table). A versioned envelope is validated + sanitized
# server-side (NOT trusted from the client) and size-capped. The allowed-value sets are single-sourced
# here so the server sanitizer and any future consumer agree. Theme/preset/section names mirror the SPA.
AUTH_PREFS_MAX_BYTES = 32768                    # 32 KiB cap on the stored JSON blob (bounds abuse)
AUTH_PREFS_VERSION = 1                          # envelope version (bump when the prefs shape changes)
PREFS_THEMES = ("amber", "hc")
PREFS_LAYOUT_PRESETS = ("default", "triage", "inspect", "research", "blotterfull")
PREFS_SPLITS = ("all", "vertical", "calendar")
PREFS_AUTOREFRESH = ("10s", "30s", "off")
PREFS_COL_KEYS = ("opp", "risk", "nm", "no", "qs", "diag")   # colKeyOf() catalogs in columns.ts
PREFS_SETTINGS_BOOL = ("longShort", "showIds", "resolutionCriteria", "hideNetNegExec")
PREFS_TEXT_SIZES = ("compact", "normal", "large", "xlarge")   # discrete UI text-size steps (settings.textSize)
# The fixed singleton workspace panel ids — MANDATORY allow-list for the persisted custom layout
# (auth_store._clean_layout drops any id not here and dedupes). Mirrors the client PANEL_IDS in layout.ts.
PREFS_PANEL_IDS = ("p-blotter", "p-des", "p-ladder", "p-watch", "p-alerts", "p-research")
# Authenticated-action rate limits (per user) — register uses the login (ip,username) limiter; these guard
# the post-login state-changers so a debounce burst or a script can't hammer them.
AUTH_ACTION_LIMITS = {                          # action -> (max_events, window_seconds)
    "password": (10, 300),                      # password changes: 10 / 5 min
    "preferences": (60, 60),                    # prefs PUT: 60 / min (debounced client → generous)
    "device": (30, 60),                         # device revoke/logout: 30 / min
}

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
# Filter/threshold debounce (PR R): a burst of control changes (e.g. dragging "Max loss ¢") coalesces into
# ONE re-render this many seconds after the LAST change, instead of one synchronous rebuild per keystroke
# (which blocks the event loop → "connection lost"). A lightweight tick timer checks the idle deadline.
UI_DEBOUNCE_SECONDS = 0.3
UI_DEBOUNCE_TICK_SECONDS = 0.1

# --- In-process auto-scan scheduler (scan_scheduler.py) -------------------------------
# A single process-wide background loop that triggers the NON-force scan on a timer, so `python serve.py`
# auto-refreshes data without an external scheduler. One loop per process regardless of viewer count; each
# tick rides the ScanManager TTL/budget/singleflight guards. The UI exposes a toggle + interval selector.
AUTO_SCAN_INTERVAL_OPTIONS = [10, 15, 30, 60, 120]   # selectable seconds (>= SCAN_MIN_INTERVAL_SECONDS)
AUTO_SCAN_DEFAULT_SECONDS = 60                        # server-safe default (was 10). 10s hammered CPU
                                                      # (overheating) and 30h x 10s steady-stated the store to
                                                      # ~28 GB. 60s is a calm background refresh; an active
                                                      # user can still pick 10-15s from the selector and manual
                                                      # "Scan now" is never cadence-gated. The scan scheduler
                                                      # reads the env override AUTO_SCAN_DEFAULT_SECONDS.
                                                      # Original note: 10 > the 8s SCAN_MIN_INTERVAL and a scan is
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

# The Terminal Pro SPA (/terminal) is not a NiceGUI client, so it can't bump the presence COUNTER; instead
# its feed poll touches a heartbeat and the idle-gate treats a touch within this window as presence (so the
# background scan refreshes the snapshot while the SPA is open, and re-pauses this long after it closes).
# Kept > the SPA poll interval so an open tab stays active across one missed beat (hidden-tab throttling).
TERMINAL_PRESENCE_WINDOW_S = 30
