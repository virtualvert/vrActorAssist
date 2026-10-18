import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// `bun run dev` serves the UI on :5173. Without a running agent it starts in demo mode;
// with `python -m agent --dev` on :47800 the /api and /ui requests are proxied to it.
const AGENT = "http://127.0.0.1:47800";

export default defineConfig({
  plugins: [svelte()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: AGENT, changeOrigin: true },
      "/ui": { target: AGENT, changeOrigin: true, ws: true },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    target: "es2022",
  },
});
