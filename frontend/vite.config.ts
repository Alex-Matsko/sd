import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: loadEnv(mode, ".", "").API_PROXY_TARGET ?? "http://localhost:8080", changeOrigin: true, ws: true, rewrite: (path) => path.replace(/^\/api/, "") } },
  },
}));
