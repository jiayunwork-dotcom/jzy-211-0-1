import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 开发态把 /api 代理到后端容器；生产由 nginx 反代
export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
