import preact from "@preact/preset-vite";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

function precargaFuente(): Plugin {
  return {
    name: "precarga-fuente",
    apply: "build",
    transformIndexHtml: {
      order: "post",
      handler(_html, ctx) {
        const archivo = Object.keys(ctx.bundle ?? {}).find((n) => /ibm-plex-sans-latin-wght-normal.*\.woff2$/.test(n));
        if (!archivo) return [];
        return [
          {
            tag: "link",
            injectTo: "head",
            attrs: { rel: "preload", as: "font", type: "font/woff2", crossorigin: "", href: `/${archivo}` },
          },
        ];
      },
    },
  };
}

export default defineConfig({
  base: "/",
  plugins: [preact(), precargaFuente()],
  build: {
    outDir: "../backend/tutela2/static/dist",
    emptyOutDir: true,
    assetsDir: "assets",
    assetsInlineLimit: 0,
    modulePreload: { polyfill: false },
    sourcemap: false,
  },
  server: {
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["src/pruebas/preparar.ts"],
  },
});
