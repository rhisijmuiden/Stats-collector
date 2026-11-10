import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8080", "/help-assets": "http://127.0.0.1:8080" },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 900,
    rollupOptions: { output: { manualChunks: { charts: ["echarts/core", "echarts/charts", "echarts/components", "echarts/renderers"] } } },
  },
});
