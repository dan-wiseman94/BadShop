import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import prefixSelector from "postcss-prefix-selector";
export default defineConfig({
  plugins: [react(), tailwindcss()],
  css: {
    postcss: {
      plugins: [prefixSelector({
        prefix: ':root:is([data-theme="classic"], [data-theme="geocities"])',
        includeFiles: [/[/\\]98\.css[/\\]dist[/\\]98\.css$/],
      }), prefixSelector({
        prefix: ':root[data-theme="xp"]',
        includeFiles: [/[/\\]xp\.css[/\\]dist[/\\]XP\.css$/],
      }), prefixSelector({
        prefix: ':root[data-theme="arcade"]',
        includeFiles: [/[/\\]vendor[/\\]nes-buttons\.css$/],
        transform(prefix, selector) {
          return `${prefix} ${selector.replace(/\.nes-btn/g, ':is(.nes-btn, button)').replace(/\.is-primary/g, ':is(.is-primary, .primary, .export, .send)').replace(/\.is-disabled/g, ':disabled')}`;
        },
      }), prefixSelector({
        prefix: ':root[data-theme="terminal"]',
        includeFiles: [/[/\\]terminal\.css[/\\]dist[/\\]terminal\.css$/],
        transform(prefix, selector) {
          if (selector === ':root' || selector === 'body') return prefix;
          return `${prefix} ${selector.replace(/\.btn(?![\w-])/g, ':is(.btn, button)')}`;
        },
      })],
    },
  },
  clearScreen: false,
  server: { host: "127.0.0.1", port: 1420, strictPort: true },
  envPrefix: ["VITE_", "TAURI_ENV_"],
  build: { target: "es2022" },
});
