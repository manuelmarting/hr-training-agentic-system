import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../backend/app/static",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      // Overridden in Docker Compose (`VITE_API_PROXY_TARGET=http://backend:8000`):
      // the dev server runs inside its own container there, so "localhost" would
      // otherwise point at itself instead of the backend service.
      "/api": process.env.VITE_API_PROXY_TARGET || "http://localhost:8000",
    },
  },
});
