---
name: kalshi-visualizer-canonical-kb
created: 2026-06-02
last_updated: 2026-06-04
---


# Canonical Knowledge Base

Cross-topic insights distilled from session work. Update via `distill`.

Organize entries into the three sections below. Add entries newest-on-top within each section.

## Insights

### 2026-06-04 — Kalshi exact-score markets settle to "Fair Market Price" on retirement

**Source:** full-tennis-coverage / m5-synthetic-bundle-detector
**What:** Verified live in `rules_secondary`: if a tennis match ends in a **retirement** (or no ball is played), an exact-set-score market that "cannot be unconditionally settled" resolves to **Fair Market Price** (exchange discretion), while the match-winner / reach-round markets settle cleanly (the player still advances). So a bundle of {exact scores} priced against a match-winner is NOT riskless on abnormal endings.
**Why it matters:** This is *the* reason synthetic exact-score bundles are always settlement-caveated (`SETTLEMENT_CHECK_REQUIRED`, review-only, never Actionable). Any future cross-family check linking exact-score to a winner/advance market (e.g. seed S8) must carry the caveat — never treat them as guaranteed arbitrage.

### 2026-06-04 — Tennis match format (bo5 vs bo3) is NOT tour-based; scoreline is a structured field

**Source:** full-tennis-coverage / m5-synthetic-bundle-detector
**What:** ATP ≠ always best-of-5 — only **men's Grand Slam singles** are bo5 ({3-0,3-1,3-2}); WTA and non-Slam ATP are bo3 ({2-0,2-1}). Derive format from competition (Grand-Slam keyword) **AND** gender (division), never the tour alone. The set score is a **structured** field — `custom_strike["Set Score"] = "3-0"` (alongside the `tennis_competitor` UUID) — so no title regex is needed to parse it.
**Why it matters:** A tour-keyed format guess silently mis-sizes the expected score set and kills detection. Read `custom_strike["Set Score"]` directly; resolve format via `SportConfig.score_format_fn` (Grand-Slam + gender).

### 2026-06-02 — "Executable inconsistency", never "arbitrage"

**Source:** kalshi-visualizer / CONTEXT.md harvest
**What:** Findings are always called "executable inconsistencies", never "arbitrage". True arbitrage additionally requires the two markets' settlement *rules* to match, which the app cannot auto-verify — so cross-market (match-alignment) pairs always carry `RULE_CHECK_REQUIRED`.
**Why it matters:** This naming discipline is an owner constraint to avoid overclaiming. It governs all user-facing copy (page title, glossary, status labels) — a single "arbitrage" slip is a regression.

### 2026-06-02 — AUDIT-002: DISPLAY_VIOLATION takes precedence over QUOTE_SIZE_MISSING

**Source:** kalshi-visualizer / CONTEXT.md harvest
**What:** When a price-cross has no firm size AND the display prices also cross, the status is `DISPLAY_VIOLATION` (Warning), not `QUOTE_SIZE_MISSING` (Missing data). A reviewer (Codex) preferred strict `QUOTE_SIZE_MISSING`; the owner chose to keep `DISPLAY_VIOLATION` because a display cross is the more informative signal.
**Why it matters:** This is a deliberate product decision, not a bug. Anyone "fixing" it to strict QUOTE_SIZE_MISSING is reverting an owner call — see the inline comment in `consistency.py` and the note in CLAUDE.md.

### 2026-06-02 — Read-only, public-data-only scope

**Source:** kalshi-visualizer / CONTEXT.md harvest
**What:** The project started from a `.env` with a Kalshi API key + RSA key, but the app only needs public market data (no auth). The credentials were removed and the scope locked to read-only.
**Why it matters:** Trading, auth, order placement, and account access are out of scope unless the owner explicitly lifts the guard. Nothing here needs a key; never re-introduce one.

### 2026-06-02 — Liquidity reality: most ladder markets are illiquid

