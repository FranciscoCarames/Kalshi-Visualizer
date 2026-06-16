import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The SPA is served at /terminal in production (FastAPI StaticFiles), so the built asset base is
// /terminal/. In dev, proxy /api/* straight through to serve.py on :8000 WITHOUT rewriting the path
// (the live feed lives at /api/terminal/feed) — same path in dev and prod, no surprises.
export default defineConfig({
  base: "/terminal/",
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
