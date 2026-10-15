/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    // In development the backend runs separately on port 8000.
    proxy: { "/api": "http://localhost:8000" },
  },
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.{ts,tsx}"],
  },
});