**Source:** kalshi-visualizer / CONTEXT.md harvest
**What:** On live data ~95% of ladder pairs have a No-quote or wide leg, so most display prices come from stale last trades. This is a data-availability limit, not a code bug — surfaced honestly via the Quote-quality grade.
**Why it matters:** Sets realistic expectations: few consistency checks are high-confidence. Don't "fix" sparse output by fabricating prices; the few Tight/OK rows are the trustworthy ones.

## Patterns

### 2026-06-04 — N-leg findings: additive `legs` list + 2-leg backfill (don't widen the schema)

**Source:** full-tennis-coverage / m5-synthetic-bundle-detector
**What:** The opportunity schema was 2-leg (`action_1/2_*`, `ticker_1/2`). To carry an N>2 finding (synthetic bundle) without breaking every consumer, add an additive `legs: list[dict]` (+ `n_legs`) and **backfill `action_1/2_*` from the first two legs**; 2-leg shapes set `legs=None`. The list round-trips through pandas → SQLite-JSON (`store._clean` recurses) and the API fine — **but** every new field must be **declared on the Pydantic `Opportunity` model**, because `extra="ignore"` silently drops undeclared fields at the boundary.
**Why it matters:** The reusable recipe for any future multi-leg detector (S6 winner fields, S8 advance hedge). The `extra="ignore"` drop is a silent failure mode — declare the field or lose it on the wire.

### 2026-06-04 — MECE completeness: compare found==expected against an INDEPENDENT signal

**Source:** full-tennis-coverage / m5-synthetic-bundle-detector
**What:** A field/bundle "is the set complete?" gate must compare the discovered markets against an **expected set derived from an independent signal** (here: match format from competition + gender). Deriving "expected" from the discovered markets themselves makes the check circular (vacuously true) — you'd never detect a missing outcome. If the independent signal can't be proven, **don't emit** (the "no proof → no emit" stance).
**Why it matters:** Load-bearing for S6 (n-outcome winner fields) and S8 (advance hedge) — it's what keeps a field detector free of false arbs.

### 2026-06-03 — Adding a sport = a `SportConfig` drop (the recipe)

**Source:** kalshi-visualizer / sport-generalization m1–m3 (tennis → NBA → WNBA)
**What:** The engine is sport-agnostic; a sport is pure data in `sports.py`. Recipe to add one: (1) **discover live** (keyless): `python scripts/verify_sport.py` after registering, but first probe `/series` + `/events` for the prefix, the identity field, market types, and **read `rules_primary`** to nail the ladder; (2) **register a `SportConfig`** — `series_prefixes`, `IdentityResolver(candidate_paths=…)`, `LadderSpec` (node_order broad→deep + adjacent pairs + advance/match stage→node maps), and the `family_fn`/`stage_fn`/`node_fn` closures; (3) add tests in `tests/test_sports.py`; (4) verify `pytest`/`ruff`/headless + `verify_sport.py <sport> --status all`. **Zero engine changes; never edit tennis's tests** (they're the regression guarantee).
**Key technique:** when a sport's ladder node comes from the **series**, not a title round (basketball: `KXNBA`=championship, `KXNBAPLAYOFF`=reach-playoffs), derive the advance "stage" from the **market ticker prefix** inside `stage_fn` and map it via `advance_stage_to_node` — so multiple advance series become distinct rungs with no engine/​signature change. Verify new prefixes don't collide (`KXWNBA` vs `KXNBA`: neither prefixes the other).
**Why it matters:** This is the proven path (3 sports, zero engine changes). A 4th sport (NHL etc.) follows it directly. Soccer is the exception — group-stage draws + MECE need the parked dutch-book detector first.

### 2026-06-02 — Pure-layer / Streamlit-only split enables network-free tests

**Source:** kalshi-visualizer / CONTEXT.md harvest
**What:** `data.py`, `consistency.py`, `glossary.py`, `filters.py`, `viz.py` import no Streamlit; all UI lives in `app.py`. `data.py` also avoids pandas. This keeps every analytical layer unit-testable without a browser or network.
**Why it matters:** The boundary is load-bearing for the test suite. The AppTest smoke test mocks only the three `kalshi_client` network entry points and runs the real pure layers end-to-end. Breaking the boundary (importing `st` into a pure module) breaks testability.

