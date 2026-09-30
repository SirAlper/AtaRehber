import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The API runs on its own port in development; the dev server forwards /api to it, so the browser talks to one
// origin (the refresh token cookie and streaming work as in production behind nginx).
const apiTarget = process.env.API_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: apiTarget },
      "/health": { target: apiTarget },
    },
  },
  build: {
    // No source maps in the shipped bundle; everything (fonts included) is bundled, nothing loads from a CDN
    sourcemap: false,
    rollupOptions: {
      output: {
        // Libraries change less often than the app: separate files stay cached across updates
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          markdown: ["react-markdown", "remark-gfm"],
          data: ["@tanstack/react-query", "i18next", "react-i18next"],
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
