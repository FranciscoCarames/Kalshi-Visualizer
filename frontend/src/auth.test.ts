import { afterEach, describe, expect, it, vi } from "vitest";

import { getAuthConfig, getMe, login } from "./auth";

function mockFetch(status: number, body: unknown) {
  vi.stubGlobal("fetch", vi.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  })));
}

afterEach(() => vi.unstubAllGlobals());

describe("getMe", () => {
  it("returns null on 401 (anonymous — never throws)", async () => {
    mockFetch(401, { detail: "Not authenticated" });
    expect(await getMe()).toBeNull();
  });
  it("returns the user on 200", async () => {
    mockFetch(200, { user: { username: "alice", force_pw_change: false } });
    expect(await getMe()).toEqual({ username: "alice", force_pw_change: false });
  });
});

describe("getAuthConfig", () => {
  it("falls back to auth-off when the endpoint errors", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("network"); }));
    expect(await getAuthConfig()).toEqual({ auth_enabled: false, remember_available: false });
  });
});

describe("login", () => {
  it("returns ok + user on success", async () => {
    mockFetch(200, { ok: true, user: { username: "alice", force_pw_change: true } });
    const r = await login("alice", "pw", false);
    expect(r.ok).toBe(true);
    expect(r.user?.force_pw_change).toBe(true);
  });
  it("surfaces a generic error on 401 (no enumeration)", async () => {
    mockFetch(401, { detail: "Invalid username or password" });
    const r = await login("alice", "wrong", false);
    expect(r.ok).toBe(false);
    expect(r.error).toBe("Invalid username or password");
  });
  it("maps 429 to a rate-limit message", async () => {
    mockFetch(429, {});
    const r = await login("alice", "pw", false);
    expect(r.ok).toBe(false);
    expect(r.error).toMatch(/too many/i);
  });
});
