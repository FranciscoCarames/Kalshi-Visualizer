import { afterEach, describe, expect, it, vi } from "vitest";

import { loadPrefs, savePrefs } from "./prefs";

afterEach(() => vi.unstubAllGlobals());

describe("loadPrefs", () => {
  it("returns the prefs envelope on 200", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true, status: 200, json: async () => ({ prefs: { theme: "hc", layoutPreset: "triage" } }),
    })));
    expect(await loadPrefs()).toEqual({ theme: "hc", layoutPreset: "triage" });
  });
  it("returns {} on a 401 (never throws — apiFetch fires the login handler)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 401, json: async () => ({}) })));
    expect(await loadPrefs()).toEqual({});
  });
  it("returns {} when the network throws", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("offline"); }));
    expect(await loadPrefs()).toEqual({});
  });
});

describe("savePrefs", () => {
  it("PUTs the prefs and never throws on failure", async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({}) }));
    vi.stubGlobal("fetch", fetchMock);
    await savePrefs({ version: 1, theme: "hc" });
    expect(fetchMock).toHaveBeenCalledOnce();
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual({ prefs: { version: 1, theme: "hc" } });
  });
  it("swallows a network error (no crash)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("offline"); }));
    await expect(savePrefs({ theme: "amber" })).resolves.toBeUndefined();
  });
});