### 2026-06-02 — Exact integer cents for all comparison logic; floats are display-only

**Source:** kalshi-visualizer / CONTEXT.md harvest
**What:** Every price comparison uses `data.to_cents` (Decimal-backed int). `data.to_float` is used only for what renders. Prices arrive as fixed-point dollar strings (e.g. `"0.6500"`), never as floats.
**Why it matters:** Avoids float drift in the consistency math. Never `float()` a raw price string — use `to_float` (None-safe; `""`→None) or `to_cents`.

## Gotchas

### 2026-06-04 — Round parser: list specific rounds before generic Final/Finals (hyphen bug)

**Source:** full-tennis-coverage / m5-synthetic-bundle-detector (PR #42)
**What:** `sports.extract_round` returns the **first** matching pattern, and a hyphen is a regex word boundary — so a generic `\bfinal(s)\b` ordered before a more-specific round swallowed hyphenated variants: "semi-final"/"quarter-final" → "Final", "conference semi-finals" → "Finals". Bit **all three** sports (tennis/NBA/WNBA). Non-hyphenated forms ("semifinal") were unaffected, so it hid until exact-score work needed reliable stages.
**Why it matters:** Any `*_ROUND_PATTERNS` tuple must order most-specific first (Quarterfinal/Semifinal/Conference-Semifinals before Final/Finals) and include hyphen alternation (`semi-?finals?`). Stage parsing feeds the ladder node map AND the synthetic-bundle hedge join — a mis-parse mis-links markets.

### 2026-06-02 — A stacked PR can merge into the feature branch and silently miss `main`

**Source:** kalshi-visualizer / audit-hardening m1
**What:** A PR based on an unmerged feature branch (`audit → feature`) only auto-retargets to `main` when GitHub deletes the parent branch on merge. Here the parent wasn't deleted, so after the parent merged to `main`, merging the stacked PR just updated the *feature branch* — the work never reached `main`. Fixed by opening a fresh PR `audit → main` (clean diff, since `main` already had the parent's commits).
**Why it matters:** When stacking, verify with `git merge-base --is-ancestor <commit> origin/main` after merging — don't trust "PR merged" alone. Better: delete the parent branch on merge so GitHub retargets the child, or base the child on `main` once the parent lands.

### 2026-06-02 — `df.to_dict("records")` turns None into NaN (silent-NaN postmortem)

**Source:** kalshi-visualizer / CONTEXT.md harvest
**What:** Converting a DataFrame with `to_dict("records")` coerces a `None` numeric into float **NaN**, so a plain `is None` check silently misses it. This caused a real bug where ~33% of "ok" spreads were silently NaN.
**Why it matters:** Anywhere a price round-trips through pandas, use NaN-safe checks (`consistency._isna`/`_num`), not `is None`. This will bite again wherever new numeric fields flow through `to_dict`.

### 2026-06-02 — Streamlit caches imported modules; restart the server after editing pure modules

**Source:** kalshi-visualizer / CONTEXT.md harvest
**What:** After editing an imported module (`data.py`/`consistency.py`/…), a browser "Rerun" won't pick it up — you must fully stop and restart `streamlit run app.py`. A stale long-lived server once produced a phantom `ImportError` for code that was correct on disk.
**Why it matters:** Saves a confusing debugging session. For a phantom `ImportError`, also clear stale bytecode: `rm -rf __pycache__ tests/__pycache__`.

### 2026-06-02 — PowerShell `@'...'@` here-string corrupts messages via the Bash tool

**Source:** kalshi-visualizer / CONTEXT.md harvest
**What:** Using the PowerShell `@'...'@` here-string syntax for multi-line commit/PR text through the Bash tool injects stray `@` characters and corrupts the message. It bit the project twice.
**Why it matters:** For multi-line git text, use the Bash tool's `<<'EOF'` here-doc or `gh --body-file -` instead.

---
*Generated by scaffold-project on 2026-06-02*
