/* Manual-scan client — drives the ▷SCAN / ⚡force buttons over the real read-only endpoints
 * (POST /scan + GET /scan/status). Honors the scan-token gate + rate limit: on 401/429/202-already
 * the caller surfaces the reason; never a silent no-op. The 4s feed poll picks up the new snapshot. */
import { apiFetch } from "./http";

export interface ScanStatus {
  status?: string; since?: number | null; last_snapshot_id?: number | null;
  reason?: string | null; last_scan_error?: string | null;
}

export async function postScan(force: boolean): Promise<{ ok: boolean; code: number; error?: string }> {
  // Same-origin POST. When SCAN_TOKEN is set on the server, a 401 surfaces honestly as "scan locked"
  // (the dashboard's own button bypasses the gate in-process; an external caller must send the header).
  const r = await apiFetch(`/scan${force ? "?force=true" : ""}`, { method: "POST", headers: { Accept: "application/json" } });
  if (r.status === 202) return { ok: true, code: 202 };
  let error = `scan ${r.status}`;
  if (r.status === 401) error = "session expired — sign in again";
  else if (r.status === 429) error = "rate-limited — slow down";
  else { try { const j = await r.json(); if (j?.detail) error = String(j.detail); } catch { /* ignore */ } }
  return { ok: false, code: r.status, error };
}

export async function getScanStatus(): Promise<ScanStatus> {
  const r = await apiFetch("/scan/status", { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error("scan/status " + r.status);
  return r.json();
}
