/* Ctrl-K command palette (cmdk) — fuzzy over lenses · sections · layouts · theme · participants.
 * Running an item dispatches the action through the shared context and closes. */
import { Command } from "cmdk";
import { useTerminal } from "./context";
import { LENSES } from "./lens";
import { ZONES, SUBTABS } from "./feed";

const PRESETS: [string, string][] = [
  ["default", "Default"], ["inspect", "Inspect"], ["research", "Research"], ["triage", "Triage"], ["blotterfull", "Blotter full"],
];

export default function Palette() {
  const t = useTerminal();
  if (!t.paletteOpen) return null;
  const close = () => t.setPaletteOpen(false);
  const run = (fn: () => void) => { fn(); close(); };
  return (
    <div className="pal-overlay" onMouseDown={close}>
      <Command className="pal" label="Command palette" onMouseDown={(e) => e.stopPropagation()}
               onKeyDown={(e) => { if (e.key === "Escape") close(); }}>
        <div className="pal-in"><span className="amber">⌘</span>
          <Command.Input autoFocus placeholder="Type a lens · section · layout · theme · participant…" /></div>
        <Command.List className="pal-list">
          <Command.Empty className="pal-empty">No match.</Command.Empty>
          <Command.Group heading="Lens">
            {LENSES.map(([l, lbl, tip]) => (
              <Command.Item key={"lens" + l} value={"lens " + lbl} onSelect={() => run(() => t.setLens(l))}>
                <span className="pi-k">{lbl}</span><span className="pi-d">{tip}</span><span className="pi-tag">lens</span>
              </Command.Item>
            ))}
          </Command.Group>
          <Command.Group heading="Section">
            {ZONES.flatMap(([z]) => SUBTABS[z].map(([s, lbl]) => (
              <Command.Item key={"sec" + z + s} value={"go " + lbl + " " + z} onSelect={() => run(() => t.goSection(z, s))}>
                <span className="pi-k">{lbl}</span><span className="pi-d">{z}</span><span className="pi-tag">go</span>
              </Command.Item>
            )))}
          </Command.Group>
          <Command.Group heading="Layout">
            {PRESETS.map(([p, lbl]) => (
              <Command.Item key={"lay" + p} value={"layout " + lbl} onSelect={() => run(() => t.applyLayout(p))}>
                <span className="pi-k">{lbl}</span><span className="pi-tag">layout</span>
              </Command.Item>
            ))}
          </Command.Group>
          <Command.Group heading="Theme">
            <Command.Item value="theme amber" onSelect={() => run(() => t.setTheme("amber"))}><span className="pi-k">Amber</span><span className="pi-tag">theme</span></Command.Item>
            <Command.Item value="theme high contrast" onSelect={() => run(() => t.setTheme("hc"))}><span className="pi-k">High contrast</span><span className="pi-tag">theme</span></Command.Item>
          </Command.Group>
          <Command.Group heading="Participant">
            {t.opps.slice(0, 400).map((o) => (
              <Command.Item key={"p" + o.id} value={"participant " + (o.name || "") + " " + (o.sport || "")}
                            onSelect={() => run(() => { t.goSection(o.zone, o.section); t.setSel({ ...o }); })}>
                <span className="pi-k">{o.name}</span><span className="pi-d">{o.sport} · {o.bucket}</span><span className="pi-tag">row</span>
              </Command.Item>
            ))}
          </Command.Group>
        </Command.List>
        <div className="pal-foot"><span><b>↑↓</b> move</span><span><b>↵</b> run</span><span><b>esc</b> close</span><span className="amber">discoverable — start typing</span></div>
      </Command>
    </div>
  );
}
