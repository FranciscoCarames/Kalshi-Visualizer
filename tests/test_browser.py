"""Headless browser smoke tests (PR 26c) — render the real NiceGUI dashboard page in-process via
nicegui.testing.User (no selenium) and assert the key sections show. Catches page-BODY render regressions
the pure-builder unit tests can't (the body builds on websocket connect). The dashboard reads the engine
in-process, so a standalone NiceGUI app over a seeded tmp store renders fully — no FastAPI mount / HTTP
needed.

Anything that needs a REAL browser (a native file-download dialog, websocket reconnect) is out of scope for
the headless User and is covered by the manual "Before hosting" checks instead (docs/DEPLOYMENT.md).
"""
from __future__ import annotations

import pytest
from nicegui.testing import User

import config
import presence
import scan_manager
import store
from webui import engine

MAIN = "tests/nicegui_main.py"


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    """Point the engine at a fresh tmp store and isolate the process-global singletons the dashboard reads."""
    db = str(tmp_path / "browser.db")
    monkeypatch.setattr(config, "SNAPSHOT_DB_PATH", db)   # engine reads this when db_path is None
    engine._FRAME_CACHE.clear()
    scan_manager.manager.reset()
    presence.reset()
    return db


def _actionable_opp():
    return {
        "opportunity_id": "o1", "sport": "tennis", "sport_label": "Tennis", "bucket": "actionable",
        "name": "Player One", "detail": "Reach Final ⊇ Win", "source": "containment", "tournament": "FO",
        "exec_gap_c": 4, "exec_min_size": 10, "exec_max_profit_dollars": 0.4, "participant_key": "p1",
        "relationship_type": "containment", "action_1_text": "Buy YES", "action_2_text": "Buy NO",
        "market_status": "active", "tradable_now": "Yes",
    }


def _contracts():
    return [{"player_key": "p1", "series": "KXATPADVANCE", "ladder_node": "Reach Final", "kind": "advance",
             "display_pct": 40, "display_c": 40, "yes_bid_pct": 38, "yes_ask_pct": 42, "quote_quality": "OK",
             "contract": "Reach Final", "category": "Stage advancement", "stage_rank": 2,
             "ladder_eligible": True, "mapping_confidence": "high", "status": "active", "kalshi_url": "u"}]


def _seed(db, opps, *, frames=None):
    store.write_snapshot("2026-06-05 12:00:00 UTC", opps, frames=frames or [], db_path=db)


# --- render + sections ----------------------------------------------------------------
@pytest.mark.nicegui_main_file(MAIN)
async def test_renders_core_sections(user: User, seeded_db) -> None:
    _seed(seeded_db, [_actionable_opp()],
          frames=[{"sport": "tennis", "frame_type": "contracts", "schema_version": 1, "rows": _contracts()}])
    await user.open("/")
    await user.should_see("Kalshi Opportunity Engine")     # header (no emoji)
    await user.should_see("Actionable — executable gross edges")
    await user.should_see("Review Required — settlement-dependent")   # clearer rename of "Review signal"
    await user.should_see("Bounded-Loss Bets")             # split watchlist section 1 (switch on by default)
    await user.should_see("Overpriced Books")              # split watchlist section 2
    await user.should_see("Diagnostics & Debug")
    await user.should_see("Refresh snapshot")               # the manual refresh/scan button
    await user.should_not_see("🆕")                         # professional pass: no childish emojis
    await user.should_not_see("🎯")


# --- truthful empty states (PR 26a) ---------------------------------------------------
@pytest.mark.nicegui_main_file(MAIN)
async def test_empty_state_no_scan(user: User, seeded_db) -> None:
    await user.open("/")                                    # empty store → no snapshot
    await user.should_see("No scan yet")


@pytest.mark.nicegui_main_file(MAIN)
async def test_empty_state_no_opportunities(user: User, seeded_db) -> None:
    _seed(seeded_db, [])                                    # a scan ran but found nothing
    await user.open("/")
    await user.should_see("no opportunities right now")


# --- P2: the poll surfaces a snapshot written AFTER the page opened (no re-open / manual refresh) ----
@pytest.mark.nicegui_main_file(MAIN)
async def test_new_snapshot_surfaces_via_poll(user: User, seeded_db, monkeypatch) -> None:
    # Deterministic, not a wall-clock gamble: `should_see` waits only ~0.3s (3 retries x 0.1s), but the
    # dashboard poll fires every config.UI_POLL_SECONDS (default 1s), so the default wait races the timer
    # and flakes. Shrink the interval BEFORE open (the ui.timer is created during open) and give should_see
    # a window comfortably longer than the interval.
    monkeypatch.setattr(config, "UI_POLL_SECONDS", 0.1)
    await user.open("/")
    await user.should_see("No scan yet")                    # empty store at open
    store.write_snapshot("2026-06-05 12:00:00 UTC", [_actionable_opp()],
                         meta={"scanned": 3, "loaded": 3, "failed": 0}, db_path=seeded_db)
    await user.should_see("3 series", retries=40)           # ~4s window >> 0.1s poll -> no race


