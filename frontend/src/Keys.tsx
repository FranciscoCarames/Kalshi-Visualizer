/* Global keyboard navigation. Ctrl-K / "/" open the palette; 1-6 set a lens; J/K move the blotter
 * selection (drives the inspector + ladder); typing in an input is never intercepted. */
import { useEffect, useRef } from "react";
import { useTerminal } from "./context";
import { LENSES } from "./lens";

export default function Keys() {
  const t = useTerminal();
  const ref = useRef(t);
  ref.current = t;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const T = ref.current;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); T.setPaletteOpen(true); return; }
      if (T.paletteOpen) return;                       // the palette owns its keys while open
      const tag = (document.activeElement?.tagName || "").toLowerCase();
      if (tag === "input" || tag === "select" || tag === "textarea") return;
      if (e.key === "/") { e.preventDefault(); T.setPaletteOpen(true); return; }
      if (e.key >= "1" && e.key <= "6") { T.setLens(LENSES[+e.key - 1][0]); return; }
      if (e.key === "j" || e.key === "k") {
        const rows = T.rows; if (!rows.length) return;
        const at = rows.findIndex((r) => r.id === T.sel?.id);
        const idx = e.key === "j"
          ? Math.min((at < 0 ? -1 : at) + 1, rows.length - 1)
          : Math.max((at < 0 ? 1 : at) - 1, 0);
        T.setSel({ ...rows[idx] });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return null;
}
