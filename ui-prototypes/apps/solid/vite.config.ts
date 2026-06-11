import { defineConfig } from "vite";
import solid from "vite-plugin-solid";

export default defineConfig({
  plugins: [solid()],
  server: {
    port: 5174, strictPort: true,
    fs: { allow: ["../../"] },
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, "") } },
  },
  optimizeDeps: { exclude: ["@bakeoff/shared"] },
});
