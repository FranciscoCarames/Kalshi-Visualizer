---
name: guardrail-direction-2026-06
description: "Owner's revised product guardrails — trading planned, trader-aggressive language, dual framing, arb→actionable"
metadata: 
  node_type: memory
  type: project
  originSessionId: 32aea8e3-5052-4081-b0ec-f047ab703d66
---

On 2026-06-19 the owner revised several long-standing product guardrails (documented in CLAUDE.md /
Strategy Map / Overview). Tracked in the Obsidian note "TODO — Guardrail Updates".

1. **Read-only is the current state, not a permanent principle.** The app is expected to grow into one that
   can place trades. Don't treat "read-only" as a defining constraint; leave room for an execution layer.
   (Still don't *build* trading until explicitly asked.)
2. **Language: honest but trader-aggressive.** Never oversell (no "riskless/guaranteed"), but be punchy and
   direct enough that a trader instantly understands — not so hedged the signal turns to mush.
3. **Two framings, toggleable:** Buy YES / Buy NO (current) AND Long YES / Short YES (Buy NO ≈ Short YES).
4. **Arbitrage → Actionable.** Any genuine arbitrage should route to Actionable. Relaxes the old "only
   EXECUTABLE_VIOLATION / EXECUTABLE_DUTCH_BOOK reach Actionable, never call it arbitrage" stance.

**How to apply:** these are direction, not built yet. Update docs first, but don't relax a guard in the docs
before the replacement behaviour exists in the app. Related: [[models-allowed-with-transparency]],
[[ranking-stays-gross-maker-exempt]].
