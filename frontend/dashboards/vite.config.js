import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

// Standalone presentation app. Unlike v07 it needs no backend proxy — every
// dashboard runs a faithful, self-contained client-side simulation of the real
// layer logic (seeded with the real config values), so it presents reliably
// with no GPU / Qdrant / API-key dependency. Port is offset from v07's 5173 so
// both can run side by side.
export default defineConfig({
  plugins: [svelte()],
  server: { port: 5273, open: false },
  preview: { port: 5274 },
})
