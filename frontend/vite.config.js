import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// This app is built and its output is served BY the FastAPI backend itself,
// at /dashboard/ (see backend/main.py's StaticFiles mount) - no separate
// Node server in production. `base` matches that mount path so built asset
// URLs resolve correctly. In dev (`npm run dev`), the proxy below forwards
// API calls to the FastAPI server so you don't need CORS or two origins.
export default defineConfig({
  base: "/dashboard/",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/jobs": "http://127.0.0.1:8000",
      "/meta": "http://127.0.0.1:8000",
    },
  },
  build: {
    outDir: "../backend/static",
    emptyOutDir: true,
  },
});
