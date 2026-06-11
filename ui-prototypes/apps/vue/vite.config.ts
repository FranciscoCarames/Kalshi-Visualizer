import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5176, strictPort: true,
    fs: { allow: ["../../"] },
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, "") } },
  },
  optimizeDeps: { exclude: ["@bakeoff/shared"] },
});
