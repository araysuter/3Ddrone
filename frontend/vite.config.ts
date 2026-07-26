import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  plugins: [react()],
  cacheDir:
    process.env.VITE_PUBLIC_SHARE_BUILD === "true"
      ? "node_modules/.vite-public"
      : "node_modules/.vite-operator",
  resolve: {
    alias: {
      "@mapper-app": fileURLToPath(
        new URL(
          process.env.VITE_PUBLIC_SHARE_BUILD === "true"
            ? "./src/PublicApp.tsx"
            : "./src/App.tsx",
          import.meta.url,
        ),
      ),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
