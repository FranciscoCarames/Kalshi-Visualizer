/* Auth API client for the SPA — talks to the FastAPI /auth router. Hand-written types (repo convention;
 * no openapi codegen). `getMe`/`getAuthConfig` use raw fetch because an anonymous 401 is expected there
 * and must NOT trigger the global login-redirect handler. */

export interface AuthUser { username: string; force_pw_change: boolean; }
export interface AuthConfig { auth_enabled: boolean; remember_available: boolean; }
export interface Device {
  id: number; label: string | null; created_ts: number; expires_ts: number;
  last_used_ts: number | null; revoked_ts: number | null;
}

export async function getAuthConfig(): Promise<AuthConfig> {
  try {
    const r = await fetch("/auth/config", { headers: { Accept: "application/json" } });
    if (!r.ok) return { auth_enabled: false, remember_available: false };
    return r.json();
  } catch {
    return { auth_enabled: false, remember_available: false };
  }
}

export async function getMe(): Promise<AuthUser | null> {
  const r = await fetch("/auth/me", { headers: { Accept: "application/json" } });
  if (r.status === 401) return null;
  if (!r.ok) throw new Error("auth/me " + r.status);
  return (await r.json()).user as AuthUser;
}

export async function login(username: string, password: string, remember: boolean):
  Promise<{ ok: boolean; user?: AuthUser; error?: string }> {
  const r = await fetch("/auth/login", {
    method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ username, password, remember }),
  });
  if (r.ok) return { ok: true, user: (await r.json()).user as AuthUser };
  let error = r.status === 429 ? "Too many attempts — wait a minute" : "Invalid username or password";
  try { const j = await r.json(); if (j?.detail) error = String(j.detail); } catch { /* keep default */ }
  return { ok: false, error };
}

export async function logout(): Promise<void> {
  await fetch("/auth/logout", { method: "POST", headers: { Accept: "application/json" } });
}

export async function changePassword(currentPassword: string, newPassword: string):
  Promise<{ ok: boolean; error?: string }> {
  const r = await fetch("/auth/password", {
    method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
  if (r.ok) return { ok: true };
  let error = "Could not change password";
  try { const j = await r.json(); if (j?.detail) error = String(j.detail); } catch { /* keep default */ }
  return { ok: false, error };
}

export async function listDevices(): Promise<Device[]> {
  const r = await fetch("/auth/devices", { headers: { Accept: "application/json" } });
  if (!r.ok) return [];
  return (await r.json()).devices as Device[];
}

export async function revokeDevice(id: number): Promise<void> {
  await fetch(`/auth/devices/${id}/revoke`, { method: "POST", headers: { Accept: "application/json" } });
}
