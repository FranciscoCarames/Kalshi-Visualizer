/* The docked workspace — Dockview hosts the panels as draggable / resizable / pop-out groups.
 * Layout PRESETS rebuild the arrangement; drag a tab to rearrange, drag a splitter to resize, POP a group
 * to a separate window (multi-monitor). Replaces Phase B1's static CSS grid. */
import { useEffect, useRef, useState } from "react";
import { DockviewReact, type DockviewApi, type DockviewReadyEvent, themeAbyss } from "dockview";
import "dockview/dist/styles/dockview.css";
import { PANELS } from "./panels";
import { useTerminal } from "./context";

const TITLES: Record<string, string> = {
  blotter: "BLOTTER", inspector: "INSPECTOR", ladder: "MD LADDER", watch: "RECENTLY ACTIONABLE", alerts: "ALERTS",
};
const add = (api: DockviewApi, id: string, position?: object) =>
  api.addPanel({ id, component: id, title: TITLES[id], position: position as never });

type Preset = "default" | "inspect" | "research" | "triage" | "blotterfull";

function build(api: DockviewApi, preset: Preset) {
  api.clear();
  add(api, "blotter");
  if (preset === "blotterfull") return;
  if (preset === "triage") {
    add(api, "inspector", { referencePanel: "blotter", direction: "below" });
    return;
  }
  if (preset === "inspect") {
    add(api, "inspector", { referencePanel: "blotter", direction: "right" });
    add(api, "ladder", { referencePanel: "inspector", direction: "below" });
    return;
  }
  // default + research: full five-panel desk
  add(api, "inspector", { referencePanel: "blotter", direction: "below" });
  add(api, "ladder", { referencePanel: "blotter", direction: "right" });
  add(api, "watch", { referencePanel: "ladder", direction: "right" });
  add(api, "alerts", { referencePanel: "watch", direction: "below" });
  if (preset === "research") api.getPanel("alerts") && api.removePanel(api.getPanel("alerts")!);
}

const PRESETS: [Preset, string][] = [
  ["default", "Default"], ["inspect", "Inspect"], ["research", "Research"], ["triage", "Triage"], ["blotterfull", "Blotter full"],
];

export default function Workspace() {
  const t = useTerminal();
  const apiRef = useRef<DockviewApi | null>(null);
  const [preset, setPreset] = useState<Preset>("default");

  const onReady = (event: DockviewReadyEvent) => { apiRef.current = event.api; build(event.api, "default"); };
  const applyPreset = (p: Preset) => { setPreset(p); if (apiRef.current) build(apiRef.current, p); };
  const seqRef = useRef(0);
  // Expose preset-switching (palette → Layout) + dynamic panel adds (multi-select → Compare/Overlap).
  useEffect(() => {
    t.registerLayout((p) => applyPreset(p as Preset));
    t.registerAddPanel((component, title, params) => {
      const api = apiRef.current; if (!api) return;
      api.addPanel({ id: `${component}_${++seqRef.current}`, component, title,
        params: params as never, position: { direction: "right" } as never });
    });
  }, [t]);
  const popActive = () => {
    const api = apiRef.current; if (!api) return;
    const g = api.activeGroup; if (g) api.addPopoutGroup(g);
  };

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      <div className="tp-dockbar">
        <span className="dim">LAYOUT</span>
        <select value={preset} onChange={(e) => applyPreset(e.target.value as Preset)}>
          {PRESETS.map(([p, label]) => <option key={p} value={p}>{label}</option>)}
        </select>
        <button className="tp-tb" onClick={popActive} title="Pop the active panel group into its own window">⧉ POP</button>
        <button className="tp-tb" onClick={() => applyPreset(preset)} title="Reset this layout">↺</button>
        <span className="dim" style={{ marginLeft: "auto", fontSize: 9 }}>drag tabs to rearrange · drag splitters to resize · ⧉ to pop out</span>
      </div>
      <div className="tp-dock" style={{ flex: 1, minHeight: 0 }}>
        <DockviewReact components={PANELS} onReady={onReady} theme={themeAbyss} />
      </div>
    </div>
  );
}
