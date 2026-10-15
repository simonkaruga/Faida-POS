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
    proxy: {
      // In development the counter backend runs on 8000 and the cloud backend on 8100.
      "/api": "http://localhost:8000",
      "/cloud": { target: "http://localhost:8100", rewrite: (path) => path.replace(/^\/cloud/, "") },
    },
  },
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.{ts,tsx}"],
  },
});
