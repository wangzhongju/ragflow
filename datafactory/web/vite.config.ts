import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/factory/",
  plugins: [react()],
  server: {
    port: 9391,
    proxy: {
      "/api/factory": "http://127.0.0.1:9390",
    },
  },
});