# --- detail + diagnostics sections render (PR 24/25b) ---------------------------------
# NOTE: the headless User sees server-side elements/labels, NOT Quasar table / AG-Grid ROW DATA (rendered
# client-side) and cannot drive table-ROW selection (a content click doesn't fire the table's on_select).
# So the actionable-row text and the click→open-detail interaction are manual checks
# (docs/DEPLOYMENT.md "Before hosting"). Here we assert the detail + diagnostics SECTIONS build without error; the
# detail/diagnostics CONTENT builders are exhaustively unit-tested (test_viewmodel / test_webui).
@pytest.mark.nicegui_main_file(MAIN)
async def test_detail_and_diagnostics_sections_render(user: User, seeded_db) -> None:
    _seed(seeded_db, [_actionable_opp()],
          frames=[{"sport": "tennis", "frame_type": "contracts", "schema_version": 1, "rows": _contracts()}])
    await user.open("/")
    await user.should_see("Selected Detail — click a row")   # the (click-to-fill) detail section exists
    await user.should_see("Category honesty")                # diagnostics content rendered (Labels)
    await user.should_see("Sum of independent row maxima")   # the honest metric label
    await user.should_see("Full diagnostics")                # the full-diagnostics AG-Grid section header


# --- UX defaults (PR S5) --------------------------------------------------------------
@pytest.mark.nicegui_main_file(MAIN)
async def test_ux_defaults_render(user: User, seeded_db) -> None:
    """The Dark mode toggle and the Blocked toggle (hidden by default) render. The selected-row highlight +
    the resolution-criteria expansion need a real row-click selection, which the headless User can't drive —
    manual checks (docs/DEPLOYMENT.md "Before hosting")."""
    _seed(seeded_db, [_actionable_opp()],
          frames=[{"sport": "tennis", "frame_type": "contracts", "schema_version": 1, "rows": _contracts()}])
    await user.open("/")
    await user.should_see("Dark mode")                       # PR S5 theme toggle (now in the settings dialog)
    await user.should_not_see("fees / depth / collateral not fully modeled")  # disclosure sentence removed
    await user.should_see("Blocked")                         # toggle still present (default off)


# --- market telemetry is its own "not an opportunity signal" section (PR 6) -----------
@pytest.mark.nicegui_main_file(MAIN)
async def test_market_telemetry_is_a_labelled_non_signal_section(user: User, seeded_db) -> None:
    _seed(seeded_db, [_actionable_opp()])
    await user.open("/")
    await user.should_see("Market Telemetry — Liquidity & Volatility")   # collapsed; liquidity lives here now


# --- scan-in-progress indicator (UI trust fix 1) ---------------------------------------
# During a scan the dashboard otherwise silently shows the previous snapshot; the label makes the
# in-flight refresh visible for EVERY scan source (scheduler, another LAN viewer, POST /scan), not
# just this client's "Scan now" button. manager state is isolated by the seeded_db fixture's reset().
_SCANNING_TEXT = "Scanning — new data shortly"


@pytest.mark.nicegui_main_file(MAIN)
async def test_scanning_indicator_shows_when_scan_in_flight_at_open(user: User, seeded_db) -> None:
    _seed(seeded_db, [_actionable_opp()])
    scan_manager.manager._status["status"] = "in_progress"   # fake an in-flight scan (status() copies this)
    await user.open("/")
    await user.should_see(_SCANNING_TEXT)                    # painted by the post-build tick_age() call


@pytest.mark.nicegui_main_file(MAIN)
async def test_scanning_indicator_hidden_when_idle(user: User, seeded_db) -> None:
    _seed(seeded_db, [_actionable_opp()])
    await user.open("/")                                     # fixture reset() → status "idle"
    await user.should_not_see(_SCANNING_TEXT)


@pytest.mark.nicegui_main_file(MAIN)
async def test_scanning_indicator_appears_via_tick(user: User, seeded_db) -> None:
    _seed(seeded_db, [_actionable_opp()])
    await user.open("/")
    await user.should_not_see(_SCANNING_TEXT)
    scan_manager.manager._status["status"] = "in_progress"   # scan starts AFTER the page opened
    await user.should_see(_SCANNING_TEXT)                    # should_see retries past the 1s tick (P2 pattern)
