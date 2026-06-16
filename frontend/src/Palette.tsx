/* Command palette — ported from ui-mockup-final-spa.html (.palette/.pal/.pin/.plist/.pcat/.pitem/.pfoot),
 * no cmdk. Fuzzy substring filter + ↑↓/↵/esc keyboard nav. Running an item dispatches through context. */
import { useEffect, useMemo, useRef, useState } from "react";
import { useTerminal } from "./context";
import { LENSES } from "./lens";
import { ZONES, SUBTABS } from "./feed";

interface PItem { cat: string; k: string; d?: string; tag: string; run: () => void; }
const PRESETS: [string, string][] = [
  ["default", "Default"], ["triage", "Triage"], ["inspect", "Inspect"], ["research", "Research"], ["blotterfull", "Scanner full"],
];

export default function Palette() {
  const t = useTerminal();
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const close = () => { t.setPaletteOpen(false); setQ(""); setActive(0); };
  const run = (fn: () => void) => { fn(); close(); };

  const items = useMemo<PItem[]>(() => {
    const out: PItem[] = [];
    (["opp", "res", "ops", "alrt"] as const).forEach((s) => out.push({ cat: "Surface", k: s.toUpperCase(), tag: "view", run: () => t.setSurface(s) }));
    LENSES.forEach(([l, lbl, tip]) => out.push({ cat: "Lens", k: lbl, d: tip, tag: "lens", run: () => t.setLens(l) }));
    ZONES.forEach(([z]) => SUBTABS[z].forEach(([s, lbl]) => out.push({ cat: "Section", k: lbl, d: z, tag: "go", run: () => { t.setSurface("opp"); t.goSection(z, s); } })));
    PRESETS.forEach(([p, lbl]) => out.push({ cat: "Layout", k: lbl, tag: "layout", run: () => { t.setSurface("opp"); t.applyLayout(p); } }));
    out.push({ cat: "Theme", k: "Amber", tag: "theme", run: () => t.setTheme("amber") });
    out.push({ cat: "Theme", k: "High contrast", tag: "theme", run: () => t.setTheme("hc") });
    out.push({ cat: "Toggle", k: "Net of fees (est.)", tag: "toggle", run: () => t.setShowNet(!t.showNet) });
    out.push({ cat: "Toggle", k: "Larger text", tag: "toggle", run: () => document.body.classList.toggle("big") });
    out.push({ cat: "Toggle", k: "Long / short wording", tag: "toggle", run: () => t.setSetting("longShort", !t.settings.longShort) });
    out.push({ cat: "Toggle", k: "Show IDs & codes", tag: "toggle", run: () => t.setSetting("showIds", !t.settings.showIds) });
    out.push({ cat: "Help", k: "Keyboard: Ctrl-K · 1-6 lens · J/K rows · ↵ open", tag: "help", run: () => {} });
    // Index ALL participants (no silent cap), deduped by a STABLE key — player_key+sport when present (so two
    // distinct entities sharing a display name never merge), else name+sport. First (highest-ranked) wins.
    const seen = new Set<string>();
    for (const o of t.opps) {
      if (!o.name) continue;
      const key = `${o.player_key || o.name}__${o.sport || ""}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({
        cat: "Participant", k: o.name, d: `${o.sport} · ${o.bucket}`, tag: "row",
        run: () => { t.setSurface("opp"); t.goSection(o.zone, o.section); t.setSel({ ...o }); },
      });
    }
    return out;
  }, [t]);

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return items;
    return items.filter((it) => (it.k + " " + (it.d || "") + " " + it.cat + " " + it.tag).toLowerCase().includes(s));
  }, [items, q]);
  // Cap the RENDERED rows (never the index) so a big result set can't lag the input; honest "+N more" hint.
  const PAL_RENDER_CAP = 250;
  const shown = filtered.slice(0, PAL_RENDER_CAP);
  const hiddenCount = filtered.length - shown.length;

  useEffect(() => { if (t.paletteOpen) setTimeout(() => inputRef.current?.focus(), 0); }, [t.paletteOpen]);
  if (!t.paletteOpen) return null;

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") return close();
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(shown.length - 1, a + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
    else if (e.key === "Enter") { e.preventDefault(); shown[active]?.run && run(shown[active].run); }
  };

  let lastCat = "";
  return (
    <div className="palette on" onMouseDown={close}>
      <div className="pal" onMouseDown={(e) => e.stopPropagation()}>
        <div className="pin"><span className="amber">⌘</span>
          <input ref={inputRef} value={q} onChange={(e) => { setQ(e.target.value); setActive(0); }} onKeyDown={onKey}
                 placeholder="Type a function, participant, lens, layout… (e.g. OPS · golf · ripeness · triage · HELP)" /></div>
        <div className="plist">
          {shown.length === 0 ? <div className="pitem">No match.</div> : shown.map((it, i) => {
            const header = it.cat !== lastCat ? <div className="pcat" key={"c" + it.cat}>{it.cat.toUpperCase()}</div> : null;
            lastCat = it.cat;
            return (
              <div key={"i" + i}>
                {header}
                <div className={"pitem" + (i === active ? " act" : "")} onMouseEnter={() => setActive(i)} onClick={() => run(it.run)}>
                  <span className="pi-k">{it.k}</span>{it.d ? <span className="pi-d">{it.d}</span> : null}<span className="pi-tag">{it.tag}</span>
                </div>
              </div>
            );
          })}
          {hiddenCount > 0 ? <div className="pitem dim">+{hiddenCount} more — keep typing to narrow</div> : null}
        </div>
        <div className="pfoot"><span><b>↑↓</b> move</span><span><b>↵</b> run</span><span><b>esc</b> close</span><span className="amber">discoverable — start typing</span></div>
      </div>
    </div>
  );
}
