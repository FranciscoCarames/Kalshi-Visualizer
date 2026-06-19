import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";

// App version string injected at build time from package.json (`"version"`), surfaced via
// `__APP_VERSION__` and shown in the footer as e.g. "v1.0.0". package.json is the single source of
// truth — bump it there on a release. Fails open to "v0" if the field is somehow missing.
function appVersion(): string {
  try {
    const pkg = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8"));
    return `v${pkg.version}`;
  } catch {
    return "v0";
  }
}

// The SPA is served at /terminal in production (FastAPI StaticFiles), so the built asset base is
// /terminal/. In dev, proxy /api/* straight through to serve.py on :8000 WITHOUT rewriting the path
// (the live feed lives at /api/terminal/feed) — same path in dev and prod, no surprises.
export default defineConfig({
  base: "/terminal/",
  define: { __APP_VERSION__: JSON.stringify(appVersion()) },
  plugins: [react()],
  server: {
    port: 5180,
    strictPort: true,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
