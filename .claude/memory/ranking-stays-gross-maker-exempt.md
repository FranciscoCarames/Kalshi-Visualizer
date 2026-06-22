---
name: ranking-stays-gross-maker-exempt
description: "Keep gross-edge default ranking — owner has maker-fee-exempt status, so gross = net for them"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 32aea8e3-5052-4081-b0ec-f047ab703d66
---

The owner rejected making net-of-fee edge the default ranking. Keep gross edge as the default sort; fees
stay visible for sanity-checking but never drive the default ranking.

**Why:** Kalshi grants some firms maker-fee-exempt status, and the owner trades (or plans to) under it — so
for them gross edge *is* net edge, and a net-of-fee ranking would reorder the list based on costs they don't
pay.

**How to apply:** don't propose net-of-fee as the default ranking again. A net view as an *optional,
non-default* lens is fine. Maker-side support (resting orders for better price/fees) is wanted — see the
"Maker tab" idea in the Obsidian "Future Expansions — TODO" note. Related: [[models-allowed-with-transparency]].
