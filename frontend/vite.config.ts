/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      // index.html: the counter screens (local backend); phone.html: the owner's phone (cloud).
      input: { counter: resolve(__dirname, "index.html"), phone: resolve(__dirname, "phone.html") },
    },
  },
  server: {
    // Development ports stay clear of the usual 8000/5173, so other projects can run
    // alongside. An installed counter still serves everything on 8000.
    port: 5180,
    strictPort: true,
    proxy: {
      // In development the counter backend runs on 8010 and the cloud backend on 8110.
      "/api": "http://localhost:8010",
      "/cloud": { target: "http://localhost:8110", rewrite: (path) => path.replace(/^\/cloud/, "") },
    },
  },
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.{ts,tsx}"],
  },
});
