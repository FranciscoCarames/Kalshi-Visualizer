/* AuthGate — wraps the whole SPA above TerminalProvider.
 *
 * On boot it reads /auth/config: if auth is OFF (today's open behaviour) it renders the app unchanged with
 * no account chrome. If auth is ON it calls /auth/me — anonymous → the login view; authenticated → the app
 * plus a small account bar. A 401 from ANY data call (routed via http.apiFetch) flips the gate back to the
 * login view; because that UNMOUNTS TerminalProvider, the feed poll stops and all in-memory opportunity
 * state is discarded — no stale data lingers after logout/expiry. force_pw_change → a forced change view. */
import { useCallback, useEffect, useState } from "react";

import {
  type AuthConfig, type AuthUser, type Device,
  changePassword, getAuthConfig, getMe, listDevices, login, logout, revokeDevice,
} from "./auth";
import { setUnauthorizedHandler } from "./http";

type Phase = "loading" | "anon" | "authed";

const card: React.CSSProperties = {
  background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 6,
  padding: "22px 24px", width: 320, fontFamily: "var(--mono)", color: "var(--tx)",
};
const overlay: React.CSSProperties = {
  position: "fixed", inset: 0, display: "flex", alignItems: "center", justifyContent: "center",
  background: "var(--bg)", zIndex: 9999,
};
const field: React.CSSProperties = {
  width: "100%", boxSizing: "border-box", marginTop: 4, marginBottom: 12, padding: "7px 9px",
  background: "var(--bg1)", border: "1px solid var(--line)", borderRadius: 4,
  color: "var(--tx)", fontFamily: "var(--mono)", fontSize: 13,
};
const btn: React.CSSProperties = {
  width: "100%", padding: "8px 0", background: "var(--amber)", color: "#000", border: "none",
  borderRadius: 4, cursor: "pointer", fontFamily: "var(--mono)", fontWeight: 700, fontSize: 13,
};
const label: React.CSSProperties = { fontSize: 11, color: "var(--tx2)", textTransform: "uppercase", letterSpacing: 0.5 };

function LoginView({ cfg, onAuthed }: { cfg: AuthConfig; onAuthed: () => void }) {
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [remember, setRemember] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(null);
    const res = await login(u, p, remember);
    setBusy(false);
    if (res.ok) onAuthed(); else setErr(res.error ?? "Login failed");
  }

  return (
    <div style={overlay}>
      <form style={card} onSubmit={submit}>
        <div style={{ color: "var(--amber)", fontWeight: 700, letterSpacing: 1, marginBottom: 2 }}>
          KALSHI STRUCTURED SCANNER
        </div>
        <div style={{ fontSize: 11, color: "var(--tx3)", marginBottom: 18 }}>sign in to continue</div>
        <div style={label}>username</div>
        <input style={field} value={u} autoFocus autoComplete="username"
               onChange={(e) => setU(e.target.value)} />
        <div style={label}>password</div>
        <input style={field} type="password" value={p} autoComplete="current-password"
               onChange={(e) => setP(e.target.value)} />
        {cfg.remember_available ? (
          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, margin: "2px 0 14px", color: "var(--tx2)", cursor: "pointer" }}>
            <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
            stay signed in on this device
          </label>
        ) : <div style={{ height: 8 }} />}
        {err ? <div style={{ color: "var(--red)", fontSize: 12, marginBottom: 10 }}>{err}</div> : null}
        <button style={{ ...btn, opacity: busy ? 0.6 : 1 }} type="submit" disabled={busy}>
          {busy ? "…" : "SIGN IN"}
        </button>
      </form>
    </div>
  );
}

function ChangePasswordView({ onDone, forced }: { onDone: () => void; forced: boolean }) {
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (next !== confirm) { setErr("New passwords do not match"); return; }
    setBusy(true); setErr(null);
    const res = await changePassword(cur, next);
    setBusy(false);
    if (res.ok) onDone(); else setErr(res.error ?? "Could not change password");
  }

  return (
    <div style={overlay}>
      <form style={card} onSubmit={submit}>
        <div style={{ color: "var(--amber)", fontWeight: 700, marginBottom: 2 }}>CHANGE PASSWORD</div>
        <div style={{ fontSize: 11, color: "var(--tx3)", marginBottom: 16 }}>
          {forced ? "a password change is required before continuing" : "update your password"}
        </div>
        <div style={label}>current password</div>
        <input style={field} type="password" value={cur} autoFocus onChange={(e) => setCur(e.target.value)} />
        <div style={label}>new password</div>
        <input style={field} type="password" value={next} onChange={(e) => setNext(e.target.value)} />
        <div style={label}>confirm new password</div>
        <input style={field} type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        {err ? <div style={{ color: "var(--red)", fontSize: 12, marginBottom: 10 }}>{err}</div> : null}
        <button style={{ ...btn, opacity: busy ? 0.6 : 1 }} type="submit" disabled={busy}>
          {busy ? "…" : "UPDATE PASSWORD"}
        </button>
      </form>
    </div>
  );
}

