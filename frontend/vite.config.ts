import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const backend = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 43117,
    strictPort: true,
    proxy: {
      "/api": { target: backend, changeOrigin: true },
      "/docs": { target: backend, changeOrigin: true },
      "/redoc": { target: backend, changeOrigin: true },
      "/openapi.json": { target: backend, changeOrigin: true },
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 43118,
    strictPort: true,
  },
});
