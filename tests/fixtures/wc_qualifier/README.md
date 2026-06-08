# World Cup Qualifier Setups fixtures (Group B, captured 2026-06-08)

Sanitized offline fixtures for the WC Qualifier Setups feature, captured by
`scripts/probe_wc_qualifier_setups.py` and trimmed to the fields `data.build_contracts` consumes plus
prices/sizes (same convention as `tests/fixtures/soccer`). One full group (B: Switzerland / Qatar /
Bosnia and Herzegovina / Canada):

| File | Series | Shape |
|---|---|---|
| `KXWCGROUPQUAL-26B.json` | group qualifiers | 4 per-team "qualify" markets; `soccer_team` UUID + name |
| `KXWCGROUPWIN-26B.json` | group winners | 4 per-team "win the group" markets; UUID |
| `KXWCGROUPORDER-B26.json` | exact standings | 24 orderings, `mutually_exclusive=True` |
| `KXWCGAME-26JUN*.json` (×6) | 3-way games | the group's full round-robin; Home/Away/Tie |

## Discovery facts these pin (verified live; NOT in the public Kalshi docs)

- **`with_nested_markets=true` is mandatory for discovery.** `/events?series_ticker=KXWCGAME` returns
  0 events without it but 72 with it; `kalshi_client.get_events` already passes it.
- **Two group-ticker shapes.** `KXWCGROUPQUAL-26B` / `KXWCGROUPWIN-26B` put the group letter AFTER
  the season token; `KXWCGROUPORDER-B26` puts it BEFORE. `wc_groups.parse_wc_group_key` handles both.
- **Exact-order identity is by NAME, not UUID.** `KXWCGROUPORDER` markets carry the four placement
  team names in `custom_strike` (`"1st Place Team"`…`"4th Place Team"`, with stray newlines) and have
  **no `soccer_team` UUID**, so the join to `KXWCGROUPQUAL` goes through `wc_groups.normalize_country_name`.
  The captured fixtures confirm the qualifier↔order name sets match exactly under normalization.
- **Settlement is undocumented.** Kalshi documents the generic `/events` params and market fields, but
  **not** the 2026 exact-order/best-third qualification settlement rules — which is why the exact-order
  and game-support outputs stay diagnostic-only, never executable.

Re-run the probe from an unthrottled network before relying on these for a merge:
`python scripts/probe_wc_qualifier_setups.py`.
