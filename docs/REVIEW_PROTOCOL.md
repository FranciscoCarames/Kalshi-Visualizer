# Review Protocol

A shared review protocol for **Claude Code**, **Codex**, and the owner. Goal: keep reviews
**blocker-focused** and avoid endless plan-perfection loops, especially for Kalshi market-logic changes.

`CLAUDE.md` is the authoritative project context and `AGENTS.md` is Codex's operating guide — this file
does not repeat them; it defines the shared review contract all three of us follow.

## 1. Review types

- **Plan review** — before implementation. Is the approach sound and the smallest safe slice? Output
  focuses on blockers/major issues, not polish.
- **Implementation / diff review** — the change exists. Audit the diff against `main` for correctness,
  scope creep, and tests.
- **PR readiness review** — final gate before merge. Verdict + conditions, tests green, docs current,
  branch hygiene clean: branched off `main`, one PR per change, no stacking on unmerged branches, never
  committing/pushing to `main`.

## 2. Risk classes

Label every review with one class and scale depth to it.

- **Low** — docs, copy, tests, minor UI layout.
- **Medium** — sport-config additions, filters, exports, viewmodel changes.
- **High** — market-data fetching, pricing, actionability gates, settlement rules, dutch-book logic,
  synthetic bundles, scanner / API pipeline.
- **Critical** — trading, auth, order placement, net-of-fees actionability, conditional-probability /
  de-vig models, live WebSocket feeds, or any non-read-only behavior. Out of scope unless explicitly
  requested → default to `reject`.

## 3. Standard review output

Every review uses these sections, in order:

- **Risk class** — Low / Medium / High / Critical (per §2), scaling review depth.
- **Review scope** — files/paths/behaviors examined, and what was NOT looked at.
- **Assumptions checked** — claims relied on and how each was verified (doc / test / live / unverified).
- **Verdict** — one of the four below.
- **Blockers** — must-fix before merge.
- **Major issues** — serious but not merge-blocking.
- **Minor issues** — nits, style, small clarity wins.
- **Missing tests** — untested paths and edge cases.
- **Current-doc checks** — matches `CLAUDE.md`? needs a doc update? external facts verified?
- **Regression risks** — what could break and how you'd notice.
- **Final recommendation** — one concrete next action.

Never say "no issues." Say **"no blockers found under the stated review scope"** and list remaining
uncertainty.

## 4. Verdict meanings

- **approve** — no blockers found under the stated review scope; mergeable as-is.
- **approve with conditions** — mergeable once the listed conditions are met.
- **reject** — has at least one blocker; do not merge.
- **needs more evidence** — can't decide; verification is missing (often network-blocked).

## 5. Blocker examples

- **False actionable signal** — an edge presented as executable/tradable that isn't.
- **Wrong opportunity labeling** — mislabeling across executable inconsistency / dutch book / synthetic
  bundle / review-only signal.
- **Missing MECE / exhaustiveness proof** for a dutch book or bundle.
- **Missing quote-size, market-status, or firm-price gate** on an executable claim.
- **Removed or weakened settlement caveat** (retirement / tie / walkover / postponement).
- **Float comparison logic** in any price path (must be integer cents / `Decimal`).
- **Engine/UI boundary regression** (UI imports leaking into pure modules).
- **Failing tests** — or a behavior change with no test.
- **Scope-guard violation** — Critical-class behavior added without explicit request.

## 6. Plan-review rules

- Focus on blockers and major issues.
- Do not demand plan perfection before implementation.
- Prefer the smallest safe implementation slice.
- If a plan is stale relative to `main`, require revalidation before building on it.
- Stop iterating once no blockers remain under the stated review scope.

## 7. Implementation-review rules

- Audit the diff against `main`.
- Check whether behavior changed **outside the intended scope**.
- Require targeted tests for behavior changes, or explain why existing tests already cover the behavior.
- For current Kalshi / API / market-structure / settlement / fees / rate-limit / sports-schedule /
  listed-market / package-or-library / deployment facts, verify against **current official docs or live
  evidence** — not memory or the diff's own claims. For Kalshi facts, use
  **<https://docs.kalshi.com/llms.txt>** as the first official-docs source; if it is unavailable,
  incomplete, or insufficient, fall back to the relevant official Kalshi docs page or live evidence. If
  network access is unavailable, mark the assumption **unverified** — do not treat repo docs as current truth.

## 8. Conservative-labeling rules

- Do not call containment findings "arbitrage."
- Reserve "dutch-book arbitrage" for proven MECE dutch-book findings under the app's conservative
  gross / top-of-book basis.
- Synthetic bundles stay **review-only** unless explicitly changed.
- Never use "riskless", "locked", or "true arbitrage" unless settlement, MECE/exhaustiveness, execution,
  size, price, and rule conditions all justify it.
