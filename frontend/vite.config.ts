import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { execSync } from "node:child_process";

// App version string injected at build time: git short SHA (+ "-dirty" if the tree has uncommitted
// changes) and the build date. Surfaced via `__APP_VERSION__` and shown in the footer so the running
// version is always visible. Fails open to "unknown" if git isn't available.
function appVersion(): string {
  let v = "unknown";
  try {
    const sha = execSync("git rev-parse --short HEAD", { stdio: ["ignore", "pipe", "ignore"] }).toString().trim();
    // Only TRACKED uncommitted changes count as "dirty" (git describe --dirty convention) — untracked
    // scratch (dist, logs) must not flip a clean committed build to "-dirty".
    const dirty = execSync("git status --porcelain --untracked-files=no", { stdio: ["ignore", "pipe", "ignore"] }).toString().trim() ? "-dirty" : "";
    v = sha + dirty;
  } catch { /* no git → keep "unknown" */ }
  return `${v} · ${new Date().toISOString().slice(0, 10)}`;
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