function DevicesDialog({ onClose }: { onClose: () => void }) {
  const [devices, setDevices] = useState<Device[]>([]);
  const refresh = useCallback(() => { listDevices().then(setDevices); }, []);
  useEffect(() => { refresh(); }, [refresh]);
  const fmt = (ts: number | null) => (ts ? new Date(ts * 1000).toLocaleString() : "—");
  return (
    <div style={overlay} onClick={onClose}>
      <div style={{ ...card, width: 460 }} onClick={(e) => e.stopPropagation()}>
        <div style={{ color: "var(--amber)", fontWeight: 700, marginBottom: 12 }}>TRUSTED DEVICES</div>
        {devices.length === 0 ? (
          <div style={{ fontSize: 12, color: "var(--tx3)" }}>no remembered devices</div>
        ) : devices.map((d) => (
          <div key={d.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center",
                                    fontSize: 12, padding: "6px 0", borderBottom: "1px solid var(--line)" }}>
            <span>added {fmt(d.created_ts)} · last used {fmt(d.last_used_ts)}</span>
            <button style={{ ...btn, width: "auto", padding: "3px 8px", background: "var(--red)", color: "#fff" }}
                    onClick={() => revokeDevice(d.id).then(refresh)}>revoke</button>
          </div>
        ))}
        <button style={{ ...btn, marginTop: 14, background: "var(--bg2)", color: "var(--tx)" }} onClick={onClose}>
          close
        </button>
      </div>
    </div>
  );
}

function AccountBar({ user, onLogout }: { user: AuthUser; onLogout: () => void }) {
  const [showDevices, setShowDevices] = useState(false);
  const [changing, setChanging] = useState(false);
  const pill: React.CSSProperties = {
    position: "fixed", top: 6, right: 8, zIndex: 9000, display: "flex", gap: 8, alignItems: "center",
    fontFamily: "var(--mono)", fontSize: 11, color: "var(--tx2)",
    background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 4, padding: "3px 8px",
  };
  const link: React.CSSProperties = { cursor: "pointer", color: "var(--cyan)" };
  return (
    <>
      <div style={pill}>
        <span style={{ color: "var(--amber)" }}>{user.username}</span>
        <span style={link} onClick={() => setShowDevices(true)} title="trusted devices">⌗</span>
        <span style={link} onClick={() => setChanging(true)} title="change password">key</span>
        <span style={{ ...link, color: "var(--red)" }} onClick={onLogout} title="sign out">⎋ logout</span>
      </div>
      {showDevices ? <DevicesDialog onClose={() => setShowDevices(false)} /> : null}
      {changing ? <ChangePasswordView forced={false} onDone={() => setChanging(false)} /> : null}
    </>
  );
}

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [cfg, setCfg] = useState<AuthConfig>({ auth_enabled: false, remember_available: false });
  const [user, setUser] = useState<AuthUser | null>(null);

  const refresh = useCallback(async () => {
    const c = await getAuthConfig();
    setCfg(c);
    if (!c.auth_enabled) { setPhase("authed"); return; }   // auth off → open app (unchanged behaviour)
    const me = await getMe().catch(() => null);
    if (me) { setUser(me); setPhase("authed"); } else { setUser(null); setPhase("anon"); }
  }, []);

  useEffect(() => {
    refresh();
    setUnauthorizedHandler(() => { setUser(null); setPhase("anon"); });
    return () => setUnauthorizedHandler(null);
  }, [refresh]);

  async function doLogout() {
    await logout();
    setUser(null);
    setPhase("anon");
  }

  if (phase === "loading") {
    return <div style={{ ...overlay, color: "var(--tx3)", fontFamily: "var(--mono)", fontSize: 12 }}>…</div>;
  }
  if (phase === "anon") {
    return <LoginView cfg={cfg} onAuthed={refresh} />;
  }
  // authed
  if (cfg.auth_enabled && user?.force_pw_change) {
    return <ChangePasswordView forced onDone={refresh} />;
  }
  return (
    <>
      {children}
      {cfg.auth_enabled && user ? <AccountBar user={user} onLogout={doLogout} /> : null}
    </>
  );
}
