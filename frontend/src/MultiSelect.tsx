/* A compact checkbox multi-select popover (mockup `.ms`), for the Sport + Tournament filters.
 * Empty selection = "All". Pure presentational — selection state lives in the terminal context. */
import { useEffect, useRef, useState } from "react";

export default function MultiSelect(
  { label, options, selected, onToggle }:
  { label: string; options: string[]; selected: Set<string>; onToggle: (v: string) => void },
) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const off = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", off);
    return () => document.removeEventListener("mousedown", off);
  }, [open]);
  const summary = selected.size === 0 ? "All" : `${selected.size} sel`;
  return (
    <span className="ms" ref={box}>
      <button className="ms-btn" aria-label={`Filter by ${label} (${summary})`} aria-expanded={open} onClick={() => setOpen((v) => !v)}>{label}: {summary} ▾</button>
      {open ? (
        <div className="menu on" style={{ top: 22, left: 0 }}>
          {options.length === 0 ? <div className="mi">— none —</div> : options.map((o) => (
            <label key={o}><input type="checkbox" checked={selected.has(o)} onChange={() => onToggle(o)} />{o}</label>
          ))}
        </div>
      ) : null}
    </span>
  );
}
