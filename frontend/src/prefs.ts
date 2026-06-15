/* Per-user preferences — load on login, save (debounced) on change. The server stores a sanitized,
 * versioned envelope per user (auth.db); the client mirrors only DURABLE view state — theme, settings,
 * shown/ordered columns, band thresholds, split, and the chosen layout preset. Transient FILTERS are
 * deliberately NOT persisted (a shared/debug URL must never silently become a user's saved default).
 * Routed through apiFetch so a 401 surfaces the login screen. */
import { apiFetch } from "./http";

export const PREFS_VERSION = 1;
export const THEMES = ["amber", "hc"] as const;
export const LAYOUT_PRESETS = ["default", "triage", "inspect", "research", "blotterfull"] as const;
export const SPLITS = ["all", "vertical", "calendar"] as const;

export interface Prefs {
  version?: number;
  theme?: "amber" | "hc";
  settings?: Record<string, unknown>;
  showNet?: boolean;
  columns?: Record<string, string[]>;
  bands?: Record<string, Record<string, unknown>>;
  split?: string;
  layoutPreset?: string;
}

export async function loadPrefs(): Promise<Prefs> {
  try {
    const r = await apiFetch("/auth/preferences", { headers: { Accept: "application/json" } });
    if (!r.ok) return {};
    return (await r.json()).prefs ?? {};
  } catch {
    return {};
  }
}

export async function savePrefs(prefs: Prefs): Promise<void> {
  // Save failures must never crash or block the dashboard — log and move on (the next change retries).
  try {
    await apiFetch("/auth/preferences", {
      method: "PUT",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ prefs }),
    });
  } catch (e) {
    console.warn("preferences save failed", e);
  }
}
