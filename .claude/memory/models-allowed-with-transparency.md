---
name: models-allowed-with-transparency
description: Owner reversed the SPA no-model/no-de-vig guard — models are now allowed if clearly labelled
metadata: 
  node_type: memory
  type: project
  originSessionId: 32aea8e3-5052-4081-b0ec-f047ab703d66
---

The owner (2026-06-19) reversed the long-standing "SPA stays display-only / no de-vig / no probability
models" guard documented in CLAUDE.md. New direction: integrating probability models is inevitable and
welcome where it adds value.

**Why:** the owner sees model-based signals (parlay consistency, cross-event relative value, sportsbook
de-vig) as the path to directional mispricing, not just internal contradictions.

**How to apply:** the firm rule is **transparency, not prohibition** — the app must always make it obvious
when a number comes from a model, state the model's assumptions/limitations, and never present a modelled
number as a riskless edge. This contradicts the current CLAUDE.md "no de-vig in the SPA" wording, so
confirm before relying on that doc; the owner's stated direction overrides it. Related: [[ranking-stays-gross-maker-exempt]].
